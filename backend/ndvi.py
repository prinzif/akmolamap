"""
/backend/ndvi.py - NDVI мониторинг через Sentinel Hub API.

Улучшенная версия с:
- Statistical API для эффективного получения статистики
- ORBIT mosaicking для временных рядов
- Calculations API для гистограмм и перцентилей
- Оптимизированная работа с rasterio
- Кэширование статистики
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import hashlib
import json
import time

import numpy as np

from backend.constants import (
    STATUS_SUCCESS,
    STATUS_ERROR,
    STATUS_NO_DATA,
    NDVI_STATUS_OPTIMAL,
    NDVI_STATUS_HIGH,
    NDVI_STATUS_LOW,
    NDVI_STATUS_CRITICAL_LOW,
    NDVI_STATUS_WATER,
    NDVI_STATUS_BARE_SOIL,
    NDVI_STATUS_DEFAULT,
    NDVI_THRESHOLD_OPTIMAL,
    NDVI_THRESHOLD_HIGH,
    NDVI_THRESHOLD_LOW,
    NDVI_THRESHOLD_CRITICAL
)
from scipy import stats as scipy_stats
import requests

try:
    import rasterio
    from rasterio.windows import Window
    from rasterio.warp import transform_geom
    from rasterio.crs import CRS
except ImportError:
    rasterio = None

from backend.sentinel import search_products
from backend.ndvi_sentinelhub import (
    fetch_ndvi_geotiff,
    get_cdse_token,
    SentinelHubError,
    NoDataAvailableError,
    MosaickingOrder
)

logger = logging.getLogger(__name__)

# Импорт настроек
from backend.settings import settings

# Директории кэша
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "ndvi"
STATS_CACHE_DIR = CACHE_DIR / "stats"
STATS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Sentinel Hub API endpoints (из настроек)
SH_STATISTICS_URL = settings.SH_STATISTICS_URL
SH_PROCESS_URL = settings.SH_PROCESS_URL


# --------------------------- Утилиты --------------------------------- #

def _require_rasterio() -> None:
    """Проверка наличия rasterio."""
    if rasterio is None:
        raise RuntimeError(
            "rasterio не установлен. Установите пакет: pip install rasterio"
        )


def _open_ndvi_array(
    tif_path: Path,
    window: Optional[Window] = None
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Читает GeoTIFF (1 канал, FLOAT32), возвращает массив и метаданные.
    
    Args:
        tif_path: Путь к GeoTIFF файлу
        window: Опциональное окно для частичного чтения
        
    Returns:
        Tuple[np.ndarray, Dict]: Массив данных и метаданные
    """
    _require_rasterio()
    
    with rasterio.open(tif_path) as src:
        # Читаем с masked=True для корректной обработки nodata
        arr = src.read(1, window=window, masked=True)
        meta = src.meta.copy()

    # Конвертируем в numpy array с NaN вместо маски
    data = np.array(arr.filled(np.nan), dtype=np.float32)

    # Явно удаляем временный masked array для освобождения памяти
    del arr

    return data, meta


def _sample_point_ndvi(
    tif_path: Path,
    lon: float,
    lat: float
) -> Optional[float]:
    """
    Возвращает значение NDVI в точке (lon, lat) из GeoTIFF.
    
    Args:
        tif_path: Путь к GeoTIFF файлу
        lon: Долгота (EPSG:4326)
        lat: Широта (EPSG:4326)
        
    Returns:
        Optional[float]: Значение NDVI или None если вне растра/nodata
    """
    _require_rasterio()
    
    try:
        with rasterio.open(tif_path) as src:
            # Проверяем, что точка в bounds
            if not (src.bounds.left <= lon <= src.bounds.right and
                    src.bounds.bottom <= lat <= src.bounds.top):
                return None
            
            # Используем sample для интерполированного значения
            values = list(src.sample([(lon, lat)], indexes=1))
            
            if not values:
                return None
            
            val = float(values[0][0])
            
            # Проверка на валидность
            if np.isnan(val) or np.isinf(val):
                return None
            
            # Клиппинг к валидному диапазону NDVI
            if val < -1.0 or val > 1.0:
                logger.warning(f"NDVI value {val} out of range [-1, 1], clipping")
                val = np.clip(val, -1.0, 1.0)
            
            return val
            
    except Exception as e:
        logger.warning(f"Failed to sample point ({lon}, {lat}): {e}")
        return None


def _as_float_or_none(x: Any) -> Optional[float]:
    """Пытается привести к float, возвращает None для None/NaN/нечисел."""
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _stats_cache_key(
    bbox: List[float],
    start_date: str,
    end_date: str,
    aggregation_days: int
) -> str:
    """Генерирует ключ кэша для статистики (SHA256 для безопасности)."""
    payload = {
        "bbox": [round(b, 6) for b in bbox],
        "start": start_date,
        "end": end_date,
        "agg_days": aggregation_days
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]  # First 16 chars for shorter filenames
    return f"stats_{digest}.json"




from math import cos, radians, ceil

# Используем константы из настроек
S2L2A_MIN_MPP = settings.S2L2A_MIN_MPP    # разумный минимум для статистики
S2L2A_MAX_MPP = settings.S2L2A_MAX_MPP    # жёсткий лимит Statistical API
MIN_PIXELS = settings.MIN_PIXELS          # чтобы не получить 1x1 px
MAX_PIXELS = settings.MAX_PIXELS          # предохранитель от гигантских массивов

def _approx_bbox_size_meters(bbox: List[float]) -> Tuple[float, float]:
    """Грубая оценка размеров bbox в метрах по широте середины окна."""
    minx, miny, maxx, maxy = bbox
    lat_mid = (miny + maxy) / 2.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * cos(radians(lat_mid))
    width_m  = max(1.0, (maxx - minx) * m_per_deg_lon)
    height_m = max(1.0, (maxy - miny) * m_per_deg_lat)
    return width_m, height_m

def _choose_resolution_and_size_for_s2(bbox: List[float], target_mpp: int = 60) -> Tuple[int, int]:
    """
    Выбирает width/height так, чтобы фактический meters-per-pixel гарантированно
    укладывался в лимит S2L2A_MAX_MPP. target_mpp — желаемое разрешение.
    """
    w_m, h_m = _approx_bbox_size_meters(bbox)
    mpp = max(S2L2A_MIN_MPP, min(int(target_mpp), S2L2A_MAX_MPP))

    w_px = max(MIN_PIXELS, min(MAX_PIXELS, ceil(w_m / mpp)))
    h_px = max(MIN_PIXELS, min(MAX_PIXELS, ceil(h_m / mpp)))

    # Контрольная проверка — при необходимости поднимаем число пикселей
    eff_mpp = max(w_m / w_px, h_m / h_px)
    if eff_mpp > S2L2A_MAX_MPP:
        w_px = max(w_px, min(MAX_PIXELS, ceil(w_m / S2L2A_MAX_MPP)))
        h_px = max(h_px, min(MAX_PIXELS, ceil(h_m / S2L2A_MAX_MPP)))

    logger.debug(f"S2 size select: bbox≈({w_m:.0f}x{h_m:.0f} m), target {mpp} m/px → {w_px}x{h_px} px (eff≈{eff_mpp:.1f} m/px)")
    return int(w_px), int(h_px)





# --------------------- Доменные хелперы/зоны ------------------------- #

def get_agricultural_zones(bbox: List[float]) -> List[Dict[str, Any]]:
    """
    Возвращает список сельскохозяйственных зон в bbox.
    
    Args:
        bbox: [minlon, minlat, maxlon, maxlat]
        
    Returns:
        List[Dict]: Список зон с метаданными
    """
    zones = [
        {
            "name": "Северная зерновая зона",
            "description": "Основная пшеничная зона региона",
            "center": [52.28, 70.4],
            "area_ha": 1200000,
            "typical_crops": ["Пшеница", "Ячмень", "Овёс"]
        },
        {
            "name": "Центральная смешанная зона",
            "description": "Разнообразное земледелие",
            "center": [51.16, 71.45],
            "area_ha": 950000,
            "typical_crops": ["Пшеница", "Подсолнечник", "Лён"]
        },
        {
            "name": "Южная орошаемая зона",
            "description": "Интенсивное орошаемое земледелие",
            "center": [50.4, 72.3],
            "area_ha": 780000,
            "typical_crops": ["Кукуруза", "Овощи", "Бахчевые"]
        }
    ]

    minlon, minlat, maxlon, maxlat = bbox
    filtered = []
    
    for zone in zones:
        lat, lon = zone["center"]
        if minlat <= lat <= maxlat and minlon <= lon <= maxlon:
            filtered.append(zone)

    return filtered if filtered else zones


def classify_ndvi_status(mean_ndvi: float) -> Dict[str, str]:
    """
    Классифицирует состояние растительности по среднему NDVI.

    Args:
        mean_ndvi: Среднее значение NDVI

    Returns:
        Dict: Статус, уровень и описание
    """
    if mean_ndvi < NDVI_THRESHOLD_CRITICAL:
        status = NDVI_STATUS_WATER
        level = "Вода"
        description = "Водная поверхность"
    elif mean_ndvi < 0.2:
        status = NDVI_STATUS_BARE_SOIL
        level = "Оголённая почва"
        description = "Отсутствие или минимальная растительность"
    elif mean_ndvi < NDVI_THRESHOLD_HIGH:
        status = NDVI_STATUS_CRITICAL_LOW
        level = "Критически низкий"
        description = "Разреженная растительность, возможен стресс"
    elif mean_ndvi < 0.45:
        status = NDVI_STATUS_LOW
        level = "Низкий"
        description = "Умеренная растительность, ниже нормы"
    elif mean_ndvi < 0.65:
        status = NDVI_STATUS_OPTIMAL
        level = "Оптимальный"
        description = "Здоровая растительность, нормальное состояние"
    else:
        status = NDVI_STATUS_HIGH
        level = "Высокий"
        description = "Очень густая растительность"

    return {
        "status": status,
        "level": level,
        "description": description
    }


def _get_ndvi_statistics_evalscript() -> str:
    """
    Evalscript для Statistical API с мозаикой ORBIT для временных рядов.
    
    Returns:
        str: Evalscript V3 код
    """
    return """//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B04", "B08", "SCL", "dataMask"]
    }],
    output: [
      {
        id: "ndvi",
        bands: 1,
        sampleType: "FLOAT32"
      },
      {
        id: "dataMask",
        bands: 1
      }
    ],
    mosaicking: "ORBIT"
  };
}

function evaluatePixel(samples) {
  // Находим первую валидную сцену (без облаков)
  for (let i = 0; i < samples.length; i++) {
    let sample = samples[i];
    
    // Проверка dataMask
    if (sample.dataMask === 0) {
      continue;
    }
    
    // Маска облаков по SCL
    // 3=cloud shadows, 8=cloud medium probability, 9=cloud high probability, 10=thin cirrus, 11=snow
    if (sample.SCL === 3 || sample.SCL === 8 || sample.SCL === 9 || 
        sample.SCL === 10 || sample.SCL === 11) {
      continue;
    }
    
    // Вычисляем NDVI
    let denom = sample.B08 + sample.B04;
    if (denom === 0) {
      continue;
    }
    
    let ndvi = (sample.B08 - sample.B04) / denom;
    ndvi = Math.max(-1, Math.min(1, ndvi));
    
    return {
      ndvi: [ndvi],
      dataMask: [1]
    };
  }
  
  // Все сцены замаскированы
  return {
    ndvi: [NaN],
    dataMask: [0]
  };
}
"""


# -------------------------- Статистика NDVI -------------------------- #

def get_ndvi_statistics(
    bbox: List[float],
    start_date: str,
    end_date: str,
    aggregation_days: int = 5,
    use_cache: bool = True
) -> Dict[str, Any]:
    """
    Получает статистику NDVI за период через Statistical API.
    
    Args:
        bbox: [minlon, minlat, maxlon, maxlat] в EPSG:4326
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        aggregation_days: Период агрегации в днях
        use_cache: Использовать кэш
        
    Returns:
        Dict: Статистика NDVI с временным рядом
        
    Notes:
        Использует Statistical API для эффективного получения статистики
        за весь период одним запросом вместо множества Process API запросов.
    """
    try:
        logger.info(
            f"NDVI statistics: bbox={bbox}, period={start_date}..{end_date}, "
            f"aggregation={aggregation_days}d"
        )
        
        # Проверка кэша
        if use_cache:
            cache_key = _stats_cache_key(bbox, start_date, end_date, aggregation_days)
            cache_path = STATS_CACHE_DIR / cache_key
            
            if cache_path.exists():
                try:
                    with open(cache_path, 'r') as f:
                        cached = json.load(f)
                    logger.info(f"Statistics cache hit: {cache_key}")
                    return cached
                except Exception as e:
                    logger.warning(f"Failed to load cache: {e}")
        
        # Получаем токен
        token = get_cdse_token()
        
        # Evalscript с ORBIT mosaicking
        evalscript = _get_ndvi_statistics_evalscript()

        # Подбираем безопасный размер тайла по bbox, чтобы не превысить 1500 m/px
        width_px, height_px = _choose_resolution_and_size_for_s2(bbox, target_mpp=60)

        
        # Формируем запрос к Statistical API
        payload = {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    }
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "maxCloudCoverage": 50  # Более мягкий фильтр, т.к. маскируем в evalscript
                    },
                    "processing": {
                        "harmonizeValues": True
                    }
                }]
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start_date}T00:00:00Z",
                    "to": f"{end_date}T23:59:59Z"
                },
                "aggregationInterval": {
                    "of": f"P{aggregation_days}D"
                },
                "evalscript": evalscript,
                # вместо resx/resy используем явный размер растера
                "width": width_px,
                "height": height_px
            },

            "calculations": {
                "default": {
                    "statistics": {
                        "default": {
                            "percentiles": {
                                "k": [10, 25, 50, 75, 90]
                            }
                        }
                    }
                }
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # Отправляем запрос
        logger.info("Requesting statistics from Statistical API...")
        resp = requests.post(
            SH_STATISTICS_URL,
            headers=headers,
            json=payload,
            timeout=180
        )
        
        if resp.status_code == 400:
            error_text = resp.text
            if "no data" in error_text.lower():
                raise NoDataAvailableError(
                    f"No data available for {start_date} to {end_date}"
                )
            raise SentinelHubError(f"Invalid request: {error_text}")
        
        if resp.status_code != 200:
            logger.error(f"Statistical API error ({resp.status_code}): {resp.text}")
            resp.raise_for_status()
        
        result = resp.json()
        
        # Парсим ответ
        if result.get("status") != "OK":
            raise SentinelHubError(f"API returned non-OK status: {result}")
        
        data = result.get("data", [])
        
        if not data:
            raise NoDataAvailableError(
                f"No valid observations for {start_date} to {end_date}"
            )
        
        # Формируем timeline
        timeline = []
        all_means = []
        
        for item in data:
            interval = item.get("interval", {})
            outputs = item.get("outputs", {})
            ndvi_output = outputs.get("ndvi", {})
            bands = ndvi_output.get("bands", {})
            band_stats = bands.get("B0", {}).get("stats", {})
            
            if not band_stats:
                continue
            
            mean_val = _as_float_or_none(band_stats.get("mean"))
            if mean_val is None:
                continue

            pcts = band_stats.get("percentiles", {}) or {}

            def _r(x):
                v = _as_float_or_none(x)
                return round(v, 3) if v is not None else None

            timeline.append({
                "date": (item.get("interval", {}).get("from", "")[:10]) or interval.get("from", "")[:10],
                "mean_ndvi": round(mean_val, 3),
                "min_ndvi": _r(band_stats.get("min")),
                "max_ndvi": _r(band_stats.get("max")),
                "std_ndvi": _r(band_stats.get("stDev")),
                "percentiles": {
                    "p10": _r(pcts.get("10.0")),
                    "p25": _r(pcts.get("25.0")),
                    "p50": _r(pcts.get("50.0")),
                    "p75": _r(pcts.get("75.0")),
                    "p90": _r(pcts.get("90.0")),
                }
            })
            all_means.append(float(mean_val))

        
        if not all_means:
            raise NoDataAvailableError(
                f"All observations masked (clouds/nodata) for {start_date} to {end_date}"
            )
        
        # Агрегированная статистика
        arr = np.asarray(all_means, dtype=np.float64)
        mean_ndvi   = float(np.nanmean(arr))
        median_ndvi = float(np.nanmedian(arr))
        std_ndvi    = float(np.nanstd(arr))
        min_ndvi    = float(np.nanmin(arr))
        max_ndvi    = float(np.nanmax(arr))

        
        # Тренд
        if len(all_means) >= 3:
            x = np.arange(len(all_means))
            slope, _, r_value, p_value, _ = scipy_stats.linregress(x, all_means)
            
            if abs(slope) < 0.001:
                direction = "stable"
            else:
                direction = "increasing" if slope > 0 else "decreasing"
            
            trend = {
                "direction": direction,
                "slope": round(float(slope), 5),
                "r_squared": round(float(r_value ** 2), 3),
                "p_value": round(float(p_value), 4),
                "description": f"NDVI {direction} (R²={round(r_value**2, 3)})"
            }
        else:
            trend = {
                "direction": "insufficient_data",
                "slope": 0.0,
                "r_squared": 0.0,
                "p_value": 1.0,
                "description": "Insufficient data for trend analysis"
            }
        
        status = classify_ndvi_status(mean_ndvi)
        
        response = {
            "status": STATUS_SUCCESS,
            "statistics": {
                "mean_ndvi": round(mean_ndvi, 3),
                "median_ndvi": round(median_ndvi, 3),
                "std_ndvi": round(std_ndvi, 3),
                "min_ndvi": round(min_ndvi, 3),
                "max_ndvi": round(max_ndvi, 3),
                "total_observations": len(all_means),
                "trend": trend,
                "status": status
            },
            "timeline": timeline,
            "products_available": len(data)
        }
        
        # Сохраняем в кэш
        if use_cache:
            try:
                with open(cache_path, 'w') as f:
                    json.dump(response, f, indent=2)
                logger.info(f"Statistics cached: {cache_key}")
            except Exception as e:
                logger.warning(f"Failed to cache statistics: {e}")
        
        return response
        
    except NoDataAvailableError:
        raise
    except Exception as e:
        logger.error(f"NDVI statistics error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "statistics": {},
            "timeline": [],
            "products_available": 0
        }


# -------------------- Гистограмма (классы NDVI) ---------------------- #

def get_ndvi_histogram(
    bbox: List[float],
    start_date: str,
    end_date: str,
    bins: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Возвращает распределение NDVI по классам через Statistical API.
    
    Args:
        bbox: [minlon, minlat, maxlon, maxlat]
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        bins: Границы бинов (по умолчанию: [-1, 0, 0.2, 0.3, 0.6, 1])
        
    Returns:
        Dict: Гистограмма с процентами по классам
        
    Notes:
        Использует Statistical API с histograms calculation для
        эффективного вычисления на стороне сервера.
    """
    try:
        if bins is None:
            bins = [-1.0, 0.0, 0.2, 0.3, 0.6, 1.0]
        
        logger.info(
            f"NDVI histogram: bbox={bbox}, period={start_date}..{end_date}"
        )
        
        token = get_cdse_token()
        evalscript = _get_ndvi_statistics_evalscript()

        # Для гистограммы берём то же безопасное разрешение
        width_px, height_px = _choose_resolution_and_size_for_s2(bbox, target_mpp=60)

        
        # Формируем запрос с histogram calculation
        payload = {
            "input": {
                "bounds": {
                    "bbox": bbox,
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    }
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "maxCloudCoverage": 50
                    },
                    "processing": {
                        "harmonizeValues": True
                    }
                }]
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start_date}T00:00:00Z",
                    "to": f"{end_date}T23:59:59Z"
                },
                "aggregationInterval": {
                    "of": f"P{(datetime.strptime(end_date, '%Y-%m-%d') - datetime.strptime(start_date, '%Y-%m-%d')).days}D"
                },
                "evalscript": evalscript,
                "width": width_px,
                "height": height_px
            },

            "calculations": {
                "ndvi": {
                    "histograms": {
                        "default": {
                            "bins": bins
                        }
                    }
                }
            }
        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        resp = requests.post(
            SH_STATISTICS_URL,
            headers=headers,
            json=payload,
            timeout=180
        )
        
        if resp.status_code != 200:
            logger.error(f"Histogram API error ({resp.status_code}): {resp.text}")
            if resp.status_code == 400 and "no data" in resp.text.lower():
                raise NoDataAvailableError(f"No data for {start_date} to {end_date}")
            resp.raise_for_status()
        
        result = resp.json()
        
        if result.get("status") != "OK":
            raise SentinelHubError(f"API returned non-OK status: {result}")
        
        data = result.get("data", [])
        
        if not data:
            raise NoDataAvailableError("No valid data for histogram")
        
        # Берём первый (единственный) интервал
        outputs = data[0].get("outputs", {})
        ndvi_output = outputs.get("ndvi", {})
        bands = ndvi_output.get("bands", {})
        histogram = bands.get("B0", {}).get("histogram", {})
        
        hist_bins = histogram.get("bins", [])
        
        if not hist_bins:
            raise SentinelHubError("Empty histogram returned")
        
        # Форматируем результат
        total = sum(b.get("count", 0) for b in hist_bins)
        
        formatted_bins = []
        for i, bin_data in enumerate(hist_bins):
            count = bin_data.get("count", 0)
            low = float(bin_data.get("lowEdge", bins[i]))
            high = float(bin_data.get("highEdge", bins[i + 1]))
            pct = (count / total * 100.0) if total > 0 else 0.0
            
            # Читаемые подписи
            if i == 0 and low <= -1:
                label = "< 0"
            elif i == len(hist_bins) - 1 and high >= 1:
                label = f"{low:.1f}+"
            else:
                label = f"{low:.1f}–{high:.1f}"
            
            formatted_bins.append({
                "min": low,
                "max": high,
                "count": int(count),
                "pct": round(pct, 2),
                "label": label
            })
        
        return {
            "status": "success",
            "bins": formatted_bins,
            "total": total,
            "overflow": histogram.get("overflowCount", 0),
            "underflow": histogram.get("underflowCount", 0)
        }
        
    except NoDataAvailableError:
        raise
    except Exception as e:
        logger.error(f"NDVI histogram error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "bins": []
        }


# -------------------- Тайм-серия по точке ----------------------------- #

def get_point_timeseries(
    lon: float,
    lat: float,
    bbox: List[float],
    start_date: str,
    end_date: str,
    max_dates: int = 20
) -> Dict[str, Any]:
    """
    Получает тайм-серию NDVI в точке (lon, lat).
    
    Args:
        lon: Долгота (EPSG:4326)
        lat: Широта (EPSG:4326)
        bbox: [minlon, minlat, maxlon, maxlat] для контекста
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        max_dates: Максимальное количество дат
        
    Returns:
        Dict: Временной ряд NDVI в точке
        
    Notes:
        Использует Statistical API для получения временного ряда,
        затем берёт одно изображение на дату и сэмплирует точку.
        Для большей эффективности можно использовать маленький bbox вокруг точки.
    """
    try:
        # Проверка: точка внутри bbox
        minlon, minlat, maxlon, maxlat = bbox
        if not (minlon <= lon <= maxlon and minlat <= lat <= maxlat):
            return {
                "status": "error",
                "message": "Point outside bbox",
                "series": []
            }
        
        logger.info(
            f"Point timeseries: ({lon}, {lat}), period={start_date}..{end_date}"
        )
        
        # Создаём маленький bbox вокруг точки для оптимизации
        # ~1km на экваторе ≈ 0.01 градуса
        buffer = 0.01
        point_bbox = [
            lon - buffer,
            lat - buffer,
            lon + buffer,
            lat + buffer
        ]

        # Для маленького окна вокруг точки можно позволить 10 м/px
        width_px, height_px = _choose_resolution_and_size_for_s2(point_bbox, target_mpp=10)

        
        # Получаем список дат со Statistical API
        token = get_cdse_token()
        evalscript = _get_ndvi_statistics_evalscript()
        
        # Определяем aggregation interval
        date_range = (
            datetime.strptime(end_date, "%Y-%m-%d") -
            datetime.strptime(start_date, "%Y-%m-%d")
        ).days
        
        # Подбираем интервал для получения примерно max_dates точек
        if date_range <= max_dates:
            agg_days = 1
        else:
            agg_days = max(1, date_range // max_dates)
        
        payload = {
            "input": {
                "bounds": {
                    "bbox": point_bbox,
                    "properties": {
                        "crs": "http://www.opengis.net/def/crs/EPSG/0/4326"
                    }
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "maxCloudCoverage": 50
                    },
                    "processing": {
                        "harmonizeValues": True
                    }
                }]
            },
            "aggregation": {
                "timeRange": {
                    "from": f"{start_date}T00:00:00Z",
                    "to": f"{end_date}T23:59:59Z"
                },
                "aggregationInterval": {
                    "of": f"P{agg_days}D"
                },
                "evalscript": evalscript,
                "width": width_px,
                "height": height_px
            }

        }
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        resp = requests.post(
            SH_STATISTICS_URL,
            headers=headers,
            json=payload,
            timeout=120
        )
        
        if resp.status_code != 200:
            logger.error(f"Point timeseries API error: {resp.text}")
            if "no data" in resp.text.lower():
                return {
                    "status": "success",
                    "series": [],
                    "message": "No data available for this point"
                }
            resp.raise_for_status()
        
        result = resp.json()
        data = result.get("data", [])
        
        # Формируем серию
        series = []
        for item in data:
            interval = item.get("interval", {})
            date_str = interval.get("from", "")[:10]
            
            outputs = item.get("outputs", {})
            ndvi_output = outputs.get("ndvi", {})
            bands = ndvi_output.get("bands", {})
            stats = bands.get("B0", {}).get("stats", {})

            mean_val = _as_float_or_none(stats.get("mean"))
            if mean_val is not None:
                series.append({
                    "date": date_str,
                    "ndvi": round(mean_val, 3)
                })
        
        return {
            "status": "success",
            "series": series,
            "location": {"lon": lon, "lat": lat}
        }
        
    except Exception as e:
        logger.error(f"Point timeseries error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "series": []
        }


# --------------------------- Отчёт NDVI ------------------------------ #

def generate_recommendations(
    mean_ndvi: float,
    statistics: Dict[str, Any],
    timeline: List[Dict[str, Any]]
) -> List[str]:
    """
    Генерирует рекомендации на основе NDVI статистики.
    
    Args:
        mean_ndvi: Среднее значение NDVI
        statistics: Словарь со статистикой
        timeline: Временной ряд
        
    Returns:
        List[str]: Список рекомендаций
    """
    recommendations = []
    
    trend = statistics.get("trend", {})
    trend_direction = trend.get("direction", "stable")
    r_squared = trend.get("r_squared", 0)
    
    # Рекомендации по уровню NDVI
    if mean_ndvi < 0.3:
        recommendations.append(
            "⚠️ Низкий NDVI: проверьте посевы на наличие стресса "
            "(засуха, вредители, болезни)"
        )
        recommendations.append(
            "💧 Рассмотрите возможность дополнительного орошения или "
            "внесения удобрений"
        )
        recommendations.append(
            "📊 Проведите почвенный анализ для выявления дефицита питательных веществ"
        )
    elif mean_ndvi < 0.45:
        recommendations.append(
            "⚡ NDVI ниже оптимального: мониторьте состояние посевов "
            "каждые 5–7 дней"
        )
        recommendations.append(
            "🌡️ Проанализируйте данные по осадкам и температуре за период"
        )
    else:
        recommendations.append(
            "✅ NDVI в норме: продолжайте регулярный мониторинг каждые 10–14 дней"
        )
    
    # Рекомендации по тренду
    if trend_direction == "decreasing" and r_squared > 0.5:
        recommendations.append(
            "📉 Тренд снижения NDVI: требуется детальный анализ причин ухудшения"
        )
        recommendations.append(
            "🔍 Проверьте историю обработки полей и погодные условия"
        )
    elif trend_direction == "increasing" and r_squared > 0.5:
        recommendations.append(
            "📈 Положительный тренд: состояние растительности улучшается"
        )
    elif trend_direction == "stable":
        recommendations.append(
            "➡️ Стабильный NDVI: мониторьте дальнейшую динамику"
        )
    
    # Вариабельность
    std_ndvi = statistics.get("std_ndvi", 0)
    if std_ndvi > 0.15:
        recommendations.append(
            "📊 Высокая вариабельность NDVI: возможна неоднородность полей "
            "или изменчивые условия"
        )
    
    # Общие рекомендации
    recommendations.append(
        "📅 Сравните текущие показатели с данными прошлых лет для "
        "выявления аномалий"
    )
    recommendations.append(
        "🛰️ Используйте мультиспектральный анализ для детальной диагностики"
    )
    
    return recommendations


def generate_ndvi_report(
    bbox: List[float],
    date: str,
    period_days: int = 30
) -> Dict[str, Any]:
    """
    Генерирует отчёт по NDVI за указанный период до даты.
    
    Args:
        bbox: [minlon, minlat, maxlon, maxlat]
        date: Конечная дата (YYYY-MM-DD)
        period_days: Количество дней назад от даты
        
    Returns:
        Dict: Детальный отчёт с рекомендациями
    """
    try:
        end_date = datetime.strptime(date, "%Y-%m-%d")
        start_date = end_date - timedelta(days=period_days)
        
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        
        logger.info(f"Generating NDVI report for {start_str} to {end_str}")
        
        # Получаем статистику
        stats_data = get_ndvi_statistics(
            bbox=bbox,
            start_date=start_str,
            end_date=end_str,
            aggregation_days=5
        )
        
        if stats_data["status"] != "success":
            return {
                "status": "error",
                "message": "Failed to generate report",
                "region": "Акмолинская область",
                "report_date": date
            }
        
        statistics = stats_data["statistics"]
        timeline = stats_data["timeline"]
        mean_ndvi = statistics.get("mean_ndvi", 0.0)
        
        # Классификация состояния
        status_info = classify_ndvi_status(mean_ndvi)
        
        # Генерация рекомендаций
        recommendations = generate_recommendations(
            mean_ndvi, statistics, timeline
        )
        
        # Сельскохозяйственные зоны
        zones = get_agricultural_zones(bbox)
        
        return {
            "status": "success",
            "region": "Акмолинская область",
            "report_date": date,
            "period_analyzed": f"{start_str} – {end_str}",
            "vegetation_status": {
                "overall": status_info["level"],
                "description": status_info["description"],
                "trend": statistics.get("trend", {}).get("description", ""),
                "recommendations": recommendations
            },
            "ndvi_statistics": {
                "mean_ndvi": statistics.get("mean_ndvi", 0.0),
                "median_ndvi": statistics.get("median_ndvi", 0.0),
                "std_ndvi": statistics.get("std_ndvi", 0.0),
                "min_ndvi": statistics.get("min_ndvi", 0.0),
                "max_ndvi": statistics.get("max_ndvi", 0.0),
                "observations_count": statistics.get("total_observations", 0)
            },
            "timeline": timeline,
            "agricultural_zones": zones,
            "products_available": stats_data.get("products_available", 0)
        }
        
    except NoDataAvailableError as e:
        logger.error(f"No data for report: {e}")
        return {
            "status": "error",
            "message": str(e),
            "region": "Акмолинская область",
            "report_date": date
        }
    except Exception as e:
        logger.error(f"Report generation error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "region": "Акмолинская область",
            "report_date": date
        }


# ----------------------- Утилиты для batch операций ------------------- #

def get_multiple_points_timeseries(
    points: List[Tuple[float, float]],
    bbox: List[float],
    start_date: str,
    end_date: str,
    max_dates: int = 20
) -> Dict[str, Any]:
    """
    Получает тайм-серии NDVI для нескольких точек.
    
    Args:
        points: Список (lon, lat) координат
        bbox: Общий bbox для всех точек
        start_date: Начальная дата
        end_date: Конечная дата
        max_dates: Максимум дат на точку
        
    Returns:
        Dict: Временные ряды для всех точек
    """
    results = []
    
    for i, (lon, lat) in enumerate(points):
        try:
            series = get_point_timeseries(
                lon=lon,
                lat=lat,
                bbox=bbox,
                start_date=start_date,
                end_date=end_date,
                max_dates=max_dates
            )
            results.append({
                "point_id": i,
                "lon": lon,
                "lat": lat,
                "series": series.get("series", []),
                "status": series.get("status", "error")
            })
        except Exception as e:
            logger.error(f"Failed to get series for point {i} ({lon}, {lat}): {e}")
            results.append({
                "point_id": i,
                "lon": lon,
                "lat": lat,
                "series": [],
                "status": "error",
                "error": str(e)
            })
    
    return {
        "status": "success",
        "points": results,
        "total_points": len(points)
    }