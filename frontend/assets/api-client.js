/**
 * API Client for Akmola Sentinel API
 *
 * Centralized API client with:
 * - Automatic error handling
 * - Request cancellation support
 * - Retry logic with exponential backoff
 * - Request ID tracking
 * - Consistent response formatting
 *
 * @module api-client
 */

import {
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    ERROR_NETWORK,
    ERROR_TIMEOUT,
    ERROR_GENERIC
} from './constants.js';

/**
 * API Client class for making requests to the backend
 */
export class APIClient {
    /**
     * Create an API client
     * @param {string} baseURL - Base URL for API requests
     * @param {Object} options - Client options
     * @param {number} options.timeout - Request timeout in milliseconds
     * @param {number} options.maxRetries - Maximum retry attempts
     * @param {number} options.retryDelay - Initial retry delay in milliseconds
     */
    constructor(baseURL = '', options = {}) {
        this.baseURL = baseURL;
        this.timeout = options.timeout || REQUEST_TIMEOUT;
        this.maxRetries = options.maxRetries || MAX_RETRIES;
        this.retryDelay = options.retryDelay || RETRY_DELAY;
        this.activeRequests = new Map();
    }

    /**
     * Generate a unique request ID
     * @returns {string} UUID v4 string
     * @private
     */
    _generateRequestId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    /**
     * Create an AbortController with timeout
     * @param {number} timeout - Timeout in milliseconds
     * @returns {AbortController} Abort controller
     * @private
     */
    _createAbortController(timeout) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);

        // Store timeout ID for cleanup
        controller.timeoutId = timeoutId;

        return controller;
    }

    /**
     * Make an HTTP request with retry logic
     * @param {string} endpoint - API endpoint (relative to baseURL)
     * @param {Object} options - Fetch options
     * @param {string} options.method - HTTP method
     * @param {Object} options.headers - Request headers
     * @param {*} options.body - Request body
     * @param {AbortSignal} options.signal - Abort signal
     * @param {number} options.retryCount - Current retry count (internal)
     * @returns {Promise<Object>} Response data
     * @throws {Error} Network error, timeout, or API error
     */
    async request(endpoint, options = {}) {
        const {
            method = 'GET',
            headers = {},
            body = null,
            signal = null,
            retryCount = 0
        } = options;

        // Generate request ID
        const requestId = this._generateRequestId();

        // Create abort controller if no signal provided
        const controller = signal ? null : this._createAbortController(this.timeout);
        const fetchSignal = signal || controller.signal;

        // Store active request for cancellation
        this.activeRequests.set(requestId, controller || { abort: () => {}, signal });

        // Construct URL
        const url = this.baseURL + endpoint;

        // Prepare headers
        const requestHeaders = {
            'Content-Type': 'application/json',
            'X-Request-ID': requestId,
            ...headers
        };

        // Prepare fetch options
        const fetchOptions = {
            method,
            headers: requestHeaders,
            signal: fetchSignal
        };

        if (body && method !== 'GET' && method !== 'HEAD') {
            fetchOptions.body = typeof body === 'string' ? body : JSON.stringify(body);
        }

        try {
            // Make request
            const response = await fetch(url, fetchOptions);

            // Clean up
            if (controller) {
                clearTimeout(controller.timeoutId);
            }
            this.activeRequests.delete(requestId);

            // Handle HTTP errors
            if (!response.ok) {
                const error = await this._handleErrorResponse(response);

                // Retry on 5xx errors
                if (response.status >= 500 && retryCount < this.maxRetries) {
                    return await this._retryRequest(endpoint, options, retryCount);
                }

                throw error;
            }

            // Parse response
            const data = await response.json();

            return {
                success: true,
                data,
                requestId,
                status: response.status,
                headers: this._parseHeaders(response.headers)
            };

        } catch (error) {
            // Clean up
            if (controller) {
                clearTimeout(controller.timeoutId);
            }
            this.activeRequests.delete(requestId);

            // Handle abort
            if (error.name === 'AbortError') {
                throw new Error(ERROR_TIMEOUT);
            }

            // Handle network errors with retry
            if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
                if (retryCount < this.maxRetries) {
                    return await this._retryRequest(endpoint, options, retryCount);
                }
                throw new Error(ERROR_NETWORK);
            }

            // Re-throw other errors
            throw error;
        }
    }

    /**
     * Handle error response from API
     * @param {Response} response - Fetch response
     * @returns {Promise<Error>} Error object
     * @private
     */
    async _handleErrorResponse(response) {
        let message = ERROR_GENERIC;

        try {
            const errorData = await response.json();
            message = errorData.detail || errorData.message || message;
        } catch (e) {
            // Failed to parse error response
            message = `HTTP ${response.status}: ${response.statusText}`;
        }

        const error = new Error(message);
        error.status = response.status;
        error.response = response;

        return error;
    }

    /**
     * Retry a failed request with exponential backoff
     * @param {string} endpoint - API endpoint
     * @param {Object} options - Request options
     * @param {number} retryCount - Current retry count
     * @returns {Promise<Object>} Response data
     * @private
     */
    async _retryRequest(endpoint, options, retryCount) {
        const delay = this.retryDelay * Math.pow(2, retryCount);

        console.warn(`Request failed, retrying in ${delay}ms (attempt ${retryCount + 1}/${this.maxRetries})`);

        await new Promise(resolve => setTimeout(resolve, delay));

        return await this.request(endpoint, {
            ...options,
            retryCount: retryCount + 1
        });
    }

    /**
     * Parse response headers into object
     * @param {Headers} headers - Response headers
     * @returns {Object} Headers object
     * @private
     */
    _parseHeaders(headers) {
        const result = {};
        for (const [key, value] of headers.entries()) {
            result[key] = value;
        }
        return result;
    }

    /**
     * Cancel a specific request by ID
     * @param {string} requestId - Request ID to cancel
     */
    cancelRequest(requestId) {
        const controller = this.activeRequests.get(requestId);
        if (controller) {
            controller.abort();
            this.activeRequests.delete(requestId);
        }
    }

    /**
     * Cancel all active requests
     */
    cancelAllRequests() {
        for (const [requestId, controller] of this.activeRequests.entries()) {
            controller.abort();
        }
        this.activeRequests.clear();
    }

    /**
     * GET request
     * @param {string} endpoint - API endpoint
     * @param {Object} params - Query parameters
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} Response data
     */
    async get(endpoint, params = {}, options = {}) {
        const queryString = new URLSearchParams(params).toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;

        return await this.request(url, {
            ...options,
            method: 'GET'
        });
    }

    /**
     * POST request
     * @param {string} endpoint - API endpoint
     * @param {*} body - Request body
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} Response data
     */
    async post(endpoint, body, options = {}) {
        return await this.request(endpoint, {
            ...options,
            method: 'POST',
            body
        });
    }

    /**
     * PUT request
     * @param {string} endpoint - API endpoint
     * @param {*} body - Request body
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} Response data
     */
    async put(endpoint, body, options = {}) {
        return await this.request(endpoint, {
            ...options,
            method: 'PUT',
            body
        });
    }

    /**
     * DELETE request
     * @param {string} endpoint - API endpoint
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} Response data
     */
    async delete(endpoint, options = {}) {
        return await this.request(endpoint, {
            ...options,
            method: 'DELETE'
        });
    }
}

/**
 * Default API client instance
 */
export const apiClient = new APIClient('/api/v1');

/**
 * API endpoints organized by resource
 */
export const API = {
    // NDVI endpoints
    ndvi: {
        /**
         * Get NDVI GeoTIFF
         * @param {Object} params - Request parameters
         * @param {Array<number>} params.bbox - Bounding box [minLon, minLat, maxLon, maxLat]
         * @param {string} params.start - Start date (YYYY-MM-DD)
         * @param {string} params.end - End date (YYYY-MM-DD)
         * @param {number} params.width - Image width in pixels
         * @param {number} params.height - Image height in pixels
         * @returns {Promise<Object>} Response with file_url
         */
        geotiff: (params) => apiClient.get('/ndvi/geotiff', params),

        /**
         * Get NDVI statistics
         * @param {Object} params - Request parameters
         * @param {Array<number>} params.bbox - Bounding box
         * @param {string} params.start - Start date
         * @param {string} params.end - End date
         * @returns {Promise<Object>} Statistics data
         */
        statistics: (params) => apiClient.get('/ndvi/statistics', params),

        /**
         * Get NDVI timeline
         * @param {Object} params - Request parameters
         * @param {Array<number>} params.bbox - Bounding box
         * @param {string} params.start - Start date
         * @param {string} params.end - End date
         * @param {number} params.interval_days - Interval between data points
         * @returns {Promise<Object>} Timeline data
         */
        timeline: (params) => apiClient.get('/ndvi/timeline', params),

        /**
         * Get NDVI report
         * @param {Object} params - Request parameters
         * @returns {Promise<Object>} Report data
         */
        report: (params) => apiClient.get('/ndvi/report', params)
    },

    // BIOPAR endpoints
    biopar: {
        /**
         * Get BIOPAR GeoTIFF
         * @param {Object} params - Request parameters
         * @param {Array<number>} params.bbox - Bounding box
         * @param {string} params.start - Start date
         * @param {string} params.end - End date
         * @param {string} params.biopar_type - BIOPAR type (FAPAR, LAI, FCOVER, CCC, CWC)
         * @returns {Promise<Object>} Response with file_url
         */
        geotiff: (params) => apiClient.get('/biopar/geotiff', params),

        /**
         * Get BIOPAR statistics
         * @param {Object} params - Request parameters
         * @returns {Promise<Object>} Statistics data
         */
        statistics: (params) => apiClient.get('/biopar/statistics', params),

        /**
         * Get BIOPAR timeline
         * @param {Object} params - Request parameters
         * @returns {Promise<Object>} Timeline data
         */
        timeline: (params) => apiClient.get('/biopar/timeline', params),

        /**
         * Get BIOPAR report
         * @param {Object} params - Request parameters
         * @returns {Promise<Object>} Report data
         */
        report: (params) => apiClient.get('/biopar/report', params)
    },

    // Meta endpoints
    meta: {
        /**
         * Health check
         * @returns {Promise<Object>} Health status
         */
        health: () => apiClient.get('/health'),

        /**
         * Get API metrics
         * @returns {Promise<Object>} Metrics data
         */
        metrics: () => apiClient.get('/metrics'),

        /**
         * Get metrics summary
         * @returns {Promise<Object>} Metrics summary
         */
        metricsSummary: () => apiClient.get('/metrics/summary'),

        /**
         * Get cache status
         * @returns {Promise<Object>} Cache status
         */
        cacheStatus: () => apiClient.get('/cache/status'),

        /**
         * Get job status
         * @param {string} jobId - Job ID
         * @returns {Promise<Object>} Job status
         */
        jobStatus: (jobId) => apiClient.get(`/jobs/${jobId}`),

        /**
         * List jobs
         * @param {Object} params - Query parameters
         * @param {string} params.status - Filter by status
         * @param {string} params.job_type - Filter by job type
         * @param {number} params.limit - Limit results
         * @returns {Promise<Object>} Jobs list
         */
        listJobs: (params) => apiClient.get('/jobs', params)
    }
};

export default apiClient;
