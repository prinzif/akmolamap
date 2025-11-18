# backend/providers/gdacs.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

# Простая карта типов GDACS -> наши категории
GDACS_MAP = {
    "EQ": "earthquakes",
    "TC": "severeStorms",   # Tropical Cyclone -> Штормы
    "FL": "floods",
    "VO": "manmade",        # (можно вынести в volcanoes, если добавите категорию)
    "WF": "wildfires",
    "DR": "drought",
}

# API: список событий в периоде
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist"

def _within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= lon <= x2 and y1 <= lat <= y2

async def load_gdacs(
    start: Optional[str],
    end: Optional[str],
    bbox: Tuple[float, float, float, float],
) -> Dict[str, Any]:
    """
    Возвращает события GDACS в нашем общем контракте.
    """
    params = {}
    if start: params["fromdate"] = start
    if end:   params["todate"]   = end

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(GDACS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("GDACS fetch failed: %s", e)
        return {"events": [], "stats": {"total": 0, "in_region": 0, "nearby": 0, "by_category": {}, "sample_coordinates": []}}

    items = data.get("features", []) or data.get("events", []) or []
    events: List[Dict[str, Any]] = []
    stats = {"total": 0, "in_region": 0, "nearby": 0, "by_category": {}, "sample_coordinates": []}

    for it in items:
        stats["total"] += 1
        try:
            # GDACS может вернуться как FeatureCollection или список словарей — поддержим оба
            if isinstance(it, dict) and it.get("type") == "Feature":
                props = it.get("properties", {}) or {}
                geom = it.get("geometry", {}) or {}
                coords = (geom.get("coordinates") or [None, None])
                lon, lat = float(coords[0]), float(coords[1])
                evtype = str(props.get("eventtype") or props.get("eventtypecode") or "").upper()
                title  = props.get("eventname") or props.get("title") or "GDACS Event"
                date_iso = props.get("fromdate") or props.get("alertdate") or None
                link = props.get("url") or props.get("eventurl") or "https://www.gdacs.org/"

            else:
                # упрощённый фолбэк (некоторые ответы бывают с полями напрямую)
                props = it
                lon, lat = float(props.get("lon")), float(props.get("lat"))
                evtype  = str(props.get("eventtype") or "").upper()
                title   = props.get("eventname") or props.get("title") or "GDACS Event"
                date_iso = props.get("fromdate") or props.get("alertdate") or None
                link    = props.get("url") or "https://www.gdacs.org/"

            if not _within_bbox(lon, lat, bbox):
                continue

            cat = GDACS_MAP.get(evtype, "manmade")
            ev = {
                "id": f"gdacs_{props.get('eventid') or props.get('id') or f'{evtype}_{lon}_{lat}'}",
                "title": title,
                "description": props.get("description") or "",
                "link": link,
                "categories": [{"id": cat, "title": evtype}],
                "geometry": [{
                    "type": "Point",
                    "coordinates": [lon, lat],
                    "date": date_iso,
                }],
                "sources": [{"id": "GDACS"}],
                "closed": None,
            }
            events.append(ev)
            stats["in_region"] += 1
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

            if len(stats["sample_coordinates"]) < 10:
                stats["sample_coordinates"].append({
                    "title": title[:50],
                    "coords": [lon, lat],
                    "distance_deg": 0.0
                })

        except Exception:
            continue

    return {"events": events, "stats": stats}
