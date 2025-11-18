# backend/providers/firms.py

from __future__ import annotations
import csv
import io
import math
from typing import Any, Dict, List, Optional, Tuple
import httpx
from datetime import datetime, timezone

# Публичные CSV из FIRMS (без ключа). Берём VIIRS NRT (обычно больше точек), далее MODIS как резерв.
CANDIDATE_URLS = [
    # VIIRS 375m, last 24h (common public CSV)
    "https://firms.modaps.eosdis.nasa.gov/active_fire/viirs/csv/VNP14IMGTDL_NRT_Global_24h.csv",
    # VIIRS 375m, last 48h
    "https://firms.modaps.eosdis.nasa.gov/active_fire/viirs/csv/VNP14IMGTDL_NRT_Global_48h.csv",
    # MODIS C6 1km, last 24h
    "https://firms.modaps.eosdis.nasa.gov/active_fire/c6/csv/MODIS_C6_Global_24h.csv",
    # MODIS C6 1km, last 48h
    "https://firms.modaps.eosdis.nasa.gov/active_fire/c6/csv/MODIS_C6_Global_48h.csv",
]

def _within_bbox(lon: float, lat: float, bbox: Tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = bbox
    return x1 <= lon <= x2 and y1 <= lat <= y2

def _safe_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None

def _parse_acq_datetime(acq_date: str, acq_time: str) -> Optional[str]:
    # acq_date: 'YYYY-MM-DD' или 'YYYY/MM/DD', acq_time: 'HHMM'
    try:
        acq_date = acq_date.replace("/", "-")
        hh = int(acq_time[:2]) if acq_time and len(acq_time) >= 2 else 0
        mm = int(acq_time[2:4]) if acq_time and len(acq_time) >= 4 else 0
        dt = datetime(int(acq_date[0:4]), int(acq_date[5:7]), int(acq_date[8:10]), hh, mm, tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except Exception:
        return None

async def _download_first_available() -> Optional[str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for url in CANDIDATE_URLS:
            try:
                r = await client.get(url)
                if r.status_code == 200 and (r.headers.get("content-type","text/plain")).startswith(("text", "application")):
                    text = r.text.strip()
                    # Бывает, что приходит HTML-заглушка — проверим наличие CSV-заголовков
                    if "latitude" in text.splitlines()[0].lower():
                        return text
            except Exception:
                pass
    return None

async def fetch_firms_bbox(
    bbox: Tuple[float, float, float, float],
    min_confidence: int = 0,   # 0..100 (иногда строковые 'nominal/low', обработаем)
    limit_points: int = 1000,  # ограничим, чтобы не завалить фронт
) -> Dict[str, Any]:
    """
    Возвращает один "событийный" объект категории 'wildfires' с множеством Point-геометрий (FIRMS detections),
    отфильтрованных по bbox. Источник: FIRMS CSV (без API-ключа).
    """
    csv_text = await _download_first_available()
    if not csv_text:
        return {"events": [], "stats": {"total": 0, "in_region": 0}}

    detections: List[Dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        lat = _safe_float(row.get("latitude"))
        lon = _safe_float(row.get("longitude"))
        if lat is None or lon is None:
            continue
        if not _within_bbox(lon, lat, bbox):
            continue

        # confidence: может быть числом или строкой ('low/nominal/high')
        conf_raw = row.get("confidence", "")
        conf_val: Optional[int] = None
        if isinstance(conf_raw, str):
            if conf_raw.isdigit():
                conf_val = int(conf_raw)
            else:
                m = conf_raw.strip().lower()
                conf_val = {"low": 33, "nominal": 66, "high": 90}.get(m, 50)
        else:
            try:
                conf_val = int(conf_raw)
            except Exception:
                conf_val = 0

        if conf_val is not None and conf_val < min_confidence:
            continue

        acq_date = row.get("acq_date") or ""
        acq_time = row.get("acq_time") or ""
        iso_date = _parse_acq_datetime(acq_date, acq_time) or None

        detections.append({
            "type": "Point",
            "coordinates": [lon, lat],
            "date": iso_date,
            "confidence": conf_val,
            "sat": row.get("satellite") or row.get("sensor") or "VIIRS/MODIS",
            "bright_ti4": _safe_float(row.get("bright_ti4")),
            "bright_ti5": _safe_float(row.get("bright_ti5")),
            "frp": _safe_float(row.get("frp")),
        })

    if not detections:
        return {"events": [], "stats": {"total": 0, "in_region": 0}}

    # Сортировка по уверенности/яркости и ограничение количества
    detections.sort(key=lambda d: (d.get("confidence") or 0, d.get("frp") or 0.0), reverse=True)
    detections = detections[:limit_points]

    event = {
        "id": "firms_wildfires",
        "title": f"Активные пожары (FIRMS): {len(detections)} точек",
        "description": "Детекции тепловых аномалий по данным NASA FIRMS (24–48 ч).",
        "link": "https://firms.modaps.eosdis.nasa.gov/",
        "categories": [{"id": "wildfires", "title": "Wildfires"}],
        "geometry": [
            {"type": "Point", "coordinates": det["coordinates"], "date": det.get("date")}
            for det in detections
        ],
        "sources": [{"id": "FIRMS"}],
        "closed": None,
    }

    return {
        "events": [event],
        "stats": {"total": len(detections), "in_region": len(detections)},
    }
