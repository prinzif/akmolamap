/**
 * Common utility functions for XSS prevention and safe DOM manipulation
 */

/**
 * Escapes HTML special characters to prevent XSS attacks
 * @param {string} text - Unsafe text from user input or API
 * @returns {string} - HTML-safe string
 */
function escapeHtml(text) {
  if (text === null || text === undefined) {
    return '';
  }

  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

/**
 * Safely sets text content (prevents XSS)
 * Use this instead of innerHTML when displaying user data
 * @param {HTMLElement} element - DOM element
 * @param {string} text - Text to display
 */
function setTextSafe(element, text) {
  if (!element) return;
  element.textContent = String(text || '');
}

/**
 * Safely creates an element with text content
 * @param {string} tagName - HTML tag name (e.g., 'div', 'span')
 * @param {string} text - Text content
 * @param {string} className - Optional CSS class
 * @returns {HTMLElement}
 */
function createElementSafe(tagName, text = '', className = '') {
  const el = document.createElement(tagName);
  if (className) el.className = className;
  if (text) el.textContent = text;
  return el;
}

/**
 * Sanitizes a number for safe display
 * @param {any} value - Value to sanitize
 * @param {number} decimals - Number of decimal places
 * @returns {string}
 */
function sanitizeNumber(value, decimals = 2) {
  const num = parseFloat(value);
  if (isNaN(num)) return '—';
  return num.toFixed(decimals);
}

/**
 * Sanitizes an array of strings (e.g., crop names) for safe display
 * @param {Array} arr - Array of strings
 * @param {string} separator - Join separator
 * @returns {string}
 */
function sanitizeArray(arr, separator = ', ') {
  if (!Array.isArray(arr)) return '';
  return arr.map(item => escapeHtml(item)).join(separator);
}

/**
 * Validates and sanitizes a date string
 * @param {string} dateStr - Date string
 * @returns {string} - Sanitized date or empty string
 */
function sanitizeDate(dateStr) {
  if (!dateStr) return '';
  // Basic YYYY-MM-DD validation
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
    console.warn('Invalid date format:', dateStr);
    return '';
  }
  return escapeHtml(dateStr);
}

/**
 * Creates a safe HTML string by escaping all interpolated values
 * Usage: safeHtml`<div>Name: ${userName}</div>`
 * @param {Array} strings - Template string parts
 * @param  {...any} values - Interpolated values
 * @returns {string} - Safe HTML string
 */
function safeHtml(strings, ...values) {
  let result = strings[0];
  for (let i = 0; i < values.length; i++) {
    result += escapeHtml(values[i]) + strings[i + 1];
  }
  return result;
}

/**
 * localStorage utilities with error handling
 */

/**
 * Safely gets an item from localStorage
 * @param {string} key - Storage key
 * @param {any} defaultValue - Default value if not found or error
 * @returns {any} - Retrieved value or default
 */
function storageGet(key, defaultValue = null) {
  try {
    if (typeof localStorage === 'undefined') {
      console.warn('localStorage not available');
      return defaultValue;
    }

    const value = localStorage.getItem(key);
    if (value === null) {
      return defaultValue;
    }

    // Try to parse as JSON, fall back to raw value
    try {
      return JSON.parse(value);
    } catch (parseError) {
      // Not JSON, return as string
      return value;
    }
  } catch (error) {
    console.error(`Error reading from localStorage (key: ${key}):`, error);
    return defaultValue;
  }
}

/**
 * Safely sets an item in localStorage
 * @param {string} key - Storage key
 * @param {any} value - Value to store (will be JSON stringified)
 * @returns {boolean} - True if successful, false otherwise
 */
function storageSet(key, value) {
  try {
    if (typeof localStorage === 'undefined') {
      console.warn('localStorage not available');
      return false;
    }

    const stringValue = typeof value === 'string' ? value : JSON.stringify(value);
    localStorage.setItem(key, stringValue);
    return true;
  } catch (error) {
    if (error.name === 'QuotaExceededError') {
      console.error('localStorage quota exceeded. Clearing old data...');
      // Try to clear some space
      try {
        storageClear();
        localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value));
        return true;
      } catch (retryError) {
        console.error('Failed to save even after clearing:', retryError);
        return false;
      }
    } else {
      console.error(`Error writing to localStorage (key: ${key}):`, error);
      return false;
    }
  }
}

/**
 * Safely removes an item from localStorage
 * @param {string} key - Storage key
 * @returns {boolean} - True if successful, false otherwise
 */
function storageRemove(key) {
  try {
    if (typeof localStorage === 'undefined') {
      return false;
    }
    localStorage.removeItem(key);
    return true;
  } catch (error) {
    console.error(`Error removing from localStorage (key: ${key}):`, error);
    return false;
  }
}

/**
 * Safely clears all localStorage
 * @returns {boolean} - True if successful, false otherwise
 */
function storageClear() {
  try {
    if (typeof localStorage === 'undefined') {
      return false;
    }
    localStorage.clear();
    return true;
  } catch (error) {
    console.error('Error clearing localStorage:', error);
    return false;
  }
}

/**
 * Checks if localStorage is available and working
 * @returns {boolean}
 */
function isStorageAvailable() {
  try {
    if (typeof localStorage === 'undefined') {
      return false;
    }
    const testKey = '__storage_test__';
    localStorage.setItem(testKey, 'test');
    localStorage.removeItem(testKey);
    return true;
  } catch (error) {
    return false;
  }
}

/**
 * Loading state utilities
 */

/**
 * Shows loading state on a button
 * @param {HTMLElement} button - Button element
 * @param {string} loadingText - Text to show while loading (default: 'Загрузка...')
 * @returns {Function} - Call this function to restore original state
 */
function setButtonLoading(button, loadingText = 'Загрузка...') {
  if (!button) return () => {};

  const originalText = button.textContent;
  const originalDisabled = button.disabled;

  button.textContent = loadingText;
  button.disabled = true;
  button.classList.add('loading');

  // Return function to restore original state
  return () => {
    button.textContent = originalText;
    button.disabled = originalDisabled;
    button.classList.remove('loading');
  };
}

/**
 * Shows a loading spinner in a container
 * @param {HTMLElement} container - Container element
 * @param {string} message - Optional loading message
 * @returns {Function} - Call this function to remove spinner
 */
function showLoadingSpinner(container, message = '') {
  if (!container) return () => {};

  const spinner = document.createElement('div');
  spinner.className = 'loading-spinner';
  spinner.innerHTML = `
    <div class="spinner"></div>
    ${message ? `<p>${escapeHtml(message)}</p>` : ''}
  `;

  container.appendChild(spinner);

  // Return function to remove spinner
  return () => {
    if (spinner.parentNode) {
      spinner.parentNode.removeChild(spinner);
    }
  };
}

/**
 * Wraps an async function with loading state management
 * @param {Function} asyncFn - Async function to wrap
 * @param {HTMLElement} button - Button to show loading state on
 * @param {string} loadingText - Loading text
 * @returns {Function} - Wrapped function
 */
function withLoadingState(asyncFn, button, loadingText = 'Загрузка...') {
  return async function(...args) {
    const restore = setButtonLoading(button, loadingText);
    try {
      return await asyncFn.apply(this, args);
    } finally {
      restore();
    }
  };
}

/**
 * Shows empty state message
 * @param {HTMLElement} container - Container element
 * @param {string} message - Empty state message
 * @param {string} iconClass - Optional icon class
 */
function showEmptyState(container, message, iconClass = '') {
  if (!container) return;

  const emptyDiv = document.createElement('div');
  emptyDiv.className = 'empty-state';

  if (iconClass) {
    emptyDiv.innerHTML = `
      <div class="${escapeHtml(iconClass)}"></div>
      <p>${escapeHtml(message)}</p>
    `;
  } else {
    emptyDiv.innerHTML = `<p>${escapeHtml(message)}</p>`;
  }

  container.innerHTML = '';
  container.appendChild(emptyDiv);
}

/**
 * CSV export with error handling
 * @param {Array<Object>} data - Array of objects to export
 * @param {string} filename - CSV filename
 * @param {Array<string>} headers - Optional custom headers
 * @returns {boolean} - True if successful
 */
function exportToCSV(data, filename, headers = null) {
  try {
    if (!data || data.length === 0) {
      throw new Error('No data to export');
    }

    // Get headers from first object if not provided
    const csvHeaders = headers || Object.keys(data[0]);

    // Build CSV content
    let csv = csvHeaders.join(',') + '\n';

    for (const row of data) {
      const values = csvHeaders.map(header => {
        const value = row[header];
        // Handle null/undefined
        if (value === null || value === undefined) return '';
        // Escape quotes and wrap in quotes if contains comma/quote/newline
        const stringValue = String(value);
        if (stringValue.includes(',') || stringValue.includes('"') || stringValue.includes('\n')) {
          return '"' + stringValue.replace(/"/g, '""') + '"';
        }
        return stringValue;
      });
      csv += values.join(',') + '\n';
    }

    // Create blob and download
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');

    if (navigator.msSaveBlob) {
      // IE 10+
      navigator.msSaveBlob(blob, filename);
    } else {
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(link.href);
    }

    return true;
  } catch (error) {
    console.error('CSV export error:', error);
    alert('Ошибка экспорта CSV: ' + error.message);
    return false;
  }
}

// ============================================
// Request Cancellation (AbortController)
// ============================================

/**
 * Управляет отменой HTTP-запросов с помощью AbortController
 * Использование:
 *   const requestManager = createRequestManager();
 *
 *   // Отменяет предыдущий запрос, если он еще выполняется
 *   const signal = requestManager.getSignal();
 *   fetch('/api/data', { signal }).then(...);
 *
 *   // При новом запросе предыдущий будет отменен автоматически
 *   const newSignal = requestManager.getSignal();
 *   fetch('/api/other-data', { signal: newSignal }).then(...);
 */
function createRequestManager() {
  let controller = null;

  return {
    /**
     * Получает AbortSignal для текущего запроса.
     * Автоматически отменяет предыдущий запрос.
     * @returns {AbortSignal}
     */
    getSignal() {
      // Отменяем предыдущий запрос, если он существует
      if (controller) {
        controller.abort();
      }

      // Создаем новый контроллер
      controller = new AbortController();
      return controller.signal;
    },

    /**
     * Отменяет текущий запрос
     */
    abort() {
      if (controller) {
        controller.abort();
        controller = null;
      }
    },

    /**
     * Проверяет, выполняется ли запрос
     * @returns {boolean}
     */
    isPending() {
      return controller !== null && !controller.signal.aborted;
    }
  };
}

/**
 * Wrapper для fetch с автоматической отменой при размонтировании
 * @param {string} url - URL для запроса
 * @param {Object} options - Опции для fetch
 * @param {AbortSignal} options.signal - AbortSignal (опционально)
 * @returns {Promise} Promise с результатом fetch
 */
async function fetchWithCancel(url, options = {}) {
  try {
    const response = await fetch(url, options);
    return response;
  } catch (error) {
    if (error.name === 'AbortError') {
      console.log(`Request to ${url} was cancelled`);
      return null; // Возвращаем null для отмененных запросов
    }
    throw error; // Пробрасываем другие ошибки
  }
}

/**
 * Создает debounced функцию с поддержкой отмены запросов
 * @param {Function} fn - Функция для вызова
 * @param {number} delay - Задержка в мс
 * @returns {Function} Debounced функция с методом cancel
 */
function debounceWithCancel(fn, delay = 300) {
  let timeoutId = null;
  let requestManager = createRequestManager();

  function debounced(...args) {
    // Отменяем предыдущий таймер
    if (timeoutId) {
      clearTimeout(timeoutId);
    }

    // Отменяем предыдущий запрос
    requestManager.abort();

    // Создаем новый таймер
    timeoutId = setTimeout(() => {
      const signal = requestManager.getSignal();
      fn.call(this, ...args, signal);
      timeoutId = null;
    }, delay);
  }

  // Добавляем метод для принудительной отмены
  debounced.cancel = function() {
    if (timeoutId) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    requestManager.abort();
  };

  return debounced;
}

/**
 * Проверяет, поддерживается ли AbortController в браузере
 * @returns {boolean}
 */
function isAbortControllerSupported() {
  return typeof AbortController !== 'undefined';
}

// ============================================
// Coordinate Validation
// ============================================

/**
 * Проверяет валидность широты
 * @param {number|string} lat - Широта
 * @returns {boolean} true если валидна
 */
function isValidLatitude(lat) {
  const num = parseFloat(lat);
  return !isNaN(num) && num >= -90 && num <= 90;
}

/**
 * Проверяет валидность долготы
 * @param {number|string} lon - Долгота
 * @returns {boolean} true если валидна
 */
function isValidLongitude(lon) {
  const num = parseFloat(lon);
  return !isNaN(num) && num >= -180 && num <= 180;
}

/**
 * Проверяет валидность координат (lat, lon)
 * @param {number|string} lat - Широта
 * @param {number|string} lon - Долгота
 * @returns {{valid: boolean, error?: string}} Результат проверки
 */
function validateCoordinates(lat, lon) {
  if (!isValidLatitude(lat)) {
    return {
      valid: false,
      error: `Неверная широта: ${lat}. Должна быть от -90 до 90.`
    };
  }

  if (!isValidLongitude(lon)) {
    return {
      valid: false,
      error: `Неверная долгота: ${lon}. Должна быть от -180 до 180.`
    };
  }

  return { valid: true };
}

/**
 * Проверяет валидность bbox [minLon, minLat, maxLon, maxLat]
 * @param {Array<number>} bbox - Массив из 4 координат
 * @returns {{valid: boolean, error?: string}} Результат проверки
 */
function validateBbox(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4) {
    return {
      valid: false,
      error: 'Bbox должен быть массивом из 4 чисел: [minLon, minLat, maxLon, maxLat]'
    };
  }

  const [minLon, minLat, maxLon, maxLat] = bbox;

  if (!isValidLongitude(minLon)) {
    return { valid: false, error: `Неверный minLon: ${minLon}` };
  }

  if (!isValidLatitude(minLat)) {
    return { valid: false, error: `Неверный minLat: ${minLat}` };
  }

  if (!isValidLongitude(maxLon)) {
    return { valid: false, error: `Неверный maxLon: ${maxLon}` };
  }

  if (!isValidLatitude(maxLat)) {
    return { valid: false, error: `Неверный maxLat: ${maxLat}` };
  }

  if (minLon >= maxLon) {
    return {
      valid: false,
      error: `minLon (${minLon}) должен быть меньше maxLon (${maxLon})`
    };
  }

  if (minLat >= maxLat) {
    return {
      valid: false,
      error: `minLat (${minLat}) должен быть меньше maxLat (${maxLat})`
    };
  }

  return { valid: true };
}

/**
 * Нормализует долготу к диапазону [-180, 180]
 * @param {number} lon - Долгота
 * @returns {number} Нормализованная долгота
 */
function normalizeLongitude(lon) {
  let normalized = lon % 360;
  if (normalized > 180) {
    normalized -= 360;
  } else if (normalized < -180) {
    normalized += 360;
  }
  return normalized;
}

/**
 * Ограничивает широту диапазоном [-90, 90]
 * @param {number} lat - Широта
 * @returns {number} Ограниченная широта
 */
function clampLatitude(lat) {
  return Math.max(-90, Math.min(90, lat));
}

// Export for use in other modules (if using modules)
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    escapeHtml,
    setTextSafe,
    createElementSafe,
    sanitizeNumber,
    sanitizeArray,
    sanitizeDate,
    safeHtml,
    storageGet,
    storageSet,
    storageRemove,
    storageClear,
    isStorageAvailable,
    setButtonLoading,
    showLoadingSpinner,
    withLoadingState,
    showEmptyState,
    exportToCSV,
    createRequestManager,
    fetchWithCancel,
    debounceWithCancel,
    isAbortControllerSupported,
    isValidLatitude,
    isValidLongitude,
    validateCoordinates,
    validateBbox,
    normalizeLongitude,
    clampLatitude
  };
}
