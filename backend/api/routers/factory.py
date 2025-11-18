"""
Фабрика для однотипных "растительных" модулей (NDVI, BIOPAR, EVI и т.п.).
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from backend.api.deps import BBox, Date


def build_vegetation_router(
    *,
    name: str,
    html_filename: str,
    get_zones_fn: Callable[[List[float]], List[Dict[str, Any]]],
    statistics_fn: Callable[..., Dict[str, Any]],
    report_fn: Callable[..., Dict[str, Any]],
    tags: Optional[List[str]] = None,
    extra_query_params_desc: Optional[Dict[str, str]] = None,
) -> APIRouter:
    """
    Создаёт APIRouter для модуля мониторинга растительности.
    """
    router = APIRouter(prefix=f"/{name}", tags=tags or [name.upper()])

    # Путь к фронтенду
    FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
    PAGE = FRONTEND_DIR / html_filename

    @router.get("", response_class=FileResponse)
    def page():
        """Отдаёт страницу мониторинга (HTML)."""
        if not PAGE.exists():
            raise HTTPException(404, f"{html_filename} not found")
        return FileResponse(str(PAGE), media_type="text/html")

    @router.get("/zones")
    def zones(bbox: List[float] = Depends(BBox)):  # ← Исправлено!
        """Список с/х зон в пределах bbox."""
        return {"zones": get_zones_fn(bbox)}

    @router.get("/statistics")
    def statistics(
        bbox: List[float] = Depends(BBox),  # ← Исправлено!
        start: str = Depends(Date("start")),  # ← Исправлено!
        end: str = Depends(Date("end")),  # ← Исправлено!
        **kwargs: Any,
    ):
        """
        Временной ряд + сводная статистика за период [start, end] в пределах bbox.
        """
        if start > end:
            raise HTTPException(400, "start must be <= end")

        return statistics_fn(bbox, start, end, **kwargs)

    @router.get("/report")
    def report(
        bbox: List[float] = Depends(BBox),  # ← Исправлено!
        date: str = Depends(Date("date")),  # ← Исправлено!
        **kwargs: Any,
    ):
        """
        Сводный отчёт (обычно за последние 30 дней до date).
        """
        return report_fn(bbox, date, **kwargs)

    return router