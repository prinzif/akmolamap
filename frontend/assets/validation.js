/**
 * Input Validation Helpers
 *
 * Provides validation functions for:
 * - Coordinates and bounding boxes
 * - Dates and date ranges
 * - Numeric values
 * - String inputs
 *
 * @module validation
 */

import {
    MIN_NDVI_VALUE,
    MAX_NDVI_VALUE,
    MAX_DATE_RANGE_DAYS,
    MAX_BBOX_AREA
} from './constants.js';

/**
 * Validation result object
 * @typedef {Object} ValidationResult
 * @property {boolean} valid - Whether the input is valid
 * @property {string} [error] - Error message if invalid
 * @property {*} [value] - Sanitized/parsed value if valid
 */

/**
 * Validate a coordinate value (latitude or longitude)
 * @param {number} value - Coordinate value
 * @param {string} type - Type of coordinate ('lat' or 'lon')
 * @returns {ValidationResult} Validation result
 */
export function validateCoordinate(value, type) {
    if (typeof value !== 'number' || isNaN(value)) {
        return {
            valid: false,
            error: `${type === 'lat' ? 'Широта' : 'Долгота'} должна быть числом`
        };
    }

    const isLat = type === 'lat';
    const min = isLat ? -90 : -180;
    const max = isLat ? 90 : 180;

    if (value < min || value > max) {
        return {
            valid: false,
            error: `${type === 'lat' ? 'Широта' : 'Долгота'} должна быть между ${min} и ${max}`
        };
    }

    return { valid: true, value };
}

/**
 * Validate a bounding box
 * @param {Array<number>} bbox - Bounding box [minLon, minLat, maxLon, maxLat]
 * @returns {ValidationResult} Validation result
 */
export function validateBoundingBox(bbox) {
    if (!Array.isArray(bbox) || bbox.length !== 4) {
        return {
            valid: false,
            error: 'Bounding box должен содержать 4 координаты'
        };
    }

    const [minLon, minLat, maxLon, maxLat] = bbox;

    // Validate individual coordinates
    const validations = [
        validateCoordinate(minLon, 'lon'),
        validateCoordinate(minLat, 'lat'),
        validateCoordinate(maxLon, 'lon'),
        validateCoordinate(maxLat, 'lat')
    ];

    for (const result of validations) {
        if (!result.valid) {
            return result;
        }
    }

    // Validate min < max
    if (minLon >= maxLon) {
        return {
            valid: false,
            error: 'Минимальная долгота должна быть меньше максимальной'
        };
    }

    if (minLat >= maxLat) {
        return {
            valid: false,
            error: 'Минимальная широта должна быть меньше максимальной'
        };
    }

    // Validate area
    const width = maxLon - minLon;
    const height = maxLat - minLat;
    const area = width * height;

    if (area > MAX_BBOX_AREA) {
        return {
            valid: false,
            error: `Площадь bbox слишком большая (максимум ${MAX_BBOX_AREA} кв.градусов)`
        };
    }

    return { valid: true, value: bbox };
}

/**
 * Validate a date string
 * @param {string} dateStr - Date string (YYYY-MM-DD)
 * @param {string} label - Label for error messages
 * @returns {ValidationResult} Validation result with Date object
 */
export function validateDate(dateStr, label = 'Дата') {
    if (!dateStr || typeof dateStr !== 'string') {
        return {
            valid: false,
            error: `${label} не указана`
        };
    }

    // Check format
    const datePattern = /^\d{4}-\d{2}-\d{2}$/;
    if (!datePattern.test(dateStr)) {
        return {
            valid: false,
            error: `${label} должна быть в формате YYYY-MM-DD`
        };
    }

    // Parse date
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) {
        return {
            valid: false,
            error: `${label} некорректна`
        };
    }

    // Check if date is not in the future
    const now = new Date();
    if (date > now) {
        return {
            valid: false,
            error: `${label} не может быть в будущем`
        };
    }

    // Check if date is not too old (e.g., before 2015 when Sentinel-2 launched)
    const minDate = new Date('2015-01-01');
    if (date < minDate) {
        return {
            valid: false,
            error: `${label} не может быть ранее 2015-01-01 (запуск Sentinel-2)`
        };
    }

    return { valid: true, value: date };
}

/**
 * Validate a date range
 * @param {string} startDate - Start date (YYYY-MM-DD)
 * @param {string} endDate - End date (YYYY-MM-DD)
 * @returns {ValidationResult} Validation result
 */
export function validateDateRange(startDate, endDate) {
    // Validate individual dates
    const startResult = validateDate(startDate, 'Начальная дата');
    if (!startResult.valid) {
        return startResult;
    }

    const endResult = validateDate(endDate, 'Конечная дата');
    if (!endResult.valid) {
        return endResult;
    }

    // Check start < end
    if (startResult.value >= endResult.value) {
        return {
            valid: false,
            error: 'Начальная дата должна быть раньше конечной'
        };
    }

    // Check range not too long
    const diffDays = (endResult.value - startResult.value) / (1000 * 60 * 60 * 24);
    if (diffDays > MAX_DATE_RANGE_DAYS) {
        return {
            valid: false,
            error: `Диапазон дат не может превышать ${MAX_DATE_RANGE_DAYS} дней`
        };
    }

    return {
        valid: true,
        value: {
            start: startResult.value,
            end: endResult.value,
            days: Math.ceil(diffDays)
        }
    };
}

/**
 * Validate a numeric value within range
 * @param {number} value - Value to validate
 * @param {Object} options - Validation options
 * @param {number} options.min - Minimum value (inclusive)
 * @param {number} options.max - Maximum value (inclusive)
 * @param {string} options.label - Label for error messages
 * @param {boolean} options.integer - Whether value must be an integer
 * @returns {ValidationResult} Validation result
 */
export function validateNumber(value, options = {}) {
    const {
        min = -Infinity,
        max = Infinity,
        label = 'Значение',
        integer = false
    } = options;

    if (typeof value !== 'number' || isNaN(value)) {
        return {
            valid: false,
            error: `${label} должно быть числом`
        };
    }

    if (integer && !Number.isInteger(value)) {
        return {
            valid: false,
            error: `${label} должно быть целым числом`
        };
    }

    if (value < min) {
        return {
            valid: false,
            error: `${label} не может быть меньше ${min}`
        };
    }

    if (value > max) {
        return {
            valid: false,
            error: `${label} не может быть больше ${max}`
        };
    }

    return { valid: true, value };
}

/**
 * Validate NDVI value
 * @param {number} value - NDVI value
 * @returns {ValidationResult} Validation result
 */
export function validateNDVI(value) {
    return validateNumber(value, {
        min: MIN_NDVI_VALUE,
        max: MAX_NDVI_VALUE,
        label: 'NDVI'
    });
}

/**
 * Validate a non-empty string
 * @param {string} value - String value
 * @param {Object} options - Validation options
 * @param {number} options.minLength - Minimum length
 * @param {number} options.maxLength - Maximum length
 * @param {string} options.label - Label for error messages
 * @param {RegExp} options.pattern - Pattern to match
 * @returns {ValidationResult} Validation result
 */
export function validateString(value, options = {}) {
    const {
        minLength = 0,
        maxLength = Infinity,
        label = 'Значение',
        pattern = null
    } = options;

    if (typeof value !== 'string') {
        return {
            valid: false,
            error: `${label} должно быть строкой`
        };
    }

    const trimmed = value.trim();

    if (minLength > 0 && trimmed.length < minLength) {
        return {
            valid: false,
            error: `${label} должно содержать минимум ${minLength} символов`
        };
    }

    if (trimmed.length > maxLength) {
        return {
            valid: false,
            error: `${label} не может содержать более ${maxLength} символов`
        };
    }

    if (pattern && !pattern.test(trimmed)) {
        return {
            valid: false,
            error: `${label} имеет некорректный формат`
        };
    }

    return { valid: true, value: trimmed };
}

/**
 * Validate BIOPAR type
 * @param {string} value - BIOPAR type
 * @returns {ValidationResult} Validation result
 */
export function validateBioparType(value) {
    const validTypes = ['FAPAR', 'LAI', 'FCOVER', 'CCC', 'CWC'];

    if (!validTypes.includes(value)) {
        return {
            valid: false,
            error: `Тип BIOPAR должен быть одним из: ${validTypes.join(', ')}`
        };
    }

    return { valid: true, value };
}

/**
 * Sanitize user input to prevent XSS
 * @param {string} input - User input
 * @returns {string} Sanitized input
 */
export function sanitizeInput(input) {
    if (typeof input !== 'string') {
        return '';
    }

    const div = document.createElement('div');
    div.textContent = input;
    return div.innerHTML;
}

/**
 * Validate form data
 * @param {Object} formData - Form data to validate
 * @param {Object} schema - Validation schema
 * @returns {Object} Validation results {valid, errors, values}
 *
 * @example
 * const schema = {
 *   bbox: { validator: validateBoundingBox, required: true },
 *   startDate: { validator: (v) => validateDate(v, 'Start'), required: true },
 *   endDate: { validator: (v) => validateDate(v, 'End'), required: true }
 * };
 *
 * const result = validateForm(formData, schema);
 * if (!result.valid) {
 *   console.error('Validation errors:', result.errors);
 * }
 */
export function validateForm(formData, schema) {
    const errors = {};
    const values = {};
    let valid = true;

    for (const [field, config] of Object.entries(schema)) {
        const value = formData[field];
        const { validator, required = false } = config;

        // Check required fields
        if (required && (value === null || value === undefined || value === '')) {
            errors[field] = 'Поле обязательно для заполнения';
            valid = false;
            continue;
        }

        // Skip validation if field is empty and not required
        if (!required && (value === null || value === undefined || value === '')) {
            continue;
        }

        // Run validator
        const result = validator(value);
        if (!result.valid) {
            errors[field] = result.error;
            valid = false;
        } else {
            values[field] = result.value;
        }
    }

    return { valid, errors, values };
}

/**
 * Display validation errors in the UI
 * @param {Object} errors - Errors object from validateForm
 * @param {string} containerId - Container element ID for error display
 */
export function displayValidationErrors(errors, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    // Clear previous errors
    container.innerHTML = '';

    if (Object.keys(errors).length === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'block';

    const errorList = document.createElement('ul');
    errorList.className = 'validation-errors';

    for (const [field, error] of Object.entries(errors)) {
        const li = document.createElement('li');
        li.textContent = `${field}: ${error}`;
        errorList.appendChild(li);
    }

    container.appendChild(errorList);
}

export default {
    validateCoordinate,
    validateBoundingBox,
    validateDate,
    validateDateRange,
    validateNumber,
    validateNDVI,
    validateString,
    validateBioparType,
    sanitizeInput,
    validateForm,
    displayValidationErrors
};
