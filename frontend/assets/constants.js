/**
 * Frontend Constants and Configuration
 * Centralized constants for animation, timing, and UI behavior
 */

// ============================================
// Animation & Timing Constants
// ============================================

/**
 * Default animation speed in milliseconds
 * @type {number}
 */
export const DEFAULT_ANIMATION_SPEED = 1000;

/**
 * Minimum animation speed in milliseconds
 * @type {number}
 */
export const MIN_ANIMATION_SPEED = 100;

/**
 * Maximum animation speed in milliseconds
 * @type {number}
 */
export const MAX_ANIMATION_SPEED = 3000;

/**
 * Animation speed step for slider
 * @type {number}
 */
export const ANIMATION_SPEED_STEP = 100;

/**
 * Debounce delay for map movement (milliseconds)
 * @type {number}
 */
export const MAP_MOVE_DEBOUNCE = 2000;

/**
 * Toast notification display duration (milliseconds)
 * @type {number}
 */
export const TOAST_DURATION = 2000;

/**
 * Loading spinner delay before showing (milliseconds)
 * @type {number}
 */
export const LOADING_DELAY = 100;


// ============================================
// Network & API Constants
// ============================================

/**
 * Default request timeout (milliseconds)
 * @type {number}
 */
export const REQUEST_TIMEOUT = 30000;

/**
 * Maximum retries for failed requests
 * @type {number}
 */
export const MAX_RETRIES = 3;

/**
 * Retry delay for failed requests (milliseconds)
 * @type {number}
 */
export const RETRY_DELAY = 3000;

/**
 * Overpass API timeout (milliseconds)
 * @type {number}
 */
export const OVERPASS_TIMEOUT = 30000;

/**
 * Maximum wait time for polling operations (milliseconds)
 * @type {number}
 */
export const MAX_POLL_WAIT = 10000;


// ============================================
// UI & CSS Constants
// ============================================

/**
 * CSS class for active state
 * @type {string}
 */
export const CLASS_ACTIVE = 'active';

/**
 * CSS class for disabled state
 * @type {string}
 */
export const CLASS_DISABLED = 'disabled';

/**
 * CSS class for loading state
 * @type {string}
 */
export const CLASS_LOADING = 'loading';

/**
 * CSS class for error state
 * @type {string}
 */
export const CLASS_ERROR = 'error';

/**
 * CSS class for success state
 * @type {string}
 */
export const CLASS_SUCCESS = 'success';

/**
 * Z-index for modals and overlays
 * @type {number}
 */
export const Z_INDEX_MODAL = 10000;

/**
 * Z-index for tooltips
 * @type {number}
 */
export const Z_INDEX_TOOLTIP = 9999;

/**
 * Z-index for loading spinners
 * @type {number}
 */
export const Z_INDEX_LOADING = 9998;


// ============================================
// Map Constants
// ============================================

/**
 * Default map center (latitude, longitude)
 * @type {[number, number]}
 */
export const DEFAULT_MAP_CENTER = [52.5, 71.5];

/**
 * Default map zoom level
 * @type {number}
 */
export const DEFAULT_MAP_ZOOM = 7;

/**
 * Minimum map zoom level
 * @type {number}
 */
export const MIN_MAP_ZOOM = 5;

/**
 * Maximum map zoom level
 * @type {number}
 */
export const MAX_MAP_ZOOM = 18;


// ============================================
// Data Validation Constants
// ============================================

/**
 * Maximum number of timeline points to display
 * @type {number}
 */
export const MAX_TIMELINE_POINTS = 100;

/**
 * Maximum bbox area in square degrees
 * @type {number}
 */
export const MAX_BBOX_AREA = 100;

/**
 * Minimum NDVI value
 * @type {number}
 */
export const MIN_NDVI_VALUE = -1.0;

/**
 * Maximum NDVI value
 * @type {number}
 */
export const MAX_NDVI_VALUE = 1.0;


// ============================================
// Date & Time Constants
// ============================================

/**
 * Date format for display (Russian locale)
 * @type {string}
 */
export const DATE_FORMAT_DISPLAY = 'DD.MM.YYYY';

/**
 * Date format for API (ISO 8601)
 * @type {string}
 */
export const DATE_FORMAT_API = 'YYYY-MM-DD';

/**
 * Maximum date range in days
 * @type {number}
 */
export const MAX_DATE_RANGE_DAYS = 365;


// ============================================
// Chart Constants
// ============================================

/**
 * Default chart height in pixels
 * @type {number}
 */
export const CHART_HEIGHT = 300;

/**
 * Chart animation duration (milliseconds)
 * @type {number}
 */
export const CHART_ANIMATION_DURATION = 750;

/**
 * Chart point radius
 * @type {number}
 */
export const CHART_POINT_RADIUS = 3;

/**
 * Chart hover point radius
 * @type {number}
 */
export const CHART_HOVER_RADIUS = 5;


// ============================================
// Storage Constants
// ============================================

/**
 * Local storage key prefix
 * @type {string}
 */
export const STORAGE_PREFIX = 'akmola_';

/**
 * Maximum localStorage usage (bytes)
 * @type {number}
 */
export const MAX_STORAGE_SIZE = 5 * 1024 * 1024; // 5MB


// ============================================
// Error Messages
// ============================================

/**
 * Generic error message
 * @type {string}
 */
export const ERROR_GENERIC = 'Произошла ошибка. Пожалуйста, попробуйте позже.';

/**
 * Network error message
 * @type {string}
 */
export const ERROR_NETWORK = 'Ошибка сети. Проверьте подключение к интернету.';

/**
 * Timeout error message
 * @type {string}
 */
export const ERROR_TIMEOUT = 'Превышено время ожидания. Попробуйте позже.';

/**
 * No data error message
 * @type {string}
 */
export const ERROR_NO_DATA = 'Нет данных для отображения.';

/**
 * Invalid input error message
 * @type {string}
 */
export const ERROR_INVALID_INPUT = 'Некорректные входные данные.';


// ============================================
// Export all constants as default object
// ============================================

export default {
    // Animation & Timing
    DEFAULT_ANIMATION_SPEED,
    MIN_ANIMATION_SPEED,
    MAX_ANIMATION_SPEED,
    ANIMATION_SPEED_STEP,
    MAP_MOVE_DEBOUNCE,
    TOAST_DURATION,
    LOADING_DELAY,

    // Network & API
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_DELAY,
    OVERPASS_TIMEOUT,
    MAX_POLL_WAIT,

    // UI & CSS
    CLASS_ACTIVE,
    CLASS_DISABLED,
    CLASS_LOADING,
    CLASS_ERROR,
    CLASS_SUCCESS,
    Z_INDEX_MODAL,
    Z_INDEX_TOOLTIP,
    Z_INDEX_LOADING,

    // Map
    DEFAULT_MAP_CENTER,
    DEFAULT_MAP_ZOOM,
    MIN_MAP_ZOOM,
    MAX_MAP_ZOOM,

    // Data Validation
    MAX_TIMELINE_POINTS,
    MAX_BBOX_AREA,
    MIN_NDVI_VALUE,
    MAX_NDVI_VALUE,

    // Date & Time
    DATE_FORMAT_DISPLAY,
    DATE_FORMAT_API,
    MAX_DATE_RANGE_DAYS,

    // Chart
    CHART_HEIGHT,
    CHART_ANIMATION_DURATION,
    CHART_POINT_RADIUS,
    CHART_HOVER_RADIUS,

    // Storage
    STORAGE_PREFIX,
    MAX_STORAGE_SIZE,

    // Error Messages
    ERROR_GENERIC,
    ERROR_NETWORK,
    ERROR_TIMEOUT,
    ERROR_NO_DATA,
    ERROR_INVALID_INPUT
};
