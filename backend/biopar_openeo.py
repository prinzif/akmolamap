"""
backend/biopar_openeo.py — BIOPAR (CCC, CWC) через openEO.

Поддерживает параметры через openEO UDP:
- FAPAR, LAI, FCOVER (для совместимости с SH)
- CCC, CWC (только через openEO)
"""

from __future__ import annotations

import logging
import hashlib
import json
import inspect
from pathlib import Path
from typing import Dict, Any, Sequence, Optional

import openeo
from backend.settings import settings

logger = logging.getLogger(__name__)

# -----------------------------
# Константы и окружение
# -----------------------------
# Директория кэша
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "biopar"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# URL UDP процесса BIOPAR (описание алгоритма)
BIOPAR_UDP_URL = (
    "https://raw.githubusercontent.com/ESA-APEx/apex_algorithms/refs/heads/main/"
    "algorithm_catalog/vito/biopar/openeo_udp/biopar.json"
)

# Поддерживаемые типы
BIOPAR_TYPES = {"FAPAR", "LAI", "FCOVER", "CCC", "CWC"}


# -----------------------------
# Исключения
# -----------------------------
class OpenEOError(Exception):
    """Базовая ошибка openEO."""
    pass


class NoDataAvailableError(OpenEOError):
    """Нет данных для запрошенного периода/области."""
    pass


# -----------------------------
# Вспомогательные функции
# -----------------------------
def _cache_key(
    aoi: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str
) -> str:
    """Генерирует SHA256 ключ для кэша (более безопасен чем MD5)."""
    payload = {
        "aoi": aoi,
        "start": start_date,
        "end": end_date,
        "biopar": biopar_type.upper(),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"biopar_openeo_{biopar_type.lower()}_{digest}.tif"


def _normalize_backend_url(raw: str | None) -> str:
    """Гарантирует https:// префикс у backend URL."""
    default_host = "openeo.dataspace.copernicus.eu"
    backend = (raw or default_host).strip()
    if not backend.startswith("http://") and not backend.startswith("https://"):
        backend = "https://" + backend
    return backend


def _authenticate(con: openeo.Connection) -> openeo.Connection:
    """
    Унифицированная аутентификация к openEO/CDSE.
    По умолчанию используем client_credentials (безинтерактивный серверный режим).
    При OPENEO_AUTH_MODE=device — device code flow с публичным клиентом.

    Учитываем различия версий openeo-python-client:
    - у старых версий у методов нет параметра `scopes`.
    """
    provider_id = "CDSE"
    scopes = [s for s in (settings.OPENEO_SCOPES or "openid").split() if s]

    if settings.OPENEO_AUTH_MODE == "client_credentials":
        if not (settings.CDSE_CLIENT_ID and settings.CDSE_CLIENT_SECRET):
            raise OpenEOError("CDSE_CLIENT_ID/CDSE_CLIENT_SECRET не заданы для client_credentials")
        logger.info("Authenticating via OIDC (client_credentials)...")

        sig = inspect.signature(con.authenticate_oidc_client_credentials)
        kwargs = dict(provider_id=provider_id,
                      client_id=settings.CDSE_CLIENT_ID,
                      client_secret=settings.CDSE_CLIENT_SECRET)
        if "scopes" in sig.parameters:
            kwargs["scopes"] = scopes

        return con.authenticate_oidc_client_credentials(**kwargs)

    # device code flow (интерактивный): используем публичный клиент
    client_id = settings.OPENEO_PUBLIC_CLIENT_ID or "cdse-public"
    logger.info("Authenticating via OIDC (device code flow, public client)...")

    sig = inspect.signature(con.authenticate_oidc)
    kwargs = dict(provider_id=provider_id,
                  client_id=client_id,
                  use_device_code=True,
                  store_refresh_token=True)
    if "scopes" in sig.parameters:
        kwargs["scopes"] = scopes

    return con.authenticate_oidc(**kwargs)


def _connect() -> openeo.Connection:
    backend_url = _normalize_backend_url(settings.OPENEO_BACKEND_URL)
    logger.info(f"Connecting to openEO backend: {backend_url}")
    con = openeo.connect(backend_url)
    con = _authenticate(con)
    logger.info("✅ openEO authenticated successfully")
    return con


# -----------------------------
# Публичные функции
# -----------------------------
def fetch_biopar_openeo(
    aoi_geojson: Dict[str, Any],
    start_date: str,
    end_date: str,
    biopar_type: str = "CCC",
    force: bool = False,
    job_id: Optional[str] = None,
) -> Path:
    """
    Загружает BIOPAR GeoTIFF через openEO UDP.

    Args:
        aoi_geojson: GeoJSON Polygon (EPSG:4326)
        start_date: Начальная дата (YYYY-MM-DD)
        end_date: Конечная дата (YYYY-MM-DD)
        biopar_type: Тип параметра (FAPAR, LAI, FCOVER, CCC, CWC)
        force: Игнорировать кэш
        job_id: Optional job ID for progress tracking

    Returns:
        Path: Путь к GeoTIFF файлу

    Raises:
        OpenEOError: Ошибка при работе с openEO
        NoDataAvailableError: Нет данных для периода

    Note:
        To track progress, pass a job_id and use the job_tracker:
        ```python
        from backend.job_tracker import job_tracker
        job_id = "biopar_" + str(uuid.uuid4())
        job_tracker.create_job(job_id, "biopar_geotiff", total_steps=3)
        result = fetch_biopar_openeo(..., job_id=job_id)
        ```
    """
    biopar_type = biopar_type.upper()
    if biopar_type not in BIOPAR_TYPES:
        raise ValueError(f"biopar_type должен быть одним из {sorted(BIOPAR_TYPES)}")

    # Кэш
    cache_name = _cache_key(aoi_geojson, start_date, end_date, biopar_type)
    cache_path = CACHE_DIR / cache_name

    if cache_path.exists() and not force:
        logger.info(f"[openEO] cache hit: {cache_name}")
        return cache_path

    logger.info(f"[openEO] Fetching {biopar_type}: {start_date}..{end_date}")

    try:
        # 1) Подключение/аутентификация
        connection = _connect()

        # 2) Создание datacube через UDP-процесс
        logger.info(f"Creating BIOPAR datacube for {biopar_type}...")
        cube = connection.datacube_from_process(
            process_id="biopar",
            namespace=BIOPAR_UDP_URL,
            temporal_extent=[start_date, end_date],
            spatial_extent=aoi_geojson,
            biopar_type=biopar_type,
        )

        # 3) Скачивание результата как GeoTIFF
        logger.info("Downloading result...")
        # Apply timeouts from settings
        try:
            cube.download(
                outputfile=str(cache_path),
                format="GTiff",
                timeout=settings.OPENEO_DOWNLOAD_TIMEOUT,
                max_poll_duration=settings.OPENEO_JOB_TIMEOUT
            )
        except TypeError:
            # Fallback for older openeo-python-client versions that don't support these parameters
            logger.warning("OpenEO client doesn't support timeout parameters, using defaults")
            cube.download(outputfile=str(cache_path), format="GTiff")

        file_size = cache_path.stat().st_size
        logger.info(f"[openEO] {biopar_type} saved: {cache_name}, size: {file_size:,} bytes")

        # 4) Сохраняем метаданные рядом
        metadata_path = cache_path.with_suffix(".json")
        metadata = {
            "aoi": aoi_geojson,
            "start_date": start_date,
            "end_date": end_date,
            "biopar_type": biopar_type,
            "file_size_bytes": file_size,
            "backend": _normalize_backend_url(settings.OPENEO_BACKEND_URL),
            "udp_url": BIOPAR_UDP_URL,
            "auth_mode": settings.OPENEO_AUTH_MODE,
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return cache_path

    except openeo.rest.OpenEoApiError as e:
        logger.error(f"openEO API error: {e}", exc_info=True)
        msg = str(e).lower()
        if any(k in msg for k in ("no data", "no scenes", "empty collection", "not enough scenes")):
            raise NoDataAvailableError(
                f"No satellite data available for {biopar_type} in period {start_date}..{end_date}"
            )
        raise OpenEOError(f"openEO API error: {e}")

    except Exception as e:
        logger.error(f"Unexpected openEO error: {e}", exc_info=True)
        raise OpenEOError(f"Failed to fetch BIOPAR via openEO: {e}")


def clear_cache(older_than_days: int | None = None) -> int:
    """Очищает кэш openEO файлов.

    Args:
        older_than_days: удалить файлы старше N дней; если None — удалить все.

    Returns:
        int: число удалённых файлов.
    """
    import time

    if not CACHE_DIR.exists():
        return 0

    deleted = 0
    cutoff_time = None
    if older_than_days:
        cutoff_time = time.time() - (older_than_days * 86400)

    for file_path in CACHE_DIR.glob("*"):
        if file_path.is_file():
            try:
                if cutoff_time is None or file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()
                    deleted += 1
            except Exception as ex:
                logger.warning(f"Failed to delete {file_path}: {ex}")

    logger.info(f"openEO cache cleanup: deleted {deleted} files")
    return deleted
