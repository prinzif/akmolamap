# backend/eonet.py
"""
Загрузка и фильтрация событий NASA EONET для заданного bbox (по умолчанию — Акмолинская область).

Контракт ответа (ожидается фронтендом):
{
    "events": [ ... ],
    "stats": {
        "total": int,
        "in_region": int,
        "nearby": int,
        "by_category": { "<id>": int, ... },
        "sample_coordinates": [
            { "title": str, "coords": [lon, lat], "distance_deg": float }, ...
        ]
    },
    "cached": bool,
    "debug": bool (optional),
    "message": str (optional)
}
"""

from __future__ import annotations

import time
import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx

from backend.settings import settings

logger = logging.getLogger(__name__)

__all__ = ["load_events"]

# ---- Кэш для событий ---------------------------------------------------------
_cache_events: Dict[str, Any] = {"ts": 0.0, "data": None, "key": ""}

# ---- Маппинг категорий EONET -> наши ID (синхронизирован с фронтендом) -------
CATEGORY_MAP: Dict[str, str] = {
    "Drought": "drought",
    "Dust and Haze": "dustHaze",
    "Earthquakes": "earthquakes",
    "Floods": "floods",
    "Landslides": "landslides",
    "Manmade": "manmade",
    "Sea and Lake Ice": "seaLakeIce",
    "Severe Storms": "severeStorms",
    "Snow": "snow",
    "Temperature Extremes": "tempExtremes",
    "Water Color": "waterColor",
    "Wildfires": "wildfires",
    # Отдельной категории volcanoes на фронте нет — отправляем в manmade
    "Volcanoes": "manmade",
}

# ---- Конфигурация ------------------------------------------------------------
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
BBOX_AKMOLA: Tuple[float, float, float, float] = (65.0, 49.5, 76.0, 54.0)  # minLon, minLat, maxLon, maxLat
CACHE_TTL_EVENTS = 300  # 5 минут


# ---- Утилиты -----------------------------------------------------------------
def _parse_bbox(bbox_str: str) -> Optional[Tuple[float, float, float, float]]:
    """
    'minLon,minLat,maxLon,maxLat' -> (minLon, minLat, maxLon, maxLat) с нормализацией.
    """
    try:
        x1, y1, x2, y2 = [float(x) for x in bbox_str.split(",")]
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    except Exception:
        return None


def _within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= lon <= x2 and y1 <= lat <= y2


def _safe_lonlat(coords: Any) -> Optional[Tuple[float, float]]:
    """Безопасно извлекает lon/lat из массива координат, проверяет диапазоны."""
    try:
        lon, lat = float(coords[0]), float(coords[1])
    except Exception:
        return None
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        return None
    return lon, lat


# ---- Основная функция --------------------------------------------------------
async def load_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    status: str = "open",
    bbox_str: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Load NASA EONET events and filter by bbox with pagination support.
    Parameters:
      - start, end: 'YYYY-MM-DD' (optional)
      - status: 'open' | 'closed' | 'all'
      - bbox_str: 'minLon,minLat,maxLon,maxLat' (optional; defaults to BBOX_AKMOLA)
      - limit: Maximum number of events to return (default: 100)
      - offset: Number of events to skip for pagination (default: 0)
    """
    # Эффективный bbox (из запроса или дефолтный)
    bbox = _parse_bbox(bbox_str) if bbox_str else BBOX_AKMOLA
    if bbox is None:
        bbox = BBOX_AKMOLA
    x1, y1, x2, y2 = bbox
    center_lon = (x1 + x2) / 2.0
    center_lat = (y1 + y2) / 2.0

    logger.info("=== EONET REQUEST ===")
    logger.info("Date range: %s to %s, status: %s", start or "no limit", end or "no limit", status)
    logger.info("BBOX effective: %s", bbox)

    # ---- Кэш ----------------------------------------------------------------
    cache_key = f"{start}_{end}_{status}_{bbox}"
    if _cache_events.get("key") == cache_key and _cache_events.get("data"):
        age = time.time() - float(_cache_events.get("ts", 0.0))
        if age < CACHE_TTL_EVENTS:
            logger.debug("Returning cached EONET data (age=%.1fs)", age)
            cached_payload = dict(_cache_events["data"])
            cached_payload["cached"] = True
            return cached_payload

    # ---- Запрос к EONET -----------------------------------------------------
    params: Dict[str, Any] = {
        "status": status,
        "limit": 1500,
        # Просим API сразу отфильтровать по bbox (если он задан/нормализован)
        "bbox": f"{x1},{y1},{x2},{y2}",
    }
    if start:
        params["start"] = start
    if end:
        params["end"] = end

    logger.info("Requesting EONET API: %s", EONET_URL)
    logger.info("Parameters: %s", params)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            # 1) Запрос С bbox
            resp = await client.get(EONET_URL, params=params)
            resp.raise_for_status()
            try:
                raw_data = resp.json()
                logger.debug("EONET raw keys: %s", list(raw_data.keys()))
                logger.debug("First event sample: %s", str(raw_data.get("events", [])[:1])[:500])

            except Exception:
                body_preview = resp.text[:800]
                logger.exception("EONET JSON parse failed. Preview:\n%s", body_preview)
                return {
                    "events": [],
                    "stats": _empty_stats(),
                    "pagination": {"total": 0, "limit": limit, "offset": offset, "returned": 0},
                    "error": "bad_json",
                    "cached": False
                }

            total_events = len(raw_data.get("events", []))
            logger.info("EONET response (with bbox): %d total events", total_events)

            # 2) Fallback: if bbox returns nothing and DEBUG is on - try without bbox
            if settings.EONET_DEBUG and total_events == 0:
                logger.warning("EONET returned 0 events with bbox; trying fallback without bbox")
                params_no_bbox = dict(params)
                params_no_bbox.pop("bbox", None)
                resp2 = await client.get(EONET_URL, params=params_no_bbox)
                resp2.raise_for_status()
                try:
                    raw_data = resp2.json()
                except Exception:
                    body_preview = resp2.text[:800]
                    logger.exception("EONET JSON parse failed (no-bbox). Preview:\n%s", body_preview)
                    return {
                        "events": [],
                        "stats": _empty_stats(),
                        "pagination": {"total": 0, "limit": limit, "offset": offset, "returned": 0},
                        "error": "bad_json",
                        "cached": False
                    }
                total_events = len(raw_data.get("events", []))
                logger.info("EONET response (NO bbox fallback): %d total events", total_events)

    except Exception as e:
        logger.error("EONET API error: %s", e)
        return {
            "events": [],
            "stats": _empty_stats(),
            "pagination": {"total": 0, "limit": limit, "offset": offset, "returned": 0},
            "error": str(e),
            "cached": False,
        }


    # ---- Фильтрация по региону ----------------------------------------------
    events_out: List[Dict[str, Any]] = []
    events_debug: List[Dict[str, Any]] = []

    stats: Dict[str, Any] = {
        "total": 0,
        "in_region": 0,
        "nearby": 0,
        "by_category": {},
        "sample_coordinates": [],
    }

    for event in raw_data.get("events", []):
        stats["total"] += 1

        categories = event.get("categories", [])
        if not categories:
            continue

        category_title = categories[0].get("title", "Unknown")
        mapped_category = CATEGORY_MAP.get(category_title, "manmade")

        event_geometries: List[Dict[str, Any]] = []
        event_in_region = False
        min_distance_deg = float("inf")
        sample_coords: Optional[Tuple[float, float]] = None  # (lon, lat)

        for geom in event.get("geometry", []):
            geo_type = (geom.get("type") or "").strip()

            if geo_type == "Point":
                sl = _safe_lonlat(geom.get("coordinates"))
                if not sl:
                    continue
                lon, lat = sl

                # «Расстояние» от центра bbox в градусах (для near-by логики/логирования)
                dist_deg = ((lon - center_lon) ** 2 + (lat - center_lat) ** 2) ** 0.5
                if dist_deg < min_distance_deg:
                    min_distance_deg = dist_deg
                    sample_coords = (lon, lat)

                # Внутри bbox — берём
                if _within_bbox(lon, lat, bbox):
                    event_geometries.append({
                        "type": "Point",
                        "coordinates": [lon, lat],
                        "date": geom.get("date"),
                    })
                    event_in_region = True
                # Иначе считаем «nearby» (~500 км ≈ 4.5°) — чисто для статистики
                elif dist_deg < 4.5:
                    stats["nearby"] += 1

            elif geo_type in ("Polygon", "LineString"):
                # Для полигонов/линий включаем геометрию как есть.
                event_geometries.append(geom)
                event_in_region = True

        # Сэмплы для отладки
        if sample_coords and len(stats["sample_coordinates"]) < 10:
            lon, lat = sample_coords
            stats["sample_coordinates"].append({
                "title": (event.get("title") or "")[:50],
                "coords": [lon, lat],
                "distance_deg": round(min_distance_deg, 2),
            })

        # Формируем событие
        if event_in_region and event_geometries:
            stats["in_region"] += 1
            stats["by_category"][mapped_category] = stats["by_category"].get(mapped_category, 0) + 1

            events_out.append({
                "id": event.get("id"),
                "title": event.get("title") or "Untitled Event",
                "description": event.get("description", ""),
                "link": event.get("link", ""),
                "categories": [{
                    "id": mapped_category,
                    "title": category_title,
                }],
                "geometry": event_geometries,
                "sources": event.get("sources", []),
                "closed": event.get("closed"),
            })
        # DEBUG: ближайшие (если внутри региона пусто)
        elif settings.EONET_DEBUG and (min_distance_deg < 7.5) and len(events_debug) < 8:
            # 7.5° ~ 830 км — чтобы всегда что-то вернулось для визуальной проверки цепочки
            approx_km = int(min_distance_deg * 111)
            events_debug.append({
                "id": f"debug_{len(events_debug)}",
                "title": f"[~{approx_km}km] {event.get('title', 'Event')}",
                "categories": [{
                    "id": mapped_category,
                    "title": category_title,
                }],
                "geometry": (event.get("geometry") or [])[:1],
                "sources": [{"id": "EONET"}],
                "_distance_deg": round(min_distance_deg, 2),
            })

    logger.info("=== FILTERING COMPLETE ===")
    logger.info("Total: %d, In region: %d, Nearby: %d", stats["total"], stats["in_region"], stats["nearby"])
    logger.info("Categories: %s", stats["by_category"])

    # If nothing in region — return nearest events in DEBUG mode
    if stats["in_region"] == 0 and settings.EONET_DEBUG and events_debug:
        logger.warning("NO EVENTS IN BBOX; returning %d nearest (DEBUG)", len(events_debug))
        # Apply pagination to debug events
        total_debug = len(events_debug)
        paginated_debug = events_debug[offset:offset + limit]

        payload = {
            "events": paginated_debug,
            "stats": stats,
            "pagination": {
                "total": total_debug,
                "limit": limit,
                "offset": offset,
                "returned": len(paginated_debug),
            },
            "debug": True,
            "message": f"No events in region. Showing {len(paginated_debug)} nearest events for debugging.",
            "cached": False,
        }
        _cache_events.update({"data": payload, "ts": time.time(), "key": cache_key})
        return payload

    # Apply pagination to filtered events
    total_events = len(events_out)
    paginated_events = events_out[offset:offset + limit]

    # Result with pagination metadata
    payload = {
        "events": paginated_events,
        "stats": stats,
        "pagination": {
            "total": total_events,
            "limit": limit,
            "offset": offset,
            "returned": len(paginated_events),
        },
        "cached": False,
    }
    _cache_events.update({"data": payload, "ts": time.time(), "key": cache_key})
    return payload


def _empty_stats() -> Dict[str, Any]:
    """Пустая статистика (на случай ошибок сети/JSON)."""
    return {
        "total": 0,
        "in_region": 0,
        "nearby": 0,
        "by_category": {},
        "sample_coordinates": [],
    }
