# backend/main.py
from pathlib import Path
import logging
import os
import re
import uuid
from typing import List, Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response

from backend.api.registry import api_v1, pages_router
from backend.settings import settings
from backend.metrics import metrics_collector
from backend.cache_monitor import CacheMonitor
from backend.job_tracker import job_tracker, JobStatus

# ==========================
# Логирование
# ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("akmola-api")

# ==========================
# Конфигурация
# ==========================
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
TITILER_URL = settings.TITILER_ENDPOINT  # Use centralized settings instead of os.getenv
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ==========================
# FastAPI
# ==========================
app = FastAPI(
    title="Akmola Sentinel API",
    description="API для мониторинга Акмолинской области с использованием данных Sentinel и NASA EONET",
    version="1.1.0",
    debug=DEBUG,
)

# ==========================
# CORS
# ==========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "X-Request-ID",
        "X-API-Version",
        "X-Process-Time",
        "X-RateLimit-Limit-Minute",
        "X-RateLimit-Limit-Hour",
        "Content-Disposition",
        "Content-Length"
    ],
    max_age=3600,  # Cache preflight for 1 hour
)

# ==========================
# Request ID & API Version Middleware
# ==========================
@app.middleware("http")
async def add_request_metadata(request: Request, call_next):
    """Add unique request ID and API version to each request for tracing"""
    import time

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.perf_counter()

    # Log incoming request if enabled
    if settings.LOG_REQUESTS:
        query_params = f"?{request.url.query}" if request.url.query else ""
        logger.info(
            "→ %s %s%s | Request-ID: %s | Client: %s",
            request.method,
            request.url.path,
            query_params,
            request_id,
            request.client.host if request.client else "unknown"
        )

        # Optionally log request body
        if settings.LOG_REQUEST_BODY and request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    logger.debug("  Request body: %s", body[:500].decode('utf-8', errors='ignore'))
            except Exception as e:
                logger.debug("  Could not log request body: %s", e)

    # Process request
    response = await call_next(request)

    # Calculate response time
    process_time_ms = (time.perf_counter() - start_time) * 1000

    # Add headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-API-Version"] = "1.1.0"
    response.headers["X-Process-Time"] = f"{process_time_ms:.2f}ms"

    # Add rate limit headers if enabled (informational, not enforced yet)
    if settings.RATE_LIMIT_ENABLED:
        response.headers["X-RateLimit-Limit-Minute"] = str(settings.RATE_LIMIT_PER_MINUTE)
        response.headers["X-RateLimit-Limit-Hour"] = str(settings.RATE_LIMIT_PER_HOUR)
        # Remaining and Reset headers would require actual rate limiting implementation
        # For now, just advertise the limits

    # Log response if enabled
    if settings.LOG_REQUESTS:
        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO

        # Mark slow requests
        slow_marker = " ⚠️ SLOW" if process_time_ms > settings.LOG_SLOW_REQUESTS_MS else ""

        logger.log(
            log_level,
            "← %s %s | Status: %d | Time: %.2fms%s | Request-ID: %s",
            request.method,
            request.url.path,
            response.status_code,
            process_time_ms,
            slow_marker,
            request_id
        )

    # Record metrics if enabled
    if settings.ENABLE_METRICS:
        metrics_collector.record_request(
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            response_time_ms=process_time_ms,
            request_id=request_id
        )

    return response

# ==========================
# Пути
# ==========================
ROOT = Path(__file__).resolve().parents[1]
FRONT_DIR = ROOT / "frontend"
ASSETS_DIR = FRONT_DIR / "assets"

CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NDVI_CACHE_DIR = CACHE_DIR / "ndvi"
BIOPAR_CACHE_DIR = CACHE_DIR / "biopar"
BIOPAR_SH_CACHE_DIR = CACHE_DIR / "biopar_sh"

for d in [NDVI_CACHE_DIR, BIOPAR_CACHE_DIR, BIOPAR_SH_CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ==========================
# Cache Monitor
# ==========================
cache_monitor = CacheMonitor(
    cache_dirs={
        "ndvi": NDVI_CACHE_DIR,
        "biopar": BIOPAR_CACHE_DIR,
        "biopar_sh": BIOPAR_SH_CACHE_DIR
    },
    max_size_mb=settings.CACHE_MAX_SIZE_MB,
    warning_threshold_pct=settings.CACHE_WARNING_THRESHOLD_PCT,
    critical_threshold_pct=settings.CACHE_CRITICAL_THRESHOLD_PCT
)

# ==========================
# Статика
# ==========================
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
    logger.info("Static files mounted: %s", ASSETS_DIR)
else:
    logger.warning("Assets directory not found: %s", ASSETS_DIR)

app.mount("/static/ndvi", StaticFiles(directory=str(NDVI_CACHE_DIR)), name="ndvi_cache")
app.mount("/static/biopar", StaticFiles(directory=str(BIOPAR_CACHE_DIR)), name="biopar_cache")
app.mount("/static/biopar_sh", StaticFiles(directory=str(BIOPAR_SH_CACHE_DIR)), name="biopar_sh_cache")
logger.info("Cache directories mounted: ndvi, biopar, biopar_sh")

# ==========================
# Health-checks
# ==========================
@app.get("/healthz", tags=["meta"])
def healthz():
    return {"status": "ok"}


@app.get("/metrics", tags=["meta"])
def get_metrics():
    """Get detailed metrics for all API endpoints"""
    return metrics_collector.get_metrics()


@app.get("/metrics/summary", tags=["meta"])
def get_metrics_summary():
    """Get summary of key metrics"""
    return metrics_collector.get_summary()


@app.get("/cache/status", tags=["meta"])
def get_cache_status():
    """Get current cache status with size and alert information"""
    return cache_monitor.get_cache_status()


@app.get("/cache/recommendations", tags=["meta"])
def get_cache_recommendations():
    """Get recommendations for cache cleanup"""
    return cache_monitor.get_cleanup_recommendations()


@app.post("/cache/cleanup", tags=["meta"])
def cleanup_cache(max_age_days: int = 30, dry_run: bool = True):
    """
    Clean up cache files older than specified days.

    Args:
        max_age_days: Maximum age of files to keep (default: 30 days)
        dry_run: If True, only report what would be deleted (default: True)
    """
    return cache_monitor.cleanup_old_files(max_age_days, dry_run)


@app.get("/jobs/{job_id}", tags=["meta"])
def get_job_status(job_id: str):
    """Get status of a specific job"""
    job = job_tracker.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job


@app.get("/jobs", tags=["meta"])
def list_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 100
):
    """
    List jobs with optional filtering.

    Args:
        status: Filter by status (pending, running, completed, failed, cancelled)
        job_type: Filter by job type
        limit: Maximum number of jobs to return (default: 100)
    """
    status_enum = None
    if status:
        try:
            status_enum = JobStatus(status.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {[s.value for s in JobStatus]}"
            )

    return job_tracker.list_jobs(status=status_enum, job_type=job_type, limit=limit)


@app.get("/jobs/stats", tags=["meta"])
def get_job_stats():
    """Get job tracker statistics"""
    return job_tracker.get_stats()


@app.delete("/jobs/completed", tags=["meta"])
def clear_completed_jobs(older_than_hours: Optional[int] = None):
    """
    Clear completed jobs from history.

    Args:
        older_than_hours: Only clear jobs completed more than N hours ago
    """
    count = job_tracker.clear_completed(older_than_hours)
    return {"cleared": count, "older_than_hours": older_than_hours}


@app.get("/health", tags=["meta"])
async def health():
    """Comprehensive health check: API + TiTiler + Sentinel Hub + Redis + Disk"""
    import shutil
    from datetime import datetime, timezone

    health_checks = {}

    # 1. Check TiTiler
    titiler_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{TITILER_URL}/healthz", timeout=5.0)
            titiler_ok = resp.status_code == 200
            health_checks["titiler"] = {
                "url": TITILER_URL,
                "status": "healthy" if titiler_ok else "unhealthy",
                "response_code": resp.status_code
            }
    except Exception as e:
        logger.warning("TiTiler unavailable: %s", e)
        health_checks["titiler"] = {
            "url": TITILER_URL,
            "status": "unhealthy",
            "error": str(e)[:100]
        }

    # 2. Check Sentinel Hub API
    sh_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Just check if the endpoint is reachable (401 is expected without auth)
            resp = await client.get(settings.SH_STATISTICS_URL, timeout=5.0)
            sh_ok = resp.status_code in [200, 401, 403]  # 401/403 means API is up but needs auth
            health_checks["sentinel_hub"] = {
                "url": settings.SH_STATISTICS_URL,
                "status": "healthy" if sh_ok else "unhealthy",
                "response_code": resp.status_code
            }
    except Exception as e:
        logger.warning("Sentinel Hub API check failed: %s", e)
        health_checks["sentinel_hub"] = {
            "url": settings.SH_STATISTICS_URL,
            "status": "unhealthy",
            "error": str(e)[:100]
        }

    # 3. Check Redis/Celery (optional check, don't fail if not configured)
    redis_ok = None  # None means not checked/not applicable
    try:
        import redis
        r = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        r.ping()
        redis_ok = True
        health_checks["redis"] = {
            "url": settings.CELERY_BROKER_URL.split('@')[-1],  # Hide credentials
            "status": "healthy"
        }
    except ImportError:
        # Redis library not installed, skip check
        health_checks["redis"] = {"status": "not_configured"}
    except Exception as e:
        logger.warning("Redis check failed: %s", e)
        redis_ok = False
        health_checks["redis"] = {
            "status": "unhealthy",
            "error": str(e)[:100]
        }

    # 4. Check disk space
    disk_ok = True
    try:
        disk = shutil.disk_usage(CACHE_DIR)
        free_gb = disk.free / (1024**3)
        disk_ok = free_gb > 1.0
        health_checks["disk"] = {
            "status": "ok" if disk_ok else "low",
            "free_gb": round(free_gb, 2),
            "usage_pct": round((disk.used / disk.total) * 100, 1),
            "cache_dir": str(CACHE_DIR)
        }
    except Exception as e:
        disk_ok = False
        health_checks["disk"] = {"status": "error", "error": str(e)}

    # 5. Cache statistics with monitoring
    cache_ok = True
    try:
        cache_status = cache_monitor.get_cache_status()
        health_checks["cache"] = {
            "status": cache_status["status"],
            "total_files": cache_status["total"]["files"],
            "total_size_mb": cache_status["total"]["size_mb"],
            "usage_pct": cache_status["total"]["usage_pct"],
            "message": cache_status.get("message")
        }
        # Cache is not OK if critical
        if cache_status["status"] == "critical":
            cache_ok = False
    except Exception as e:
        cache_ok = False
        health_checks["cache"] = {"status": "error", "error": str(e)}

    # Determine overall health status
    critical_checks = [titiler_ok, sh_ok, disk_ok, cache_ok]
    # Redis is optional, only count if it was checked
    if redis_ok is not None:
        critical_checks.append(redis_ok)

    overall_status = "healthy" if all(critical_checks) else "degraded"

    return {
        "status": overall_status,
        "service": "Akmola Sentinel API",
        "version": "1.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": health_checks
    }

# ==========================
# Прокси к TiTiler
# ==========================
# заменяет существующий titiler_proxy в backend/main.py
from urllib.parse import urlparse, urlunparse, unquote

@app.api_route(
    "/titiler/{full_path:path}",
    methods=["GET", "POST", "OPTIONS", "HEAD", "PUT", "DELETE", "PATCH"]
)
async def titiler_proxy(full_path: str, request: Request):
    """
    Прокси к TiTiler с умной нормализацией `url` параметра:
      - если url указывает на /static/ndvi/<name> и файл существует в NDVI_CACHE_DIR ->
          используем file:///data/ndvi/<name>
      - иначе если url содержит localhost or 127.0.0.1 -> заменяем на host.docker.internal
      - иначе оставляем как есть
    Это избавляет от проблем с 'localhost' внутри контейнера и не требует хардкода.
    """
    # базовый адрес Titiler (взято из env в начале файла)
    base_titiler = TITILER_URL.rstrip("/")

    # копируем заголовки, убираем проблемные
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ["host", "connection", "content-length"]
    }

    # подготовим query params — mutable copy
    params = dict(request.query_params)

    # функция для safe filename extraction
    def extract_static_name(parsed: urlparse) -> str | None:
        # ожидаем путь вида /static/ndvi/<name> или /static/ndvi/<subpath>/<name>
        p = parsed.path or ""
        parts = p.split("/")
        # ищем последовательность ["", "static", "ndvi", "<name>..."]
        try:
            idx = parts.index("static")
            if parts[idx + 1] == "ndvi":
                # восстановим tail (имя файла может быть в несколько сегментов)
                tail = "/".join(parts[idx + 2:])
                return tail if tail else None
        except (ValueError, IndexError):
            return None
        return None

    # нормализуем param 'url' при наличии
    if "url" in params:
        raw_url = params["url"]
        try:
            parsed = urlparse(raw_url)
        except Exception:
            parsed = None

        if parsed and parsed.scheme in ("http", "https"):
            name = extract_static_name(parsed)
            if name:
                # декодируем имя из URL (вдруг были пробелы/encode)
                name_unq = unquote(name)
                # безопасная нормализация файла (только basename, чтобы избежать ../)
                safe_name = Path(name_unq).name

                # Validate filename - only allow alphanumeric, underscores, hyphens, and dots
                if not re.match(r'^[a-zA-Z0-9_\-\.]+$', safe_name):
                    logger.warning("Invalid filename rejected: %s", safe_name)
                    raise HTTPException(400, f"Invalid filename: {safe_name}")

                host_file = NDVI_CACHE_DIR / safe_name
                container_file = Path("/data/ndvi") / safe_name

                if host_file.exists():
                    # используем file:// внутри контейнера
                    params["url"] = f"file://{container_file.as_posix()}"
                    logger.debug("Titiler url rewritten -> file://%s", container_file)
                else:
                    # заменим localhost/127.0.0.1 на host.docker.internal чтобы GDAL внутри контейнера достал файл
                    netloc = parsed.netloc
                    # Extract hostname without port for validation
                    hostname = netloc.split(':')[0]
                    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "host.docker.internal"]
                    if hostname not in ALLOWED_HOSTS:
                        logger.warning("Invalid host rejected: %s", hostname)
                        raise HTTPException(400, f"Invalid host: {hostname}")

                    if netloc.startswith("localhost") or netloc.startswith("127.0.0.1"):
                        # сохранение порта если есть
                        new_netloc = netloc.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")
                        parsed = parsed._replace(netloc=new_netloc)
                        params["url"] = urlunparse(parsed)
                        logger.debug("Titiler url rewritten -> %s", params["url"])
                    # иначе оставляем как есть (внешние URL)
        # else: если схема — file:// или vsicurl или прочее — оставляем без изменений

    # собрать финальный url к Titiler
    url = f"{base_titiler}/{full_path.lstrip('/')}"

    # выполняем проксирование с учетом возможной замены params
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for attempt in range(2):
            try:
                resp = await client.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    params=params,
                    content=await request.body(),
                )
                # вернуть ответ Titiler как есть (копируем заголовки)
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    headers=dict(resp.headers),
                    media_type=resp.headers.get("content-type"),
                )
            except httpx.ConnectError as e:
                logger.error("TiTiler unavailable (attempt %d): %s", attempt + 1, e)
                if attempt == 1:
                    return Response(
                        content=b"TiTiler service is unavailable",
                        status_code=502,
                        media_type="text/plain"
                    )
            except Exception as e:
                logger.exception("Ошибка прокси к Titiler: %s", e)
                raise HTTPException(status_code=500, detail="Proxy error")


# ==========================
# Роутеры — БЕЗ ПОВТОРНОГО ПРЕФИКСА!
# ==========================
app.include_router(api_v1)          # ← УБРАН prefix="/api/v1"
app.include_router(pages_router)    # ← /ndvi, /biopar, /

# ==========================
# Startup
# ==========================
@app.on_event("startup")
async def startup_event():
    logger.info("=" * 72)
    logger.info("Akmola Sentinel API started")
    logger.info("Documentation: http://%s:%s/docs", HOST, PORT)
    logger.info("NDVI:         http://%s:%s/ndvi", HOST, PORT)
    logger.info("BIOPAR:       http://%s:%s/biopar", HOST, PORT)
    logger.info("TiTiler:      %s", TITILER_URL)

    def count_tifs(d: Path) -> int:
        return len(list(d.glob("*.tif"))) if d.exists() else 0

    logger.info("NDVI cache:     %s (files: %d)", NDVI_CACHE_DIR, count_tifs(NDVI_CACHE_DIR))
    logger.info("BIOPAR cache:   %s (files: %d)", BIOPAR_CACHE_DIR, count_tifs(BIOPAR_CACHE_DIR))
    logger.info("BIOPAR_SH:      %s (files: %d)", BIOPAR_SH_CACHE_DIR, count_tifs(BIOPAR_SH_CACHE_DIR))
    logger.info("=" * 72)


@app.on_event("shutdown")
async def shutdown_event():
    """Graceful shutdown handler"""
    logger.info("=" * 72)
    logger.info("Shutting down Akmola Sentinel API...")
    logger.info("Performing cleanup...")
    # Add any cleanup tasks here (close HTTP clients, flush caches, etc.)
    logger.info("Shutdown complete")
    logger.info("=" * 72)