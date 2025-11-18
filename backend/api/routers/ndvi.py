# /backend/api/routers/ndvi.py

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.api.deps import BBox, Date
from backend.ndvi import (
    get_agricultural_zones as get_ndvi_zones,
    get_ndvi_statistics,
    get_ndvi_histogram,
    get_point_timeseries,
    generate_ndvi_report,
)
from backend.ndvi_sentinelhub import (
    fetch_ndvi_geotiff,
    NoDataAvailableError,
    SentinelHubError
)
from backend.utils import (
    validate_bbox,
    validate_dates,
    validate_bins,
    validate_coordinates,
)
from backend.settings import settings
from backend.api.schemas import (
    NDVIStatisticsResponse,
    NDVIHistogramResponse,
    NDVITimeseriesResponse,
    NDVIReportResponse,
    NDVIGeoTIFFResponse,
    NDVIZonesResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ndvi", tags=["NDVI"])

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
NDVI_HTML = FRONTEND_DIR / "ndvi.html"


# ============================================
# Error Message Sanitization
# ============================================

def sanitize_error_message(error: Exception, context: str = "operation") -> str:
    """
    Sanitize error messages to prevent leaking implementation details.

    Args:
        error: The exception to sanitize
        context: Context description (e.g., "statistics", "histogram")

    Returns:
        User-friendly error message without implementation details
    """
    error_str = str(error).lower()

    # Known safe error types that can be shown to users
    if isinstance(error, ValueError):
        # ValueError usually contains user-facing validation messages
        return str(error)

    # Check for specific patterns that indicate user-facing errors
    safe_patterns = [
        "invalid", "must be", "out of range", "too large", "too small",
        "required", "missing", "not found", "unavailable", "no data"
    ]

    if any(pattern in error_str for pattern in safe_patterns):
        return str(error)

    # Log the actual error for debugging
    logger.error(f"Error during {context}: {error}", exc_info=True)

    # Return generic message to user
    return f"Unable to complete {context}. Please try again or contact support if the issue persists."


@router.get("", response_class=FileResponse)
def page():
    """Отдаёт страницу мониторинга NDVI."""
    if not NDVI_HTML.exists():
        raise HTTPException(404, f"{NDVI_HTML.name} not found")
    return FileResponse(str(NDVI_HTML), media_type="text/html")


@router.get(
    "/zones",
    response_model=NDVIZonesResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid bbox"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def zones(bbox: List[float] = Depends(BBox)):
    """
    Get agricultural zones within the specified bounding box.

    Returns a list of agricultural zones with their locations, areas, and typical crops.
    """
    try:
        validate_bbox(bbox)
        return {"zones": get_ndvi_zones(bbox)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        sanitized_msg = sanitize_error_message(e, "zone retrieval")
        raise HTTPException(500, sanitized_msg)


@router.get(
    "/statistics",
    response_model=NDVIStatisticsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "No satellite data available"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def statistics(
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
):
    """
    Get NDVI statistics and timeline for the specified area and time period.

    Returns aggregated statistics (mean, min, max, std) and a timeline of NDVI values
    for each available satellite image within the date range.

    - **bbox**: Bounding box [minLon, minLat, maxLon, maxLat] in EPSG:4326
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    """
    try:
        validate_bbox(bbox)
        validate_dates(start, end)

        result = get_ndvi_statistics(bbox, start, end)

        # Проверяем что вернулись данные
        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            # Classify error by type
            error_lower = error_msg.lower()
            no_data_indicators = [
                "no sentinel", "no products", "no data", "no satellite",
                "no valid", "no scenes", "not found", "unavailable"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(
                    404,
                    f"No satellite data available for the period {start} to {end}. "
                    f"Try a different date range or check cloud coverage."
                )
            raise HTTPException(500, error_msg)

        # Add bbox and period to response for schema compliance
        result["bbox"] = bbox
        result["period"] = {"start": start, "end": end}

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        sanitized_msg = sanitize_error_message(e, "statistics computation")
        raise HTTPException(500, sanitized_msg)


@router.get(
    "/hist",
    response_model=NDVIHistogramResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "No valid NDVI data"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def histogram(
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
    bins: Optional[str] = Query(None, description="Comma-separated bin edges, e.g. '-1,0,0.2,0.3,0.6,1'")
):
    """
    Get NDVI histogram distribution for the specified area and time period.

    Returns a histogram showing the distribution of NDVI values across different classes
    (e.g., bare soil, sparse vegetation, healthy vegetation).

    - **bbox**: Bounding box [minLon, minLat, maxLon, maxLat]
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    - **bins**: Optional custom bin edges (comma-separated), defaults to standard NDVI classes
    """
    try:
        validate_bbox(bbox)
        validate_dates(start, end)

        # Валидируем bins если предоставлены
        bin_edges = None
        if bins:
            bin_edges = validate_bins(bins)

        result = get_ndvi_histogram(bbox, start, end, bins=bin_edges)

        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            # Classify error by type
            error_lower = error_msg.lower()
            no_data_indicators = [
                "no valid", "no data", "no pixels", "no satellite",
                "not found", "unavailable"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(
                    404,
                    f"No valid NDVI data for the period {start} to {end}. "
                    f"Area may be covered by clouds or outside satellite coverage."
                )
            raise HTTPException(500, error_msg)

        # Add bbox and period to response for schema compliance
        result["bbox"] = bbox
        result["period"] = {"start": start, "end": end}

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except NoDataAvailableError as e:
        logger.warning(f"No data for histogram: {e}")
        raise HTTPException(404, str(e))
    except Exception as e:
        sanitized_msg = sanitize_error_message(e, "histogram computation")
        raise HTTPException(500, sanitized_msg)


@router.get(
    "/timeseries",
    response_model=NDVITimeseriesResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid coordinates or point outside bbox"},
        404: {"model": ErrorResponse, "description": "No data available"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def timeseries(
    lon: float = Query(..., description="Longitude (-180 to 180)"),
    lat: float = Query(..., description="Latitude (-90 to 90)"),
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
    max_dates: int = Query(15, ge=1, le=50, description="Maximum number of dates to return")
):
    """
    Get NDVI timeseries for a specific point location.

    Returns NDVI values over time for a single point (lon, lat) within the bounding box.

    - **lon**: Longitude of the point
    - **lat**: Latitude of the point
    - **bbox**: Bounding box containing the point
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    - **max_dates**: Maximum number of dates to return (1-50)
    """
    try:
        validate_bbox(bbox)
        validate_dates(start, end)
        validate_coordinates(lon, lat)

        result = get_point_timeseries(lon, lat, bbox, start, end, max_dates)

        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            error_lower = error_msg.lower()

            # Classify error by type
            if "outside bbox" in error_lower or "outside box" in error_lower:
                raise HTTPException(400, "Point is outside the specified bounding box")

            no_data_indicators = [
                "no data", "no satellite", "not found", "unavailable"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(404, f"No data available: {error_msg}")

            raise HTTPException(500, error_msg)

        # Add bbox and period to response for schema compliance
        result["bbox"] = bbox
        result["period"] = {"start": start, "end": end}

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        sanitized_msg = sanitize_error_message(e, "timeseries retrieval")
        raise HTTPException(500, sanitized_msg)


@router.get(
    "/report",
    response_model=NDVIReportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "Insufficient data to generate report"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def report(
    bbox: List[float] = Depends(BBox),
    date: str = Depends(Date("date")),
):
    """
    Generate NDVI analysis report for the last 30 days before the specified date.

    Returns a comprehensive report with:
    - Vegetation health analysis
    - Trend analysis
    - Recommendations for agricultural management

    - **bbox**: Bounding box of the area to analyze
    - **date**: End date for the report (analyzes 30 days before this date)
    """
    try:
        validate_bbox(bbox)
        # Validate single date (end_date is same as start_date for single date validation)
        validate_dates(date, date, max_days=1)

        result = generate_ndvi_report(bbox, date)

        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            error_lower = error_msg.lower()

            # Classify error by type
            no_data_indicators = [
                "no data", "no satellite", "not found", "unavailable", "insufficient"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(404, f"Cannot generate report: {error_msg}")

            # Sanitize other error types
            logger.error(f"Report generation error: {error_msg}")
            raise HTTPException(422, "Unable to generate report. Please try again or contact support.")

        # Add bbox and date to response for schema compliance
        result["bbox"] = bbox
        result["date"] = date

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        sanitized_msg = sanitize_error_message(e, "report generation")
        raise HTTPException(500, sanitized_msg)


@router.get(
    "/geotiff",
    response_model=NDVIGeoTIFFResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "No satellite data available"},
        503: {"model": ErrorResponse, "description": "Sentinel Hub API unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def geotiff(
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
    width: int = Query(2048, ge=64, le=8192, description="Output image width in pixels"),
    height: int = Query(2048, ge=64, le=8192, description="Output image height in pixels"),
):
    """
    Get NDVI GeoTIFF file for the specified area and time period.

    Returns a URL to download a GeoTIFF raster file containing NDVI values
    that can be used with mapping tools like QGIS or TiTiler.

    - **bbox**: Bounding box [minLon, minLat, maxLon, maxLat]
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    - **width**: Output width in pixels (default: 2048, range: 64-8192)
    - **height**: Output height in pixels (default: 2048, range: 64-8192)

    The returned GeoTIFF contains:
    - NDVI values ranging from -1 to 1
    - Cloud-masked data (clouds removed)
    - Mosaicked from multiple satellite images
    - GeoTIFF format with proper georeferencing
    """
    try:
        validate_bbox(bbox)
        validate_dates(start, end)

        # Validate that total pixels doesn't exceed memory limits
        MAX_TOTAL_PIXELS = 67_000_000  # ~8192x8192
        if width * height > MAX_TOTAL_PIXELS:
            raise ValueError(
                f"Image dimensions too large: {width}x{height} = {width*height:,} pixels "
                f"(max {MAX_TOTAL_PIXELS:,})"
            )

        logger.info(f"Fetching NDVI GeoTIFF: bbox={bbox}, {start}..{end}, {width}x{height}")

        tif_path = fetch_ndvi_geotiff(
            bbox=bbox,
            start_date=start,
            end_date=end,
            width=width,
            height=height,
            max_cloud_coverage=20
        )
        
        filename = tif_path.name

        # URL для раздачи через FastAPI static mount
        # Убедись что в main.py есть: app.mount("/static/ndvi", StaticFiles(directory="cache/ndvi"), name="ndvi_cache")
        # Use configured base URL instead of hardcoded localhost
        public_url = f"{settings.API_BASE_URL}/static/ndvi/{filename}"

        logger.info(f"GeoTIFF ready: {filename}")
        
        return {
            "status": "success",
            "tiff_url": public_url,
            "filename": filename,
            "bbox": bbox,
            "period": {"start": start, "end": end}
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except NoDataAvailableError as e:
        logger.warning(f"No data available: {e}")
        raise HTTPException(
            404,
            f"No satellite data available for {start} to {end}. "
            f"Try a different date range with less cloud coverage or check if area is covered by Sentinel-2."
        )

    except SentinelHubError as e:
        logger.error(f"Sentinel Hub API error: {e}")
        raise HTTPException(
            503,
            f"Sentinel Hub Processing API error: {str(e)}. "
            f"The service may be temporarily unavailable. Please try again later."
        )

    except Exception as e:
        logger.error(f"NDVI GeoTIFF error: {e}", exc_info=True)
        raise HTTPException(
            500,
            f"Internal error while fetching NDVI GeoTIFF: {str(e)}"
        )