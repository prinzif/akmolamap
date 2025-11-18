# backend/events_combined.py
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.eonet import load_events as load_eonet
from backend.providers.usgs_quakes import fetch_quakes_bbox
from backend.providers.gdacs import load_gdacs          # ← используем существующую функцию
from backend.providers.firms import fetch_firms_bbox

logger = logging.getLogger(__name__)

def _parse_bbox(bbox_str: Optional[str]) -> Tuple[float, float, float, float]:
    """'minLon,minLat,maxLon,maxLat' -> нормализованный bbox."""
    if not bbox_str:
        return (65.0, 49.5, 76.0, 54.0)
    vals = [float(x) for x in bbox_str.split(",")]
    x1, y1, x2, y2 = vals[0], vals[1], vals[2], vals[3]
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

async def load_events_combined(
    start: Optional[str] = None,
    end: Optional[str] = None,
    status: str = "open",
    bbox_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Комбинирует события из нескольких источников:
      - NASA EONET
      - USGS Earthquakes
      - GDACS (RSS/API через наш провайдер)
      - FIRMS (активные пожары)
    """
    bbox = _parse_bbox(bbox_str)
    logger.info("[combined] bbox=%s, dates=%s..%s", bbox, start, end)

    tasks = [
        load_eonet(start, end, status, bbox_str),                 # EONET
        fetch_quakes_bbox(bbox, start, end, min_magnitude=2.5,    # USGS
                          limit=2000),
        load_gdacs(bbox, start, end),                             # GDACS (как у тебя в провайдере)
        fetch_firms_bbox(bbox, min_confidence=0,                  # FIRMS
                         limit_points=1000),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    events: List[Dict[str, Any]] = []
    stats_acc: Dict[str, int] = {"total": 0, "in_region": 0, "nearby": 0}
    by_category: Dict[str, int] = {}

    for res in results:
        if isinstance(res, Exception):
            logger.warning("[combined] provider failed: %s", res)
            continue

        provider_events = (res or {}).get("events") or []
        provider_stats = (res or {}).get("stats") or {}

        events.extend(provider_events)
        stats_acc["total"] += int(provider_stats.get("total", 0))
        stats_acc["in_region"] += int(provider_stats.get("in_region", 0))
        stats_acc["nearby"] += int(provider_stats.get("nearby", 0))

        bc = provider_stats.get("by_category") or {}
        for k, v in bc.items():
            by_category[k] = by_category.get(k, 0) + int(v)

    # Если провайдеры не вернули разбиение — считаем по событиям
    if not by_category:
        for ev in events:
            cid = (ev.get("categories") or [{}])[0].get("id", "manmade")
            by_category[cid] = by_category.get(cid, 0) + 1

    return {
        "events": events,
        "stats": {
            "total": stats_acc["total"],
            "in_region": stats_acc["in_region"],
            "nearby": stats_acc["nearby"],
            "by_category": by_category,
            "sample_coordinates": [],
        },
        "cached": False,
    }
