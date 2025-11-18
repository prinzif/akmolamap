"""
API response schemas using Pydantic for validation and documentation
"""

from backend.api.schemas.ndvi import (
    NDVIStatisticsResponse,
    NDVIHistogramResponse,
    NDVITimeseriesResponse,
    NDVIReportResponse,
    NDVIGeoTIFFResponse,
    NDVIZonesResponse,
)
from backend.api.schemas.biopar import (
    BIOPARStatisticsResponse,
    BIOPARTimeseriesResponse,
    BIOPARReportResponse,
    BIOPARGeoTIFFResponse,
)
from backend.api.schemas.common import (
    ErrorResponse,
    SuccessResponse,
)

__all__ = [
    # NDVI schemas
    "NDVIStatisticsResponse",
    "NDVIHistogramResponse",
    "NDVITimeseriesResponse",
    "NDVIReportResponse",
    "NDVIGeoTIFFResponse",
    "NDVIZonesResponse",
    # BIOPAR schemas
    "BIOPARStatisticsResponse",
    "BIOPARTimeseriesResponse",
    "BIOPARReportResponse",
    "BIOPARGeoTIFFResponse",
    # Common schemas
    "ErrorResponse",
    "SuccessResponse",
]
