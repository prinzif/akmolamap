# ============================================
# backend/api/registry.py
# ============================================
from fastapi import APIRouter

from .routers import (
    eonet,
    sentinel,
    ndvi,
    biopar,
    settings as settings_router,
    tasks as tasks_router,
    pages,
    events_combined as combined_events,
)

# ================================
# API v1 — основной роутер
# ================================
api_v1 = APIRouter(prefix="/api/v1")

# Подключение API-роутеров
api_v1.include_router(eonet.router)                    # /api/v1/events
api_v1.include_router(combined_events.router)          # /api/v1/events/combined
api_v1.include_router(sentinel.router)                 # /api/v1/sentinel/...
api_v1.include_router(ndvi.router)                     # /api/v1/ndvi/...
api_v1.include_router(biopar.router)                   # /api/v1/biopar/...
api_v1.include_router(settings_router.router)          # /api/v1/settings/...
api_v1.include_router(tasks_router.router)             # /api/v1/tasks/...

# ================================
# HTML-страницы
# ================================
pages_router = APIRouter()
pages_router.include_router(pages.router, tags=["pages"])

# ================================
# Экспорт
# ================================
__all__ = ["api_v1", "pages_router"]