# ===============================================
# backend/settings.py
# ===============================================
from pathlib import Path
import logging
from typing import Tuple, Optional, Literal
from pydantic import Field, AliasChoices, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ================== CONFIG ==================
    # Читаем .env, кодировка UTF-8; игнорируем лишние ключи, чтобы не падать
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==== CDSE / Sentinel ====
    CDSE_CLIENT_ID: Optional[str] = None
    CDSE_CLIENT_SECRET: Optional[str] = None
    CDSE_TOKEN_URL: str = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    CDSE_API_URL: str = "https://catalogue.dataspace.copernicus.eu/odata/v1"

    # ==== OpenEO (CDSE backend) ====
    # Поддерживаем и UPPER, и lower ключи в .env
    OPENEO_BACKEND_URL: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("OPENEO_BACKEND_URL", "openeo_backend_url"),
    )
    OPENEO_OIDC_ISSUER: Optional[HttpUrl] = Field(
        default=None,
        validation_alias=AliasChoices("OPENEO_OIDC_ISSUER", "openeo_oidc_issuer"),
    )
    # Режим аутентификации: по умолчанию безинтерактивный client_credentials
    OPENEO_AUTH_MODE: Literal["client_credentials", "device"] = "client_credentials"
    # Для device-флоу используем публичный клиент (без секрета)
    OPENEO_PUBLIC_CLIENT_ID: Optional[str] = "cdse-public"
    # Скоупы для OIDC
    OPENEO_SCOPES: str = "openid"

    # ==== NASA EONET ====
    EONET_URL: str = "https://eonet.gsfc.nasa.gov/api/v3/events"

    # ==== География ====
    # (lonmin, latmin, lonmax, latmax)
    BBOX_AKMOLA: Tuple[float, float, float, float] = (65.0, 49.5, 76.0, 54.0)

    # ==== Кэш ====
    CACHE_TTL_EVENTS: int = 600
    CACHE_TTL_SEARCH: int = 300

    # ==== EONET Debug Mode ====
    EONET_DEBUG: bool = False

    # ==== Файловая система ====
    DATA_DIR: Path = Path("./data")
    COG_DIR: Path = DATA_DIR / "cog"
    TMP_DIR: Path = DATA_DIR / "tmp"

    # ==== Celery / Redis ====
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_BACKEND_URL: str = "redis://localhost:6379/0"

    # ==== Логи ====
    LOG_LEVEL: str = "INFO"

    # Request/Response Logging
    LOG_REQUESTS: bool = True                    # Enable request/response logging
    LOG_REQUEST_BODY: bool = False               # Log request bodies (can be verbose)
    LOG_RESPONSE_BODY: bool = False              # Log response bodies (can be verbose)
    LOG_SLOW_REQUESTS_MS: int = 1000             # Log requests slower than this (ms)

    # Metrics Collection
    ENABLE_METRICS: bool = True                  # Enable metrics collection

    # Rate Limiting (informational headers, not enforced yet)
    RATE_LIMIT_ENABLED: bool = True              # Enable rate limit headers
    RATE_LIMIT_PER_MINUTE: int = 60              # Requests per minute limit
    RATE_LIMIT_PER_HOUR: int = 1000              # Requests per hour limit

    # ==== CORS ====
    # Comma-separated list of allowed origins
    CORS_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    # ==== API Base URL ====
    # Base URL for the API server (used for generating file URLs)
    # This should be set to the public URL of the API server
    # Examples:
    #   - Local: http://localhost:8000
    #   - Docker: http://api:8000 or http://localhost:8000 (depending on network setup)
    #   - Production: https://api.example.com
    API_BASE_URL: str = "http://localhost:8000"

    # ==== Sentinel Hub API Endpoints ====
    SH_STATISTICS_URL: str = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
    SH_PROCESS_URL: str = "https://sh.dataspace.copernicus.eu/api/v1/process"

    # ==== NDVI/BIOPAR Processing Constants ====
    # Resolution limits (meters per pixel)
    S2L2A_MIN_MPP: int = 10        # Minimum resolution for Sentinel-2 L2A
    S2L2A_MAX_MPP: int = 1500      # Maximum resolution for Statistical API
    BIOPAR_MIN_MPP: int = 10       # Minimum resolution for BIOPAR
    BIOPAR_MAX_MPP: int = 300      # Maximum resolution for BIOPAR

    # BIOPAR defaults
    BIOPAR_TARGET_MPP: int = 60    # Default target resolution for BIOPAR (meters per pixel)
    BIOPAR_MAX_CLOUD: int = 50     # Default maximum cloud coverage percentage

    # Pixel dimension limits
    MIN_PIXELS: int = 64           # Minimum pixels to avoid 1x1 images
    MAX_PIXELS: int = 4096         # Maximum pixels to prevent memory issues

    # HTTP Request timeouts (seconds)
    HTTP_REQUEST_TIMEOUT: int = 120          # General API request timeout
    HTTP_DOWNLOAD_TIMEOUT: int = 300         # GeoTIFF download timeout

    # OpenEO timeouts (seconds)
    OPENEO_JOB_TIMEOUT: int = 600            # Maximum time to wait for OpenEO job completion
    OPENEO_DOWNLOAD_TIMEOUT: int = 300       # Timeout for downloading OpenEO results

    # Retry configuration
    MAX_RETRIES: int = 3                     # Maximum retry attempts
    RETRY_DELAY: int = 2                     # Initial retry delay (seconds)
    RETRY_BACKOFF_FACTOR: float = 2.0        # Exponential backoff multiplier

    # ==== TiTiler Configuration ====
    TITILER_ENDPOINT: str = Field(
        default="http://localhost:8001",
        validation_alias=AliasChoices("TITILER_URL", "TITILER_ENDPOINT")
    )

    # ==== Overpass API Configuration ====
    OVERPASS_ENDPOINTS: str = "https://overpass-api.de/api/interpreter,https://lz4.overpass-api.de/api/interpreter,https://z.overpass-api.de/api/interpreter"
    OVERPASS_TIMEOUT: int = 30               # Overpass query timeout (seconds)

    # ==== Cache TTL Configuration ====
    # Time-to-live in seconds for different cache types
    CACHE_TTL_GEOTIFF: int = 7 * 24 * 3600   # 7 days for GeoTIFF files
    CACHE_TTL_STATS: int = 6 * 3600          # 6 hours for statistics JSON
    CACHE_TTL_TIMESERIES: int = 6 * 3600     # 6 hours for timeseries data
    CACHE_TTL_REPORTS: int = 24 * 3600       # 24 hours for generated reports

    # Cache size limits (MB)
    CACHE_MAX_SIZE_MB: int = 5000            # Maximum total cache size (5GB)
    CACHE_CLEANUP_AGE_DAYS: int = 30         # Delete files older than 30 days
    CACHE_WARNING_THRESHOLD_PCT: float = 80.0  # Warning threshold percentage
    CACHE_CRITICAL_THRESHOLD_PCT: float = 95.0  # Critical threshold percentage

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS into a list"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def overpass_endpoints_list(self) -> list[str]:
        """Parse OVERPASS_ENDPOINTS into a list"""
        return [endpoint.strip() for endpoint in self.OVERPASS_ENDPOINTS.split(",") if endpoint.strip()]


# ================== Инициализация ==================
settings = Settings()

# Гарантируем существование директорий
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.COG_DIR.mkdir(parents=True, exist_ok=True)
settings.TMP_DIR.mkdir(parents=True, exist_ok=True)

# ================== Логирование ==================
_log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("akmola")
logger.debug("Logger initialized: level=%s", settings.LOG_LEVEL)
