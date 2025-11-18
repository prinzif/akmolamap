# /backend/api/routers/biopar.py

import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from backend.api.deps import BBox, Date
from backend.biopar import (
    get_biopar_statistics,
    get_biopar_timeseries,
    generate_biopar_report,
    fetch_biopar_geotiff as fetch_biopar_geotiff_openeo,
)
from backend.biopar_sentinelhub import (
    fetch_biopar_geotiff as fetch_biopar_geotiff_sh,
    NoDataAvailableError,
    SentinelHubError,
)
from backend.utils import (
    validate_bbox,
    validate_dates,
    validate_image_dimensions,
)
from backend.settings import settings
from backend.api.schemas import (
    BIOPARStatisticsResponse,
    BIOPARTimeseriesResponse,
    BIOPARReportResponse,
    BIOPARGeoTIFFResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/biopar", tags=["BIOPAR"])

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
BIOPAR_HTML = FRONTEND_DIR / "biopar.html"

BIOPAR_TYPES = {"FAPAR", "LAI", "FCOVER", "CCC", "CWC"}
SH_SUPPORTED = {"FAPAR", "LAI", "FCOVER"}  # через Sentinel Hub Processing API


def _bbox_to_polygon(bbox: List[float]) -> Dict[str, Any]:
    """Преобразует bbox [minx,miny,maxx,maxy] в GeoJSON Polygon (EPSG:4326)."""
    if len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise HTTPException(400, "Invalid bbox: expected [minlon,minlat,maxlon,maxlat].")
    minx, miny, maxx, maxy = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny],
            [maxx, miny],
            [maxx, maxy],
            [minx, maxy],
            [minx, miny],
        ]],
    }


@router.get("", response_class=FileResponse)
def page():
    """Отдаёт страницу мониторинга BIOPAR."""
    if not BIOPAR_HTML.exists():
        raise HTTPException(404, f"{BIOPAR_HTML.name} not found")
    return FileResponse(str(BIOPAR_HTML), media_type="text/html")


@router.get(
    "/stats",
    response_model=BIOPARStatisticsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "No data available"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def stats(
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
    biopar_type: str = Query("FAPAR", description="BIOPAR type: FAPAR, LAI, FCOVER, CCC, CWC"),
):
    """
    Get BIOPAR statistics for the specified area and time period.

    Returns aggregated statistics (mean, min, max, std) and timeline for biophysical parameters.

    - **bbox**: Bounding box [minLon, minLat, maxLon, maxLat]
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    - **biopar_type**: Type of biophysical parameter (FAPAR, LAI, FCOVER, CCC, CWC)
    """
    bt = biopar_type.upper()
    if bt not in BIOPAR_TYPES:
        raise HTTPException(400, f"biopar_type must be one of {sorted(BIOPAR_TYPES)}")

    try:
        validate_bbox(bbox)
        validate_dates(start, end)

        aoi = _bbox_to_polygon(bbox)
        result = get_biopar_statistics(aoi, start, end, biopar_type=bt, use_cache=True)

        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            error_lower = error_msg.lower()

            # Classify error by type
            no_data_indicators = [
                "no data", "no satellite", "not found", "unavailable",
                "no valid", "no products"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(404, f"No data available: {error_msg}")

            # Check for validation errors
            validation_indicators = ["invalid", "parameter", "must be", "out of range"]
            if any(indicator in error_lower for indicator in validation_indicators):
                raise HTTPException(400, error_msg)

            # Other business logic errors
            logger.error(f"BIOPAR processing error: {error_msg}")
            raise HTTPException(422, "Unable to process request: " + error_msg)

        return result

    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BIOPAR/stats] error: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to compute statistics: {str(e)}")


@router.get(
    "/timeseries",
    response_model=BIOPARTimeseriesResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "No data available"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def timeseries(
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
    biopar_type: str = Query("FAPAR", description="BIOPAR type: FAPAR, LAI, FCOVER, CCC, CWC"),
    agg: int = Query(10, ge=3, le=30, description="Aggregation window (days)"),
):
    """
    Get BIOPAR timeseries with temporal aggregation.

    Returns a time series of BIOPAR values aggregated over specified time windows.

    - **bbox**: Bounding box [minLon, minLat, maxLon, maxLat]
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    - **biopar_type**: Type of biophysical parameter
    - **agg**: Aggregation window in days (3-30)
    """
    bt = biopar_type.upper()
    if bt not in BIOPAR_TYPES:
        raise HTTPException(400, f"biopar_type must be one of {sorted(BIOPAR_TYPES)}")

    try:
        validate_bbox(bbox)
        validate_dates(start, end)

        aoi = _bbox_to_polygon(bbox)
        result = get_biopar_timeseries(
            aoi_geojson=aoi,
            start_date=start,
            end_date=end,
            biopar_type=bt,
            aggregation_days=agg,
            use_cache=True,
        )
        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            error_lower = error_msg.lower()

            # Classify error by type
            no_data_indicators = [
                "no data", "no satellite", "not found", "unavailable",
                "no valid", "no products"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(404, f"No data available: {error_msg}")

            # Check for validation errors
            validation_indicators = ["invalid", "parameter", "must be", "out of range"]
            if any(indicator in error_lower for indicator in validation_indicators):
                raise HTTPException(400, error_msg)

            # Other business logic errors
            logger.error(f"BIOPAR processing error: {error_msg}")
            raise HTTPException(422, "Unable to process request: " + error_msg)

        # Add bbox and period to response for schema compliance
        result["bbox"] = bbox
        result["period"] = {"start": start, "end": end}

        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BIOPAR/timeseries] error: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to get timeseries: {str(e)}")


@router.get(
    "/report",
    response_model=BIOPARReportResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "Insufficient data to generate report"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def report(
    bbox: List[float] = Depends(BBox),
    date: str = Depends(Date("date")),
    biopar_type: str = Query("FAPAR", description="BIOPAR type: FAPAR, LAI, FCOVER, CCC, CWC"),
    period_days: int = Query(30, ge=7, le=120, description="Days before 'date' to analyze"),
    agg: int = Query(10, ge=3, le=30, description="Aggregation window (days)"),
):
    """
    Generate BIOPAR analysis report.

    Returns a comprehensive report analyzing biophysical parameters over the specified period.

    - **bbox**: Bounding box to analyze
    - **date**: End date for the report
    - **biopar_type**: Type of biophysical parameter
    - **period_days**: Number of days before 'date' to analyze (7-120)
    - **agg**: Aggregation window in days (3-30)
    """
    bt = biopar_type.upper()
    if bt not in BIOPAR_TYPES:
        raise HTTPException(400, f"biopar_type must be one of {sorted(BIOPAR_TYPES)}")

    try:
        validate_bbox(bbox)
        # Validate single date
        validate_dates(date, date, max_days=1)

        aoi = _bbox_to_polygon(bbox)
        result = generate_biopar_report(
            aoi_geojson=aoi,
            date=date,
            period_days=period_days,
            biopar_type=bt,
            aggregation_days=agg,
        )
        if result.get("status") == "error":
            error_msg = result.get("message", "Unknown error")
            error_lower = error_msg.lower()

            # Classify error by type
            no_data_indicators = [
                "no data", "no satellite", "not found", "unavailable",
                "insufficient", "no valid"
            ]
            if any(indicator in error_lower for indicator in no_data_indicators):
                raise HTTPException(404, f"Cannot generate report: {error_msg}")

            raise HTTPException(500, f"Failed to generate report: {error_msg}")

        # Add bbox, date, and period_days to response for schema compliance
        result["bbox"] = bbox
        result["date"] = date
        result["period_days"] = period_days

        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[BIOPAR/report] error: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to generate report: {str(e)}")


# /backend/api/routers/biopar.py

from pathlib import Path

@router.get(
    "/geotiff",
    response_model=BIOPARGeoTIFFResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input parameters"},
        404: {"model": ErrorResponse, "description": "No satellite data available"},
        503: {"model": ErrorResponse, "description": "Sentinel Hub or openEO API unavailable"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
def geotiff(
    bbox: List[float] = Depends(BBox),
    start: str = Depends(Date("start")),
    end: str = Depends(Date("end")),
    biopar_type: str = Query("FAPAR", description="BIOPAR type: FAPAR, LAI, FCOVER, CCC, CWC"),
    width: int = Query(2048, ge=64, le=8192),
    height: int = Query(2048, ge=64, le=8192),
    max_cloud_coverage: int = Query(30, ge=0, le=100),
):
    """
    Get BIOPAR GeoTIFF file for the specified area and time period.

    Returns a URL to download a GeoTIFF raster file containing biophysical parameter values.

    - **bbox**: Bounding box [minLon, minLat, maxLon, maxLat]
    - **start**: Start date in YYYY-MM-DD format
    - **end**: End date in YYYY-MM-DD format
    - **biopar_type**: Type of biophysical parameter (FAPAR, LAI, FCOVER, CCC, CWC)
    - **width**: Output image width in pixels (64-8192)
    - **height**: Output image height in pixels (64-8192)
    - **max_cloud_coverage**: Maximum cloud coverage percentage (0-100)

    Note: FAPAR, LAI, FCOVER use Sentinel Hub. CCC and CWC use openEO.
    """
    bt = biopar_type.upper()
    if bt not in BIOPAR_TYPES:
        raise HTTPException(400, f"biopar_type must be one of {sorted(BIOPAR_TYPES)}")

    try:
        validate_bbox(bbox)
        validate_dates(start, end)
        validate_image_dimensions(width, height)

        logger.info(f"[BIOPAR/geotiff] {bt}: bbox={bbox}, {start}..{end}")

        # Маршрут: Sentinel Hub (FAPAR/LAI/FCOVER)
        if bt in SH_SUPPORTED:
            tif_path = fetch_biopar_geotiff_sh(
                bbox=bbox,
                start_date=start,
                end_date=end,
                biopar_type=bt,
                width=width,
                height=height,
                max_cloud_coverage=max_cloud_coverage,
            )
            filename = tif_path.name
            # URL через новый эндпоинт /file/ (use configured base URL)
            public_url = f"{settings.API_BASE_URL}/api/v1/biopar/file/{filename}"
        else:
            # openEO UDP (CCC/CWC)
            aoi = _bbox_to_polygon(bbox)
            tif_path = fetch_biopar_geotiff_openeo(
                aoi_geojson=aoi,
                start_date=start,
                end_date=end,
                biopar_type=bt,
                force=False,
            )
            filename = tif_path.name
            # Use configured base URL instead of hardcoded localhost
            public_url = f"{settings.API_BASE_URL}/api/v1/biopar/file/{filename}"

        # Проверяем существование
        if not tif_path.exists():
            raise HTTPException(404, f"Generated file not found: {filename}")

        logger.info(f"[BIOPAR/geotiff] ready: {filename}")

        # Возвращаем JSON как раньше
        return {
            "status": "success",
            "tiff_url": public_url,
            "filename": filename,
            "bbox": bbox,
            "period": {"start": start, "end": end},
            "biopar_type": bt,
        }

    except ValueError as e:
        raise HTTPException(400, str(e))
    except NoDataAvailableError as e:
        logger.warning(f"[BIOPAR/geotiff] No data: {e}")
        raise HTTPException(
            404,
            f"No satellite data available for {start} to {end}. "
            f"Try another date range or relax cloud coverage.",
        )

    except SentinelHubError as e:
        logger.error(f"[BIOPAR/geotiff] Sentinel Hub error: {e}")
        raise HTTPException(
            503,
            f"Sentinel Hub Processing API error: {str(e)}. "
            f"The service may be temporarily unavailable.",
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"[BIOPAR/geotiff] internal error: {e}", exc_info=True)
        raise HTTPException(500, f"Internal error while fetching BIOPAR GeoTIFF: {str(e)}")


@router.api_route("/file/{filename}", methods=["GET", "HEAD"])
def get_biopar_file(filename: str):
    """
    Отдаёт BIOPAR GeoTIFF файл по имени (включая auxiliary файлы).
    Ищет в обеих директориях: cache/biopar_sh и cache/biopar/tiffs
    Поддерживает HEAD запросы для совместимости с GDAL/TiTiler.
    """
    # Advanced path traversal protection
    # 1. Use basename to remove any path components
    safe_filename = Path(filename).name

    # 2. Block any suspicious characters or patterns
    if ".." in safe_filename or "/" in safe_filename or "\\" in safe_filename or safe_filename != filename:
        logger.warning(f"[BIOPAR/file] Path traversal attempt blocked: {filename}")
        raise HTTPException(400, "Invalid filename")

    # 3. Allow GeoTIFF files and GDAL auxiliary files
    allowed_extensions = {
        ".tif", ".tiff",           # Main GeoTIFF files
        ".aux", ".aux.xml",        # GDAL auxiliary files
        ".ovr", ".rrd",            # Overview/pyramid files
        ".msk",                    # Mask files
        ".vrt",                    # Virtual raster
        ".tfw", ".wld"            # World files
    }

    # Check if filename ends with any allowed extension (case-insensitive)
    filename_lower = safe_filename.lower()
    if not any(filename_lower.endswith(ext) for ext in allowed_extensions):
        # Silently return 404 for auxiliary files that don't exist (GDAL probes for them)
        raise HTTPException(404, f"File not found: {safe_filename}")

    # Define allowed cache directories with absolute paths
    CACHE_ROOT = Path(__file__).resolve().parents[3] / "cache"
    sh_dir = CACHE_ROOT / "biopar_sh"
    openeo_dir = CACHE_ROOT / "biopar" / "tiffs"

    # Ищем файл в обеих возможных локациях
    sh_path = sh_dir / safe_filename
    openeo_path = openeo_dir / safe_filename

    # 4. Resolve paths and verify they're within allowed directories
    file_path = None
    if sh_path.exists():
        resolved_path = sh_path.resolve()
        if not str(resolved_path).startswith(str(sh_dir.resolve())):
            logger.error(f"[BIOPAR/file] Path traversal detected in sh_path: {filename}")
            raise HTTPException(403, "Access denied")
        file_path = resolved_path
    elif openeo_path.exists():
        resolved_path = openeo_path.resolve()
        if not str(resolved_path).startswith(str(openeo_dir.resolve())):
            logger.error(f"[BIOPAR/file] Path traversal detected in openeo_path: {filename}")
            raise HTTPException(403, "Access denied")
        file_path = resolved_path
    else:
        logger.warning(f"[BIOPAR/file] File not found: {safe_filename}")
        raise HTTPException(404, f"File not found: {safe_filename}")

    logger.info(f"[BIOPAR/file] Serving: {file_path}")

    # Determine media type based on extension
    if filename_lower.endswith((".tif", ".tiff")):
        media_type = "image/tiff"
    elif filename_lower.endswith(".xml"):
        media_type = "application/xml"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": f"inline; filename={safe_filename}",
            "Cache-Control": "public, max-age=3600",
        }
    )