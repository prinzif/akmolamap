/**
 * Утилиты для работы с Leaflet картами
 * Предотвращение утечек памяти и правильная очистка слоев
 */

// ============================================
// Layer Management
// ============================================

/**
 * Безопасно удаляет layer из карты и очищает его ресурсы
 * @param {L.Layer} layer - Leaflet layer для удаления
 * @param {L.Map} map - Leaflet map instance (опционально)
 */
function removeLayer(layer, map = null) {
  if (!layer) return;

  try {
    // Удаляем с карты если она указана
    if (map && layer._map) {
      map.removeLayer(layer);
    } else if (layer._map) {
      layer.remove();
    }

    // Очищаем event listeners
    if (layer.off) {
      layer.off();
    }

    // Для FeatureGroup/LayerGroup рекурсивно очищаем все слои
    if (layer.eachLayer) {
      layer.eachLayer(sublayer => {
        removeLayer(sublayer);
      });
      layer.clearLayers();
    }

    // Очищаем popup если есть
    if (layer.getPopup) {
      const popup = layer.getPopup();
      if (popup) {
        popup.remove();
      }
    }

    // Очищаем tooltip если есть
    if (layer.getTooltip) {
      const tooltip = layer.getTooltip();
      if (tooltip) {
        tooltip.remove();
      }
    }
  } catch (error) {
    console.error('Error removing layer:', error);
  }
}

/**
 * Очищает все слои из LayerGroup/FeatureGroup
 * @param {L.LayerGroup} layerGroup - Layer group для очистки
 */
function clearLayerGroup(layerGroup) {
  if (!layerGroup || !layerGroup.eachLayer) return;

  try {
    // Собираем все слои в массив
    const layers = [];
    layerGroup.eachLayer(layer => {
      layers.push(layer);
    });

    // Удаляем каждый слой
    layers.forEach(layer => {
      removeLayer(layer);
    });

    // Очищаем группу
    layerGroup.clearLayers();
  } catch (error) {
    console.error('Error clearing layer group:', error);
  }
}

/**
 * Удаляет все слои определенного типа с карты
 * @param {L.Map} map - Leaflet map instance
 * @param {Function} filterFn - Функция фильтрации слоев
 * @example
 *   // Удалить все маркеры
 *   removeLayersByType(map, layer => layer instanceof L.Marker)
 */
function removeLayersByType(map, filterFn) {
  if (!map) return;

  try {
    const layersToRemove = [];

    map.eachLayer(layer => {
      if (filterFn(layer)) {
        layersToRemove.push(layer);
      }
    });

    layersToRemove.forEach(layer => {
      removeLayer(layer, map);
    });
  } catch (error) {
    console.error('Error removing layers by type:', error);
  }
}

/**
 * Заменяет слой в LayerGroup новым слоем
 * @param {L.LayerGroup} layerGroup - Layer group
 * @param {L.Layer} oldLayer - Старый слой для удаления
 * @param {L.Layer} newLayer - Новый слой для добавления
 */
function replaceLayer(layerGroup, oldLayer, newLayer) {
  if (!layerGroup) return;

  try {
    if (oldLayer) {
      removeLayer(oldLayer);
    }

    if (newLayer && layerGroup.addLayer) {
      layerGroup.addLayer(newLayer);
    }
  } catch (error) {
    console.error('Error replacing layer:', error);
  }
}

// ============================================
// Map Cleanup
// ============================================

/**
 * Полностью очищает карту и освобождает ресурсы
 * @param {L.Map} map - Leaflet map instance для очистки
 */
function destroyMap(map) {
  if (!map) return;

  try {
    // Удаляем все слои
    map.eachLayer(layer => {
      removeLayer(layer, map);
    });

    // Удаляем все controls
    map.eachControl && map.eachControl(control => {
      try {
        map.removeControl(control);
      } catch (e) {
        // Некоторые controls могут не поддерживать удаление
      }
    });

    // Очищаем event listeners
    if (map.off) {
      map.off();
    }

    // Удаляем карту
    if (map.remove) {
      map.remove();
    }
  } catch (error) {
    console.error('Error destroying map:', error);
  }
}

/**
 * Сбрасывает состояние карты (удаляет все пользовательские слои, оставляет base map)
 * @param {L.Map} map - Leaflet map instance
 * @param {Array<L.Layer>} baseLayersToKeep - Базовые слои, которые нужно сохранить
 */
function resetMapState(map, baseLayersToKeep = []) {
  if (!map) return;

  try {
    // Получаем все слои
    const allLayers = [];
    map.eachLayer(layer => {
      allLayers.push(layer);
    });

    // Удаляем все кроме базовых
    allLayers.forEach(layer => {
      if (!baseLayersToKeep.includes(layer)) {
        removeLayer(layer, map);
      }
    });
  } catch (error) {
    console.error('Error resetting map state:', error);
  }
}

// ============================================
// Tile Layer Management
// ============================================

/**
 * Удаляет tile layer и прерывает загрузку тайлов
 * @param {L.TileLayer} tileLayer - Tile layer для удаления
 */
function removeTileLayer(tileLayer) {
  if (!tileLayer) return;

  try {
    // Прерываем загрузку тайлов
    if (tileLayer._tiles) {
      Object.values(tileLayer._tiles).forEach(tile => {
        if (tile.el) {
          // Прерываем загрузку изображения
          tile.el.src = '';
          tile.el.onload = null;
          tile.el.onerror = null;
        }
      });
    }

    // Удаляем layer
    removeLayer(tileLayer);
  } catch (error) {
    console.error('Error removing tile layer:', error);
  }
}

/**
 * Обновляет tile layer (удаляет старый и добавляет новый)
 * @param {L.Map} map - Leaflet map
 * @param {L.TileLayer} oldTileLayer - Старый tile layer
 * @param {L.TileLayer} newTileLayer - Новый tile layer
 * @param {L.LayerGroup} targetGroup - Целевая группа слоев (опционально)
 */
function updateTileLayer(map, oldTileLayer, newTileLayer, targetGroup = null) {
  if (!map) return newTileLayer;

  try {
    // Удаляем старый layer
    if (oldTileLayer) {
      removeTileLayer(oldTileLayer);
    }

    // Добавляем новый layer
    if (newTileLayer) {
      if (targetGroup && targetGroup.addLayer) {
        targetGroup.addLayer(newTileLayer);
      } else {
        newTileLayer.addTo(map);
      }
    }

    return newTileLayer;
  } catch (error) {
    console.error('Error updating tile layer:', error);
    return newTileLayer;
  }
}

// ============================================
// Event Listener Cleanup
// ============================================

/**
 * Создает wrapper для event listener с автоматической очисткой
 * @param {L.Map|L.Layer} target - Объект для добавления listener
 * @returns {Object} Объект с методами on/off/clear
 */
function createEventManager(target) {
  const listeners = [];

  return {
    /**
     * Добавляет event listener и запоминает его для очистки
     * @param {string} event - Имя события
     * @param {Function} handler - Обработчик события
     */
    on(event, handler) {
      if (target && target.on) {
        target.on(event, handler);
        listeners.push({ event, handler });
      }
    },

    /**
     * Удаляет конкретный event listener
     * @param {string} event - Имя события
     * @param {Function} handler - Обработчик события
     */
    off(event, handler) {
      if (target && target.off) {
        target.off(event, handler);

        // Удаляем из списка
        const index = listeners.findIndex(
          l => l.event === event && l.handler === handler
        );
        if (index !== -1) {
          listeners.splice(index, 1);
        }
      }
    },

    /**
     * Удаляет все зарегистрированные event listeners
     */
    clear() {
      listeners.forEach(({ event, handler }) => {
        if (target && target.off) {
          target.off(event, handler);
        }
      });
      listeners.length = 0;
    },

    /**
     * Получает количество активных listeners
     */
    count() {
      return listeners.length;
    }
  };
}

// ============================================
// Memory Leak Detection (Development)
// ============================================

/**
 * Подсчитывает количество слоев на карте
 * @param {L.Map} map - Leaflet map
 * @returns {number} Количество слоев
 */
function countLayers(map) {
  if (!map) return 0;

  let count = 0;
  map.eachLayer(() => count++);
  return count;
}

/**
 * Выводит информацию о слоях на карте (для отладки)
 * @param {L.Map} map - Leaflet map
 */
function debugLayers(map) {
  if (!map) return;

  console.group('Leaflet Layers Debug Info');
  console.log('Total layers:', countLayers(map));

  const layerTypes = {};
  map.eachLayer(layer => {
    const type = layer.constructor.name;
    layerTypes[type] = (layerTypes[type] || 0) + 1;
  });

  console.table(layerTypes);
  console.groupEnd();
}

// ============================================
// Export
// ============================================

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    removeLayer,
    clearLayerGroup,
    removeLayersByType,
    replaceLayer,
    destroyMap,
    resetMapState,
    removeTileLayer,
    updateTileLayer,
    createEventManager,
    countLayers,
    debugLayers
  };
}

if (typeof window !== 'undefined') {
  window.LeafletUtils = {
    removeLayer,
    clearLayerGroup,
    removeLayersByType,
    replaceLayer,
    destroyMap,
    resetMapState,
    removeTileLayer,
    updateTileLayer,
    createEventManager,
    countLayers,
    debugLayers
  };
}
