# backend/api/routers/settings.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple

from fastapi import APIRouter
from pydantic import BaseModel

from backend.settings import settings
from backend.sentinel import check_cdse_health

router = APIRouter(prefix="/settings", tags=["System"])


def _mask(s: str | None, show: int = 4) -> str | None:
    if not s:
        return s
    return s[:show] + "…" if len(s) > show else "…" * len(s)


class SettingsPublic(BaseModel):
    # Веб-сервисы
    cdse_api_url: str
    cdse_token_url: str | None = None
    eonet_url: str

    # География/кэш
    bbox_akmola: Tuple[float, float, float, float]
    cache_ttl_events: int
    cache_ttl_search: int

    # Файловая система
    data_dir: str
    cog_dir: str
    tmp_dir: str

    # Celery/логирование
    celery_broker_url: str | None = None
    celery_backend_url: str | None = None
    log_level: str | None = None

    # Безопасность (без утечек секретов)
    has_cdse_credentials: bool
    cdse_client_id_masked: str | None = None


@router.get("", response_model=SettingsPublic)
def get_settings_public():
    """
    Безопасный срез конфигурации (без секретов).
    Подходит для фронта/диагностики.
    """
    cdse_client_id = getattr(settings, "CDSE_CLIENT_ID", None)
    cdse_client_secret = getattr(settings, "CDSE_CLIENT_SECRET", None)
    cdse_username = getattr(settings, "CDSE_USERNAME", None)
    cdse_password = getattr(settings, "CDSE_PASSWORD", None)

    has_cdse_credentials = bool(
        (cdse_client_id and cdse_client_secret) or (cdse_username and cdse_password)
    )

    return SettingsPublic(
        cdse_api_url=getattr(settings, "CDSE_API_URL", ""),
        cdse_token_url=getattr(settings, "CDSE_TOKEN_URL", None),
        eonet_url=getattr(settings, "EONET_URL", ""),

        bbox_akmola=getattr(settings, "BBOX_AKMOLA", (65.0,49.5,76.0,54.0)),
        cache_ttl_events=getattr(settings, "CACHE_TTL_EVENTS", 600),
        cache_ttl_search=getattr(settings, "CACHE_TTL_SEARCH", 300),

        data_dir=str(getattr(settings, "DATA_DIR", Path("./data"))),
        cog_dir=str(getattr(settings, "COG_DIR", Path("./data/cog"))),
        tmp_dir=str(getattr(settings, "TMP_DIR", Path("./data/tmp"))),

        celery_broker_url=getattr(settings, "CELERY_BROKER_URL", None),
        celery_backend_url=getattr(settings, "CELERY_BACKEND_URL", None),
        log_level=getattr(settings, "LOG_LEVEL", None),

        has_cdse_credentials=has_cdse_credentials,
        cdse_client_id_masked=_mask(cdse_client_id),
    )


@router.get("/paths")
def paths_status():
    """
    Диагностика ФС: существование/права директорий.
    """
    def probe_dir(p: Path) -> Dict[str, object]:
        try:
            return {
                "path": str(p),
                "exists": p.exists(),
                "is_dir": p.is_dir(),
                "readable": os.access(p, os.R_OK),
                "writable": os.access(p, os.W_OK),
            }
        except Exception:
            return {
                "path": str(p),
                "exists": False,
                "is_dir": False,
                "readable": False,
                "writable": False,
            }

    data_dir = Path(getattr(settings, "DATA_DIR", Path("./data")))
    cog_dir = Path(getattr(settings, "COG_DIR", data_dir / "cog"))
    tmp_dir = Path(getattr(settings, "TMP_DIR", data_dir / "tmp"))

    return {
        "data_dir": probe_dir(data_dir),
        "cog_dir": probe_dir(cog_dir),
        "tmp_dir": probe_dir(tmp_dir),
    }


@router.get("/bbox")
def bbox():
    """
    Вернуть bbox региона и GeoJSON-полигон (WGS84).
    """
    x1, y1, x2, y2 = getattr(settings, "BBOX_AKMOLA", (65.0,49.5,76.0,54.0))
    return {
        "bbox": (x1, y1, x2, y2),
        "geojson": {
            "type": "Polygon",
            "coordinates": [[
                [x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]
            ]],
        },
    }


@router.get("/health")
def health():
    """
    Системный health:
    - доступ к директориям
    - проверка CDSE (на уровне HTTP токена/пингуемого эндпоинта)
    - наличие кредов
    """
    data_dir = Path(getattr(settings, "DATA_DIR", Path("./data")))
    cog_dir = Path(getattr(settings, "COG_DIR", data_dir / "cog"))
    tmp_dir = Path(getattr(settings, "TMP_DIR", data_dir / "tmp"))

    paths_ok = all([
        data_dir.exists(),
        cog_dir.exists(),
        tmp_dir.exists(),
    ])

    # check_cdse_health() может зависеть от токена/кредов — оставляем как есть
    cdse_ok = bool(check_cdse_health())

    has_cdse_credentials = bool(
        (getattr(settings, "CDSE_CLIENT_ID", None) and getattr(settings, "CDSE_CLIENT_SECRET", None))
        or (getattr(settings, "CDSE_USERNAME", None) and getattr(settings, "CDSE_PASSWORD", None))
    )

    return {
        "ok": bool(cdse_ok and paths_ok),
        "cdse_ok": cdse_ok,
        "paths_ok": paths_ok,
        "has_cdse_credentials": has_cdse_credentials,
    }
