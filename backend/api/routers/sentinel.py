# backend/api/routers/sentinel.py
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi import APIRouter, HTTPException, Query, Response, Depends

from backend.api.deps import BBox, OptionalDate
from backend.sentinel import (
    search_products,
    get_quicklook,
    get_product_info,
    check_cdse_health,
)

router = APIRouter(prefix="/sentinel", tags=["Sentinel"])


@router.get("/search")
def sentinel_search(
    bbox: List[float] = Depends(BBox),
    start: Optional[str] = Depends(OptionalDate("start")),
    end: Optional[str] = Depends(OptionalDate("end")),
    platform: str = Query("Sentinel-2", description="Sentinel-2 | Sentinel-1"),
    cloudmax: int = Query(40, ge=0, le=100, description="Max cloud coverage, % (S2 only)"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search for products in CDSE by bbox/date/platform/cloud coverage.
    Returns a list of product cards suitable for the frontend.
    """
    try:
        items = search_products(
            bbox=bbox,
            start=start,
            end=end,
            platform=platform,
            cloudmax=cloudmax,
            limit=limit,
        )
        return {"items": items}
    except Exception as e:
        # 503 Service Unavailable - upstream CDSE service failure
        raise HTTPException(503, f"Sentinel search failed: {e}")


@router.get("/quicklook/{product_id}")
def sentinel_quicklook(product_id: str):
    """
    Returns quicklook (thumbnail) for product_id as image/jpeg/png.
    """
    try:
        data = get_quicklook(product_id)
        # Content-type can be jpeg or png - defaulting to jpeg
        return Response(content=data, media_type="image/jpeg")
    except Exception as e:
        # 404 Not Found - product or quicklook doesn't exist
        raise HTTPException(404, f"Quicklook not available: {e}")


@router.get("/product/{product_id}")
def sentinel_product_info(product_id: str):
    """
    Detailed product information (for debugging/metadata).
    """
    try:
        return get_product_info(product_id)
    except Exception as e:
        # 503 Service Unavailable - upstream CDSE service failure
        raise HTTPException(503, f"Failed to get product info: {e}")


@router.get("/health")
def sentinel_health():
    """
    Simple CDSE API health check.
    """
    ok = check_cdse_health()
    return {"ok": ok}
