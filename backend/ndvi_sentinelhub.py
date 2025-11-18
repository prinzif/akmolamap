"""
/backend/ndvi_sentinelhub.py - NDVI через Sentinel Hub Processing API.

Улучшенная версия с:
- Правильными evalscript V3 согласно документации
- Harmonization для Sentinel-2 временных рядов
- Гибкими параметрами mosaicking и processing
- Улучшенным кэшированием и обработкой ошибок
"""
# Добавьте этот импорт в начало файла
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
import logging
import os
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
import hashlib
import json
import requests
from enum import Enum

logger = logging.getLogger(__name__)

# Импорт настроек для exponential backoff
from backend.settings import settings

# Загрузка .env
env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_path)


def _calculate_retry_delay(attempt: int, base_delay: float, backoff_factor: float) -> float:
    """
    Вычисляет задержку с экспоненциальным отступом.

    Args:
        attempt: Номер попытки (0-based)
        base_delay: Базовая задержка в секундах
        backoff_factor: Коэффициент экспоненциального роста

    Returns:
        Задержка в секундах с экспоненциальным отступом
    """
    return base_delay * (backoff_factor ** attempt)

# Директория кэша
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "ndvi"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CDSE credentials
CDSE_CLIENT_ID = os.getenv("CDSE_CLIENT_ID")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET")

if not CDSE_CLIENT_ID or not CDSE_CLIENT_SECRET:
    raise RuntimeError(
        "CDSE credentials not configured. "
        "Set CDSE_CLIENT_ID and CDSE_CLIENT_SECRET environment variables. "
        "See .env.example for template."
    )

logger.info(f"CDSE credentials loaded: {CDSE_CLIENT_ID[:10]}...")

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

# Версия evalscript для кэш-инвалидации
EVALSCRIPT_VERSION = "v2.0"


class MosaickingOrder(str, Enum):
    """Типы упорядочивания мозаики согласно Sentinel Hub API."""
    MOST_RECENT = "mostRecent"
    LEAST_RECENT = "leastRecent"
    LEAST_CC = "leastCC"  # Наименьшая облачность


class SentinelHubError(Exception):
    """Базовая ошибка Sentinel Hub API."""
    pass


class NoDataAvailableError(SentinelHubError):
    """Нет данных для запрошенного периода/области."""
    pass


class AuthenticationError(SentinelHubError):
    """Ошибка аутентификации."""
    pass


def get_cdse_token() -> str:
    """
    Получить OAuth2 токен для Copernicus Data Space Ecosystem.
    
    Returns:
        str: Access token
        
    Raises:
        AuthenticationError: При ошибке аутентификации
    """
    try:
        logger.info(f"Requesting token for client: {CDSE_CLIENT_ID[:10]}...")
        
        resp = requests.post(
            CDSE_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": CDSE_CLIENT_ID,
                "client_secret": CDSE_CLIENT_SECRET,
            },
            timeout=30,
        )
        
        logger.info(f"Token response status: {resp.status_code}")
        
        if resp.status_code != 200:
            error_msg = f"Authentication failed: {resp.text}"
            logger.error(error_msg)
            raise AuthenticationError(error_msg)
            
        token = resp.json()["access_token"]
        logger.info("Token obtained successfully")
        return token
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during authentication: {e}", exc_info=True)
        raise AuthenticationError(f"Network error: {e}")
    except KeyError as e:
        logger.error(f"Invalid token response format: {e}", exc_info=True)
        raise AuthenticationError("Invalid token response format")
    except Exception as e:
        logger.error(f"Unexpected auth error: {e}", exc_info=True)
        raise AuthenticationError(f"Unexpected error: {e}")


def get_ndvi_evalscript(use_cloud_mask: bool = True, mosaicking: str = "SIMPLE") -> str:
    """
    Генерирует evalscript V3 для NDVI согласно документации Sentinel Hub.
    
    Args:
        use_cloud_mask: Использовать облачную маску (SCL)
        mosaicking: Тип мозаики ("SIMPLE", "ORBIT", "TILE")
        
    Returns:
        str: Evalscript V3 код
        
    Notes:
        - Использует FLOAT32 для точных значений NDVI
        - Облачная маска через SCL (Scene Classification Layer)
        - Правильная обработка dataMask для nodata пикселей
        - Деление на zero защищено через epsilon
    """
    
    # Базовые bands
    bands = ["B04", "B08", "dataMask"]
    if use_cloud_mask:
        bands.append("SCL")
    
    bands_str = json.dumps(bands)
    
    evalscript = f"""//VERSION=3
function setup() {{
  return {{
    input: [{{
      bands: {bands_str}
    }}],
    output: {{
      id: "default",
      bands: 1,
      sampleType: "FLOAT32"
    }},
    mosaicking: "{mosaicking}"
  }};
}}

function evaluatePixel(sample) {{
  // Проверка на nodata
  if (sample.dataMask === 0) {{
    return [NaN];
  }}
  
  {"// Маска облаков по Scene Classification Layer" if use_cloud_mask else ""}
  {"if (sample.SCL === 3 || sample.SCL === 8 || sample.SCL === 9 || sample.SCL === 10 || sample.SCL === 11) {" if use_cloud_mask else ""}
  {"  return [NaN];" if use_cloud_mask else ""}
  {"}" if use_cloud_mask else ""}
  
  // Вычисление NDVI с защитой от деления на ноль
  let denom = sample.B08 + sample.B04;
  if (denom === 0) {{
    return [NaN];
  }}
  
  let ndvi = (sample.B08 - sample.B04) / denom;
  
  // Клиппинг к [-1, 1] для корректности
  ndvi = Math.max(-1, Math.min(1, ndvi));
  
  return [ndvi];
}}
"""
    
    return evalscript


def _cache_key(
    bbox: List[float],
    start_date: str,
    end_date: str,
    width: int,
    height: int,
    max_cloud_coverage: int,
    mosaicking_order: Optional[str],
    harmonize: bool,
    use_cloud_mask: bool
) -> str:
    """
    Генерирует стабильный ключ кэша из параметров запроса.
    
    Args:
        bbox: Bounding box [minlon, minlat, maxlon, maxlat]
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        width: Ширина выходного изображения
        height: Высота выходного изображения
        max_cloud_coverage: Максимальная облачность (%)
        mosaicking_order: Порядок мозаики
        harmonize: Использовать harmonization
        use_cloud_mask: Использовать облачную маску
        
    Returns:
        str: Имя файла кэша
    """
    payload = {
        "bbox": [round(b, 6) for b in bbox],
        "start": start_date,
        "end": end_date,
        "w": int(width),
        "h": int(height),
        "cloud": int(max_cloud_coverage),
        "mosaic": mosaicking_order or "default",
        "harmonize": harmonize,
        "mask": use_cloud_mask,
        "evalscript_version": EVALSCRIPT_VERSION
    }
    
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]  # First 16 chars for shorter filenames

    return f"ndvi_{digest}.tif"


def fetch_ndvi_geotiff(
    bbox: List[float],
    start_date: str,
    end_date: str,
    width: int = 2048,
    height: int = 2048,
    max_cloud_coverage: int = 20,
    mosaicking_order: Optional[MosaickingOrder] = MosaickingOrder.LEAST_CC,
    harmonize_values: bool = True,
    use_cloud_mask: bool = True,
    max_retries: int = 2,
    retry_delay: int = 5,
    resampling: str = "BILINEAR",
    upsampling: Optional[str] = None,
    downsampling: Optional[str] = None
) -> Path:
    """
    Запрашивает NDVI GeoTIFF через Sentinel Hub Processing API.
    
    Args:
        bbox: Bounding box [minlon, minlat, maxlon, maxlat] в EPSG:4326
        start_date: Начальная дата в формате YYYY-MM-DD
        end_date: Конечная дата в формате YYYY-MM-DD
        width: Ширина выходного изображения в пикселях
        height: Высота выходного изображения в пикселях
        max_cloud_coverage: Максимальная облачность (0-100%)
        mosaicking_order: Порядок мозаики (mostRecent, leastRecent, leastCC)
        harmonize_values: Применять harmonization для Sentinel-2 L2A
        use_cloud_mask: Использовать облачную маску SCL
        max_retries: Количество повторных попыток при временных ошибках
        retry_delay: Задержка между попытками в секундах
        resampling: Метод ресемплинга (NEAREST, BILINEAR, CUBIC, etc.)
        upsampling: Метод для upsampling (опционально)
        downsampling: Метод для downsampling (опционально)
    
    Returns:
        Path: Путь к кэшированному GeoTIFF файлу
        
    Raises:
        NoDataAvailableError: Нет спутниковых данных для периода/области
        AuthenticationError: Ошибка аутентификации
        SentinelHubError: Другие ошибки API
        
    Examples:
        >>> path = fetch_ndvi_geotiff(
        ...     bbox=[69.0, 51.0, 73.0, 53.0],
        ...     start_date="2024-06-01",
        ...     end_date="2024-06-30",
        ...     max_cloud_coverage=30
        ... )
    """
    
    # Проверка входных параметров
    if len(bbox) != 4:
        raise ValueError("bbox must contain 4 values: [minlon, minlat, maxlon, maxlat]")
    
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("Invalid bbox: min values must be less than max values")
    
    if not (0 <= max_cloud_coverage <= 100):
        raise ValueError("max_cloud_coverage must be between 0 and 100")
    
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    
    # Конвертация MosaickingOrder enum в строку
    mosaic_str = mosaicking_order.value if isinstance(mosaicking_order, MosaickingOrder) else mosaicking_order
    
    # Проверка кэша
    cache_name = _cache_key(
        bbox, start_date, end_date, width, height, 
        max_cloud_coverage, mosaic_str, harmonize_values, use_cloud_mask
    )
    cache_path = CACHE_DIR / cache_name

    if cache_path.exists():
        logger.info(f"Cache hit: {cache_name}")
        return cache_path

    logger.info(
        f"Fetching NDVI: bbox={bbox}, period={start_date}..{end_date}, "
        f"size={width}x{height}, cloud<={max_cloud_coverage}%, "
        f"mosaic={mosaic_str}, harmonize={harmonize_values}"
    )

    # Получение токена
    try:
        token = get_cdse_token()
    except AuthenticationError:
        raise
    
    # Генерация evalscript
    evalscript = get_ndvi_evalscript(
        use_cloud_mask=use_cloud_mask,
        mosaicking="SIMPLE"
    )

    # Формирование dataFilter
    data_filter: Dict[str, Any] = {
        "timeRange": {
            "from": f"{start_date}T00:00:00Z",
            "to": f"{end_date}T23:59:59Z"
        },
        "maxCloudCoverage": max_cloud_coverage
    }
    
    if mosaic_str:
        data_filter["mosaickingOrder"] = mosaic_str

    # Формирование processing параметров
    processing: Dict[str, Any] = {}
    
    if harmonize_values:
        processing["harmonizeValues"] = True
    
    # Resampling параметры
    if upsampling:
        processing["upsampling"] = upsampling
    if downsampling:
        processing["downsampling"] = downsampling
    if resampling and not (upsampling or downsampling):
        # Используем resampling только если не указаны upsampling/downsampling
        processing["resampling"] = resampling

    # Формирование payload
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
                "dataFilter": data_filter
            }]
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{
                "identifier": "default",
                "format": {
                    "type": "image/tiff"
                }
            }]
        },
        "evalscript": evalscript
    }
    
    # Добавляем processing только если есть параметры
    if processing:
        payload["processing"] = processing

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Retry логика
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            logger.info(
                f"Sending request to Sentinel Hub Processing API "
                f"(attempt {attempt + 1}/{max_retries + 1})..."
            )
            
            resp = requests.post(
                SH_PROCESS_URL,
                headers=headers,
                json=payload,
                timeout=180
            )
            
            logger.info(f"Processing API response status: {resp.status_code}")
            
            # Обработка специфичных статусов
            if resp.status_code == 400:
                error_text = resp.text
                logger.error(f"Bad Request (400): {error_text}")
                
                # Проверяем индикаторы отсутствия данных
                error_lower = error_text.lower()
                if any(phrase in error_lower for phrase in [
                    "no data", "no satellite", "no scenes", "no products"
                ]):
                    raise NoDataAvailableError(
                        f"No satellite data available for period {start_date} to {end_date} "
                        f"with cloud coverage <= {max_cloud_coverage}%. "
                        f"Try expanding the date range or increasing max_cloud_coverage."
                    )
                
                raise SentinelHubError(f"Invalid request parameters: {error_text}")
            
            elif resp.status_code == 401:
                raise AuthenticationError("Invalid or expired token")
            
            elif resp.status_code == 429:
                # Rate limit exceeded
                if attempt < max_retries:
                    # Use Retry-After header if available, otherwise use exponential backoff
                    if "Retry-After" in resp.headers:
                        retry_after = int(resp.headers.get("Retry-After", retry_delay * 1000)) / 1000
                    else:
                        retry_after = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                    logger.warning(f"Rate limit exceeded, waiting {retry_after:.1f}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(retry_after)
                    # Обновляем токен на случай его истечения
                    token = get_cdse_token()
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                else:
                    raise SentinelHubError(f"Rate limit exceeded after {max_retries} retries")
            
            elif resp.status_code in (502, 503, 504):
                # Временные ошибки сервера
                if attempt < max_retries:
                    delay = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                    logger.warning(
                        f"Server error {resp.status_code}, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(delay)
                    continue
                else:
                    raise SentinelHubError(
                        f"Sentinel Hub service unavailable (HTTP {resp.status_code}) "
                        f"after {max_retries} retries. Please try again later."
                    )
            
            elif resp.status_code != 200:
                logger.error(f"Processing API error ({resp.status_code}): {resp.text}")
                resp.raise_for_status()
            
            # Успешный ответ - проверяем содержимое
            content_length = len(resp.content)
            
            # GeoTIFF должен иметь минимальный размер
            # Пустой/corrupted TIFF обычно < 1KB
            MIN_VALID_SIZE = 1000
            
            if content_length < MIN_VALID_SIZE:
                logger.warning(
                    f"Suspiciously small response: {content_length} bytes "
                    f"(expected > {MIN_VALID_SIZE})"
                )
                
                if attempt < max_retries:
                    delay = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                    logger.warning(f"Retrying due to small response in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                else:
                    raise NoDataAvailableError(
                        f"Received empty or corrupted data for {start_date}..{end_date}. "
                        f"This usually means no valid satellite data is available."
                    )
            
            # Проверяем, что это действительно TIFF
            if not resp.content.startswith(b'II\x2a\x00') and \
               not resp.content.startswith(b'MM\x00\x2a'):
                logger.warning("Response doesn't appear to be a valid TIFF file")
                
                if attempt < max_retries:
                    delay = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                    logger.warning(f"Retrying due to invalid TIFF format in {delay:.1f}s...")
                    time.sleep(delay)
                    continue
                else:
                    raise SentinelHubError(
                        "Received invalid TIFF data from API. "
                        "This may indicate a server-side processing error."
                    )
            
            # Сохраняем успешный результат атомарно
            # Используем atomic_write_cache для предотвращения частичных записей
            try:
                from backend.utils import atomic_write_cache
                atomic_write_cache(cache_path, resp.content, use_lock=True)
                logger.info(
                    f"NDVI saved: {cache_name}, size: {content_length:,} bytes"
                )
            except Exception as write_error:
                # Очистка при ошибке записи
                logger.error(f"Failed to write cache file: {write_error}")
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                        logger.debug(f"Cleaned up partial cache file: {cache_path}")
                    except Exception as cleanup_error:
                        logger.warning(f"Could not clean up cache file: {cleanup_error}")
                raise SentinelHubError(f"Failed to save GeoTIFF: {write_error}")
            
            # Сохраняем метаданные запроса для отладки
            metadata_path = cache_path.with_suffix('.json')
            metadata = {
                "bbox": bbox,
                "start_date": start_date,
                "end_date": end_date,
                "width": width,
                "height": height,
                "max_cloud_coverage": max_cloud_coverage,
                "mosaicking_order": mosaic_str,
                "harmonize_values": harmonize_values,
                "use_cloud_mask": use_cloud_mask,
                "file_size_bytes": content_length,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "evalscript_version": EVALSCRIPT_VERSION
            }

            try:
                with open(metadata_path, "w") as f:
                    json.dump(metadata, f, indent=2)
            except Exception as meta_error:
                # Метаданные не критичны, логируем и продолжаем
                logger.warning(f"Could not save metadata: {meta_error}")

            return cache_path

        except requests.exceptions.Timeout:
            last_error = "Request timeout (180s)"
            if attempt < max_retries:
                delay = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                logger.warning(f"Timeout, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"Timeout after {max_retries} retries")
                raise SentinelHubError(
                    f"Request timeout after {max_retries} retries. "
                    f"The requested area or time range may be too large."
                )
        
        except requests.exceptions.ConnectionError as e:
            last_error = f"Connection error: {e}"
            if attempt < max_retries:
                delay = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                logger.warning(f"Connection error, retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            else:
                logger.error(f"Connection error after {max_retries} retries")
                raise SentinelHubError(
                    f"Connection failed after {max_retries} retries: {e}"
                )
        
        except (NoDataAvailableError, AuthenticationError, SentinelHubError):
            # Эти ошибки не retry-им
            raise
        
        except Exception as e:
            last_error = str(e)
            logger.error(
                f"Unexpected error (attempt {attempt + 1}): {e}",
                exc_info=True
            )
            if attempt < max_retries:
                delay = _calculate_retry_delay(attempt, retry_delay, settings.RETRY_BACKOFF_FACTOR)
                logger.warning(f"Retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(delay)
                continue
            else:
                raise SentinelHubError(
                    f"Processing failed after {max_retries} retries: {last_error}"
                )
    
    # Не должны сюда попасть, но на всякий случай
    raise SentinelHubError(
        f"Failed to fetch NDVI after {max_retries} retries: {last_error}"
    )


def clear_cache(older_than_days: Optional[int] = None) -> int:
    """
    Очищает кэш NDVI файлов.
    
    Args:
        older_than_days: Удалить только файлы старше N дней (None = все)
        
    Returns:
        int: Количество удалённых файлов
    """
    if not CACHE_DIR.exists():
        return 0
    
    deleted = 0
    cutoff_time = None
    
    if older_than_days:
        cutoff_time = time.time() - (older_than_days * 86400)
    
    for file_path in CACHE_DIR.glob("*"):
        if file_path.is_file():
            if cutoff_time is None or file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {file_path}: {e}")
    
    logger.info(f"Cache cleanup: deleted {deleted} files")
    return deleted