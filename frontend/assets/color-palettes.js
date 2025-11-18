/**
 * Централизованная конфигурация цветовых палитр
 * Используется для единообразного отображения данных NDVI и BIOPAR
 */

// ============================================
// NDVI Color Schemes
// ============================================

/**
 * Цвета для статусов NDVI
 */
const NDVI_STATUS_COLORS = {
  optimal: '#28a745',        // Зеленый - оптимальная растительность
  high: '#007cba',           // Синий - высокая растительность
  low: '#ffc107',            // Желтый - низкая растительность
  critical_low: '#dc3545',   // Красный - критически низкая
  water: '#0066cc',          // Голубой - вода
  bare_soil: '#8b4513',      // Коричневый - голая почва
  default: '#6c757d'         // Серый - нет данных/неопределен
};

/**
 * Цвета для направления тренда
 */
const TREND_COLORS = {
  increasing: '#28a745',     // Зеленый - растущий тренд
  decreasing: '#dc3545',     // Красный - падающий тренд
  stable: '#6c757d',         // Серый - стабильный
  unknown: '#6c757d'         // Серый - неизвестно
};

/**
 * TiTiler colormap для NDVI (-0.2 до 1.0)
 * Используется для рендеринга GeoTIFF слоев
 */
const NDVI_COLORMAP = {
  name: 'rdylgn',            // Red-Yellow-Green (стандартная для NDVI)
  rescale: [-0.2, 1.0],      // Диапазон значений NDVI
  return_mask: true          // Возвращать маску для прозрачности
};

// ============================================
// BIOPAR Color Schemes
// ============================================

/**
 * Цвета для статусов BIOPAR (FAPAR, LAI, FCOVER, CCC, CWC)
 */
const BIOPAR_STATUS_COLORS = {
  very_low: {
    background: 'linear-gradient(to right, #8b0000, #d2691e)',
    color: '#fff',
    label: 'Очень низкий'
  },
  low: {
    background: '#d2691e',
    color: '#fff',
    label: 'Низкий'
  },
  medium: {
    background: '#daa520',
    color: '#333',
    label: 'Средний'
  },
  optimal: {
    background: '#90ee90',
    color: '#333',
    label: 'Оптимальный'
  },
  high: {
    background: '#228b22',
    color: '#fff',
    label: 'Высокий'
  }
};

/**
 * TiTiler colormap конфигурация для различных типов BIOPAR
 */
const BIOPAR_COLORMAPS = {
  FAPAR: {
    name: 'rdylgn',
    rescale: [0, 1],
    return_mask: true
  },
  LAI: {
    name: 'rdylgn',
    rescale: [0, 8],
    return_mask: true
  },
  FCOVER: {
    name: 'rdylgn',
    rescale: [0, 1],
    return_mask: true
  },
  CCC: {
    name: 'rdylgn',
    rescale: [0, 600],
    return_mask: true
  },
  CWC: {
    name: 'blues',
    rescale: [0, 400],
    return_mask: true
  }
};

// ============================================
// UI Color Schemes
// ============================================

/**
 * Цвета для элементов интерфейса
 */
const UI_COLORS = {
  // Buttons
  button: {
    primary: '#007bff',
    success: '#28a745',
    danger: '#dc3545',
    warning: '#ffc107',
    info: '#17a2b8',
    secondary: '#6c757d'
  },

  // Alerts/Notifications
  alert: {
    success: { bg: '#d4edda', border: '#c3e6cb', text: '#155724' },
    error: { bg: '#f8d7da', border: '#f5c6cb', text: '#721c24' },
    warning: { bg: '#fff3cd', border: '#ffc107', text: '#856404' },
    info: { bg: '#d1ecf1', border: '#17a2b8', text: '#0c5460' }
  },

  // Map elements
  map: {
    selection: {
      color: '#007cba',
      fillColor: '#007cba',
      fillOpacity: 0.1,
      weight: 2
    },
    polygon: {
      color: '#7c3aed',       // Фиолетовый для AOI
      weight: 3,
      fillOpacity: 0.10,
      dashArray: '4,3'
    },
    district: {
      color: '#1d4ed8',       // Синий для районов
      weight: 1.5,
      fillOpacity: 0.05
    }
  },

  // Background colors
  background: {
    selectionInfo: '#e3f2fd',
    legend: '#f8f9fa',
    sidebar: '#ffffff'
  }
};

// ============================================
// Helper Functions
// ============================================

/**
 * Получает цвет для статуса NDVI
 * @param {string} status - Статус NDVI
 * @returns {string} Hex color code
 */
function getNDVIStatusColor(status) {
  return NDVI_STATUS_COLORS[status] || NDVI_STATUS_COLORS.default;
}

/**
 * Получает цвет для направления тренда
 * @param {string} direction - Направление (increasing, decreasing, stable)
 * @returns {string} Hex color code
 */
function getTrendColor(direction) {
  return TREND_COLORS[direction] || TREND_COLORS.unknown;
}

/**
 * Получает конфигурацию colormap для BIOPAR типа
 * @param {string} bioparType - Тип BIOPAR (FAPAR, LAI, etc.)
 * @returns {Object} Colormap configuration
 */
function getBIOPARColormap(bioparType) {
  return BIOPAR_COLORMAPS[bioparType] || BIOPAR_COLORMAPS.FAPAR;
}

/**
 * Генерирует TiTiler URL с colormap параметрами
 * @param {string} baseUrl - Базовый URL TiTiler
 * @param {string} tiffUrl - URL GeoTIFF файла
 * @param {Object} colormap - Конфигурация colormap
 * @returns {string} Полный URL с параметрами
 */
function buildTiTilerUrl(baseUrl, tiffUrl, colormap) {
  const params = new URLSearchParams({
    url: tiffUrl,
    bidx: 1,
    rescale: colormap.rescale.join(','),
    colormap_name: colormap.name,
    return_mask: colormap.return_mask
  });
  return `${baseUrl}?${params.toString()}`;
}

/**
 * Применяет стиль к Leaflet layer
 * @param {Object} layer - Leaflet layer
 * @param {string} type - Тип стиля (selection, polygon, district)
 */
function applyMapStyle(layer, type) {
  const style = UI_COLORS.map[type];
  if (style && layer.setStyle) {
    layer.setStyle(style);
  }
}

// ============================================
// Export Configuration
// ============================================

// For ES6 modules
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    // Color schemes
    NDVI_STATUS_COLORS,
    TREND_COLORS,
    NDVI_COLORMAP,
    BIOPAR_STATUS_COLORS,
    BIOPAR_COLORMAPS,
    UI_COLORS,

    // Helper functions
    getNDVIStatusColor,
    getTrendColor,
    getBIOPARColormap,
    buildTiTilerUrl,
    applyMapStyle
  };
}

// For browser global scope
if (typeof window !== 'undefined') {
  window.ColorPalettes = {
    NDVI_STATUS_COLORS,
    TREND_COLORS,
    NDVI_COLORMAP,
    BIOPAR_STATUS_COLORS,
    BIOPAR_COLORMAPS,
    UI_COLORS,
    getNDVIStatusColor,
    getTrendColor,
    getBIOPARColormap,
    buildTiTilerUrl,
    applyMapStyle
  };
}
