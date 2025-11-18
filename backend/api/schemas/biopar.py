"""
BIOPAR API response schemas
"""

from typing import List, Literal
from pydantic import BaseModel, Field


class BIOPARStatistics(BaseModel):
    """BIOPAR statistics for a time period"""
    mean: float = Field(..., description="Mean BIOPAR value", ge=0)
    min: float = Field(..., description="Minimum BIOPAR value", ge=0)
    max: float = Field(..., description="Maximum BIOPAR value", ge=0)
    std: float = Field(..., description="Standard deviation", ge=0)
    median: float | None = Field(None, description="Median BIOPAR value", ge=0)


class BIOPARTimelinePoint(BaseModel):
    """Single point in BIOPAR timeline"""
    date: str = Field(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$")
    mean_value: float = Field(..., description="Mean BIOPAR value", ge=0)
    min_value: float | None = Field(None, description="Minimum value", ge=0)
    max_value: float | None = Field(None, description="Maximum value", ge=0)
    std_value: float | None = Field(None, description="Standard deviation", ge=0)


class BIOPARStatisticsResponse(BaseModel):
    """Response for BIOPAR statistics endpoint"""
    status: Literal["success"] = "success"
    statistics: BIOPARStatistics
    timeline: List[BIOPARTimelinePoint]
    biopar_type: str = Field(..., description="BIOPAR type (FAPAR, LAI, FCOVER, CCC, CWC)")
    products_available: int = Field(..., description="Number of products found", ge=0)
    bbox: List[float] = Field(..., description="Bounding box used", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period queried")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "statistics": {
                        "mean": 0.72,
                        "min": 0.35,
                        "max": 0.95,
                        "std": 0.18
                    },
                    "timeline": [
                        {
                            "date": "2024-06-01",
                            "mean_value": 0.70,
                            "min_value": 0.40,
                            "max_value": 0.92
                        }
                    ],
                    "biopar_type": "FAPAR",
                    "products_available": 12,
                    "bbox": [69.0, 51.0, 73.0, 53.0],
                    "period": {"start": "2024-06-01", "end": "2024-06-30"}
                }
            ]
        }
    }


class BIOPARTimeseriesPoint(BaseModel):
    """Single point in BIOPAR timeseries"""
    date: str = Field(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$")
    value: float = Field(..., description="BIOPAR value", ge=0)
    aggregation_window: int | None = Field(None, description="Aggregation window in days", ge=1)


class BIOPARTrendInfo(BaseModel):
    """Trend analysis information"""
    direction: str = Field(..., description="Trend direction: increasing, decreasing, stable, or insufficient_data")
    slope: float = Field(..., description="Trend slope")
    r_squared: float = Field(..., description="R-squared value", ge=0, le=1)
    p_value: float = Field(..., description="P-value for significance", ge=0, le=1)
    description: str | None = Field(None, description="Human-readable trend description")


class BIOPARTimeseriesTimelinePoint(BaseModel):
    """Timeline point with statistics (for frontend compatibility)"""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    mean: float | None = Field(None, description="Mean value")
    min: float | None = Field(None, description="Minimum value")
    max: float | None = Field(None, description="Maximum value")
    std: float | None = Field(None, description="Standard deviation")
    p50: float | None = Field(None, description="50th percentile")
    median: float | None = Field(None, description="Median value")


class BIOPARTimeseriesResponse(BaseModel):
    """Response for BIOPAR timeseries endpoint"""
    status: Literal["success"] = "success"
    series: List[BIOPARTimeseriesPoint]
    timeline: List[BIOPARTimeseriesTimelinePoint] | None = Field(None, description="Timeline with detailed statistics (for frontend)")
    trend: BIOPARTrendInfo | None = Field(None, description="Trend analysis (for frontend)")
    biopar_type: str = Field(..., description="BIOPAR type")
    aggregation_days: int = Field(..., description="Aggregation window", ge=1)
    bbox: List[float] = Field(..., description="Bounding box used", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period queried")


class BIOPARReportResponse(BaseModel):
    """Response for BIOPAR report endpoint"""
    status: Literal["success"] = "success"
    report: dict = Field(..., description="Report data with analysis")
    biopar_type: str = Field(..., description="BIOPAR type analyzed")
    bbox: List[float] = Field(..., description="Bounding box analyzed", min_length=4, max_length=4)
    date: str = Field(..., description="Report date", pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_days: int = Field(..., description="Analysis period in days", ge=1)


class BIOPARGeoTIFFResponse(BaseModel):
    """Response for BIOPAR GeoTIFF endpoint"""
    status: Literal["success"] = "success"
    tiff_url: str = Field(..., description="URL to download the GeoTIFF file")
    filename: str = Field(..., description="GeoTIFF filename")
    bbox: List[float] = Field(..., description="Bounding box", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period")
    biopar_type: str = Field(..., description="BIOPAR type")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "tiff_url": "http://localhost:8000/api/v1/biopar/file/fapar_69.0_51.0_73.0_53.0_2024-06-01_2024-06-30.tif",
                    "filename": "fapar_69.0_51.0_73.0_53.0_2024-06-01_2024-06-30.tif",
                    "bbox": [69.0, 51.0, 73.0, 53.0],
                    "period": {"start": "2024-06-01", "end": "2024-06-30"},
                    "biopar_type": "FAPAR"
                }
            ]
        }
    }
