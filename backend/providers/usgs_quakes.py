# backend/providers/usgs_quakes.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import datetime as dt
import logging

import httpx

logger = logging.getLogger(__name__)

USGS_FDSN_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

__all__ = ["fetch_quakes_bbox"]

def _iso_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    # ожидаем 'YYYY-MM-DD'
    try:
        # вернём ISO-дату в полночь UTC для фронта (или можно время события на точке)
        d = dt.datetime.fromisoformat(s)
        return d.replace(tzinfo=dt.timezone.utc).isoformat()
    except Exception:
        return None

async def fetch_quakes_bbox(
    start: Optional[str],
    end: Optional[str],
    bbox: Tuple[float, float, float, float],
    min_magnitude: float = 2.5,
    limit: int = 2000,
) -> Dict[str, Any]:
    """
    Получить землетрясения USGS, отфильтрованные по bbox и датам.
    Возвращает формат, совместимый с фронтом:
      {"events":[...], "stats":{...}}
    """
    minlon, minlat, maxlon, maxlat = bbox

    params = {
        "format": "geojson",
        "starttime": start if start else None,
        "endtime": end if end else None,
        "minlatitude": minlat,
        "minlongitude": minlon,
        "maxlatitude": maxlat,
        "maxlongitude": maxlon,
        "minmagnitude": min_magnitude,
        "orderby": "time-asc",
        "limit": limit,
    }
    # удалим None, чтобы не засорять URL
    params = {k: v for k, v in params.items() if v is not None}

    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
        resp = await client.get(USGS_FDSN_URL, params=params, headers={"User-Agent": "akmola-monitor/1.0"})
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", []) or []

    events_out: List[Dict[str, Any]] = []
    stats = {
        "total": len(features),
        "in_region": 0,   # т.к. уже отфильтровано по bbox на стороне API, считаем все как in_region
        "nearby": 0,
        "by_category": {},
        "sample_coordinates": [],
    }

    for i, feat in enumerate(features):
        geom = feat.get("geometry") or {}
        props = feat.get("properties") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue

        lon, lat = float(coords[0]), float(coords[1])
        # время события от USGS (миллисекунды от эпохи)
        t_ms = props.get("time")
        date_iso = None
        if isinstance(t_ms, (int, float)):
            date_iso = dt.datetime.utcfromtimestamp(t_ms / 1000.0).replace(tzinfo=dt.timezone.utc).isoformat()

        title = props.get("title") or f"M{props.get('mag', '?')} earthquake"
        url = props.get("url") or ""
        mag = props.get("mag")

        event = {
            "id": str(feat.get("id") or f"usgs_{i}"),
            "title": title,
            "description": f"Magnitude: {mag}" if mag is not None else "",
            "link": url,
            "categories": [{"id": "earthquakes", "title": "Earthquakes"}],
            "geometry": [{
                "type": "Point",
                "coordinates": [lon, lat],
                "date": date_iso or _iso_date(start) or _iso_date(end),
            }],
            "sources": [{"id": "USGS"}],
            "closed": None,
        }
        events_out.append(event)

        # учёт статистики
        stats["in_region"] += 1
        stats["by_category"]["earthquakes"] = stats["by_category"].get("earthquakes", 0) + 1

        if len(stats["sample_coordinates"]) < 10:
            stats["sample_coordinates"].append({
                "title": title[:50],
                "coords": [lon, lat],
                "distance_deg": 0.0,  # не считаем для уже отсечённого bbox
            })

    return {"events": events_out, "stats": stats}
