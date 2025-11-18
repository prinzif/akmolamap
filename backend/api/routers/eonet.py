# backend/api/routers/eonet.py
from typing import Optional
from fastapi import APIRouter, Query
from backend.api.deps import validate_date
from backend.eonet import load_events

router = APIRouter(tags=["EONET"])

@router.get("/events")
async def events(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    status: str = Query("open", description="open | closed | all"),
    bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of events to return"),
    offset: int = Query(0, ge=0, description="Number of events to skip (for pagination)"),
):
    """
    Retrieve NASA EONET events with optional filtering and pagination.

    - **start**: Start date (YYYY-MM-DD)
    - **end**: End date (YYYY-MM-DD)
    - **status**: Event status filter (open/closed/all)
    - **bbox**: Bounding box filter (minLon,minLat,maxLon,maxLat)
    - **limit**: Max events per page (1-1000, default 100)
    - **offset**: Number of events to skip for pagination
    """
    if start:
        validate_date(start, "start")
    if end:
        validate_date(end, "end")
    return await load_events(
        start=start,
        end=end,
        status=status,
        bbox_str=bbox,
        limit=limit,
        offset=offset
    )
