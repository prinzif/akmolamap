# backend/providers/gdacs_rss.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
import datetime as dt

import httpx
import feedparser

# Официальная глобальная лента GDACS (RSS/Atom). Есть и типовые фиды, но глобальная — простейшая.
GDACS_RSS_URL = "https://www.gdacs.org/xml/rss.xml"

# Маппинг типов событий GDACS -> наши категории (синхронизировано с фронтом)
GDACS_TO_CATEGORY = {
    "FL": "floods",          # Flood
    "TC": "severeStorms",    # Tropical Cyclone / Storm
    "WF": "wildfires",       # WildFire
    "EQ": "earthquakes",     # EarthQuake
    "VO": "manmade",         # Volcano → у нас нет отдельной категории, кладём в manmade
    "DR": "drought",         # Drought
    # Остальные редкие типы можно также маппить в manmade
}

def _within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= lon <= x2 and y1 <= lat <= y2

def _parse_time(s: Optional[str]) -> Optional[str]:
    """Приводим pubDate в ISO (UTC) для фронта, если есть."""
    if not s:
        return None
    try:
        # feedparser уже распарсит в struct_time entry.published_parsed
        return dt.datetime(*s[:6], tzinfo=dt.timezone.utc).isoformat()
    except Exception:
        return None

def _to_category(entry: Any) -> str:
    # В RSS у GDACS есть собственные namespace-поля, но feedparser не всегда даёт их как отдельные ключи.
    # Поэтому используем эвристику: сначала ищем code в тегах, потом — по словам в заголовке.
    # Теги: entry.tags -> [{'term': 'Flood', 'scheme': ...}, ...]
    try:
        for t in entry.get("tags", []):
            term = (t.get("term") or "").lower()
            if "flood" in term: return "floods"
            if "cyclone" in term or "storm" in term or "hurricane" in term or "typhoon" in term: return "severeStorms"
            if "wildfire" in term or "fire" in term: return "wildfires"
            if "earthquake" in term: return "earthquakes"
            if "volcano" in term: return "manmade"
            if "drought" in term: return "drought"
    except Exception:
        pass

    title = (entry.get("title") or "").lower()
    if "flood" in title: return "floods"
    if any(w in title for w in ["cyclone", "storm", "hurricane", "typhoon"]): return "severeStorms"
    if any(w in title for w in ["wildfire", "fire"]): return "wildfires"
    if "earthquake" in title: return "earthquakes"
    if "volcano" in title: return "manmade"
    if "drought" in title: return "drought"
    return "manmade"

async def fetch_gdacs_rss(
    start: Optional[str],
    end: Optional[str],
    bbox: Tuple[float, float, float, float],
    limit: int = 500,
) -> Dict[str, Any]:
    """
    Возвращает события из GDACS RSS, отфильтрованные по датам и bbox.
    Выходной формат совместим с фронтом: {"events": [...], "stats": {...}}
    """
    # Политика таймаутов/ретраев простая — RSS лёгкий
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.get(GDACS_RSS_URL, headers={"User-Agent": "akmola-monitor/1.0"})
        resp.raise_for_status()
        feed_text = resp.text

    parsed = feedparser.parse(feed_text)
    entries = parsed.get("entries", [])[:limit]

    # Дата-фильтр
    start_dt = dt.datetime.fromisoformat(start) if start else None
    end_dt = dt.datetime.fromisoformat(end) if end else None

    events_out: List[Dict[str, Any]] = []
    stats = {
        "total": 0,
        "in_region": 0,
        "nearby": 0,  # для RSS «nearby» не считаем, оставляем 0
        "by_category": {},
        "sample_coordinates": [],
    }

    for e in entries:
        stats["total"] += 1

        # Время публикации / обновления
        pub_parsed = e.get("published_parsed") or e.get("updated_parsed")
        if pub_parsed and (start_dt or end_dt):
            pub = dt.datetime(*pub_parsed[:6], tzinfo=dt.timezone.utc)
            if start_dt and pub < start_dt.replace(tzinfo=dt.timezone.utc):
                continue
            if end_dt and pub > end_dt.replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1):
                continue

        # Координаты
        try:
            lat = float(e.get("geo_lat")) if e.get("geo_lat") is not None else None
            lon = float(e.get("geo_long")) if e.get("geo_long") is not None else None
        except Exception:
            lat = lon = None

        in_bbox = False
        geometry = []
        if lat is not None and lon is not None and _within_bbox(lon, lat, bbox):
            in_bbox = True
            geometry = [{
                "type": "Point",
                "coordinates": [lon, lat],
                "date": _parse_time(pub_parsed)  # для попапа
            }]

        category_id = _to_category(e)
        if in_bbox and geometry:
            stats["in_region"] += 1
            stats["by_category"][category_id] = stats["by_category"].get(category_id, 0) + 1

            events_out.append({
                "id": e.get("id") or e.get("link") or f"gdacs_{stats['total']}",
                "title": e.get("title") or "GDACS Event",
                "description": (e.get("summary") or "").strip(),
                "link": e.get("link") or "",
                "categories": [{"id": category_id, "title": category_id}],
                "geometry": geometry,
                "sources": [{"id": "GDACS"}],
                "closed": None,
            })

        # соберём немного примеров координат для логов
        if (lat is not None and lon is not None) and len(stats["sample_coordinates"]) < 10:
            stats["sample_coordinates"].append({
                "title": (e.get("title") or "")[:50],
                "coords": [lon, lat],
                "distance_deg": 0.0,  # не считаем для RSS
            })

    return {"events": events_out, "stats": stats}
