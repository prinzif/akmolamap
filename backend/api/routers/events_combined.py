# backend/api/routers/events_combined.py
from typing import Optional
from fastapi import APIRouter, Query

from backend.api.deps import validate_date
from backend.events_combined import load_events_combined

router = APIRouter(prefix="/events", tags=["Events Combined"])

@router.get("/combined")
async def events_combined(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    status: str = Query("open", description="open | closed | all"),
    bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat"),
):
    if start:
        validate_date(start, "start")
    if end:
        validate_date(end, "end")
    return await load_events_combined(start, end, status, bbox)
