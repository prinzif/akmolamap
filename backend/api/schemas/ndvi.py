"""
NDVI API response schemas
"""

from typing import List, Literal
from pydantic import BaseModel, Field


class TrendInfo(BaseModel):
    """Trend analysis information"""
    direction: str = Field(..., description="Trend direction: increasing, decreasing, stable, insufficient_data")
    slope: float = Field(..., description="Trend slope (NDVI change per observation)")
    r_squared: float = Field(..., description="R² value indicating trend strength", ge=0, le=1)
    p_value: float = Field(..., description="Statistical significance p-value", ge=0, le=1)
    description: str = Field(..., description="Human-readable trend description")


class StatusInfo(BaseModel):
    """NDVI status classification"""
    status: str = Field(..., description="Status code: critical, poor, moderate, optimal, excellent")
    level: str = Field(..., description="Russian status label")
    description: str = Field(..., description="Status description")


class NDVIStatistics(BaseModel):
    """NDVI statistics for a time period"""
    mean_ndvi: float = Field(..., description="Mean NDVI value", ge=-1, le=1)
    min_ndvi: float = Field(..., description="Minimum NDVI value", ge=-1, le=1)
    max_ndvi: float = Field(..., description="Maximum NDVI value", ge=-1, le=1)
    std_ndvi: float = Field(..., description="Standard deviation", ge=0)
    median_ndvi: float = Field(..., description="Median NDVI value", ge=-1, le=1)
    total_observations: int = Field(..., description="Number of valid observations", ge=0)
    trend: TrendInfo = Field(..., description="Trend analysis")
    status: StatusInfo = Field(..., description="Vegetation status classification")


class NDVITimelinePoint(BaseModel):
    """Single point in NDVI timeline"""
    date: str = Field(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$")
    mean_ndvi: float = Field(..., description="Mean NDVI for this date", ge=-1, le=1)
    min_ndvi: float | None = Field(None, description="Minimum NDVI (optional)", ge=-1, le=1)
    max_ndvi: float | None = Field(None, description="Maximum NDVI (optional)", ge=-1, le=1)
    std_ndvi: float | None = Field(None, description="Standard deviation (optional)", ge=0)
    cloud_coverage: float | None = Field(None, description="Cloud coverage percentage (optional)", ge=0, le=100)
    percentiles: dict | None = Field(None, description="Percentile values (optional): {p10, p25, p50, p75, p90}")


class NDVIStatisticsResponse(BaseModel):
    """Response for NDVI statistics endpoint"""
    status: Literal["success"] = "success"
    statistics: NDVIStatistics
    timeline: List[NDVITimelinePoint]
    products_available: int = Field(..., description="Number of satellite products found", ge=0)
    bbox: List[float] = Field(..., description="Bounding box used", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period queried")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "statistics": {
                        "mean_ndvi": 0.65,
                        "min_ndvi": 0.2,
                        "max_ndvi": 0.9,
                        "std_ndvi": 0.15,
                        "median_ndvi": 0.64,
                        "total_observations": 24,
                        "trend": {
                            "direction": "increasing",
                            "slope": 0.01028,
                            "r_squared": 0.261,
                            "p_value": 0.0107,
                            "description": "NDVI increasing (R²=0.261)"
                        },
                        "status": {
                            "status": "optimal",
                            "level": "Оптимальный",
                            "description": "Здоровая растительность, нормальное состояние"
                        }
                    },
                    "timeline": [
                        {
                            "date": "2024-06-01",
                            "mean_ndvi": 0.62,
                            "min_ndvi": 0.3,
                            "max_ndvi": 0.85,
                            "std_ndvi": 0.15,
                            "percentiles": {
                                "p10": 0.35,
                                "p25": 0.48,
                                "p50": 0.61,
                                "p75": 0.75,
                                "p90": 0.82
                            }
                        }
                    ],
                    "products_available": 15,
                    "bbox": [69.0, 51.0, 73.0, 53.0],
                    "period": {"start": "2024-06-01", "end": "2024-06-30"}
                }
            ]
        }
    }


class HistogramBin(BaseModel):
    """Single histogram bin"""
    min: float = Field(..., description="Bin minimum value", ge=-1, le=1)
    max: float = Field(..., description="Bin maximum value", ge=-1, le=1)
    count: int = Field(..., description="Pixel count in bin", ge=0)
    pct: float = Field(..., description="Percentage of total", ge=0, le=100)
    label: str = Field(..., description="Human-readable label")


class NDVIHistogramResponse(BaseModel):
    """Response for NDVI histogram endpoint"""
    status: Literal["success"] = "success"
    bins: List[HistogramBin]
    total: int = Field(..., description="Total valid pixels", ge=0)
    bbox: List[float] = Field(..., description="Bounding box used", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period queried")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "bins": [
                        {
                            "min": -1.0,
                            "max": 0.0,
                            "count": 150,
                            "pct": 5.2,
                            "label": "Water/Bare Soil"
                        }
                    ],
                    "total": 2880,
                    "bbox": [69.0, 51.0, 73.0, 53.0],
                    "period": {"start": "2024-06-01", "end": "2024-06-30"}
                }
            ]
        }
    }


class TimeseriesPoint(BaseModel):
    """Single point in timeseries"""
    date: str = Field(..., description="Date in YYYY-MM-DD format", pattern=r"^\d{4}-\d{2}-\d{2}$")
    ndvi: float = Field(..., description="NDVI value", ge=-1, le=1)


class NDVITimeseriesResponse(BaseModel):
    """Response for NDVI timeseries endpoint"""
    status: Literal["success"] = "success"
    series: List[TimeseriesPoint]
    location: dict = Field(..., description="Point location (lon, lat)")
    bbox: List[float] = Field(..., description="Bounding box used", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period queried")


class NDVIReportResponse(BaseModel):
    """Response for NDVI report endpoint"""
    status: Literal["success"] = "success"
    report: dict = Field(..., description="Report data with analysis and recommendations")
    bbox: List[float] = Field(..., description="Bounding box analyzed", min_length=4, max_length=4)
    date: str = Field(..., description="Report date", pattern=r"^\d{4}-\d{2}-\d{2}$")


class NDVIGeoTIFFResponse(BaseModel):
    """Response for NDVI GeoTIFF endpoint"""
    status: Literal["success"] = "success"
    tiff_url: str = Field(..., description="URL to download the GeoTIFF file")
    filename: str = Field(..., description="GeoTIFF filename")
    bbox: List[float] = Field(..., description="Bounding box", min_length=4, max_length=4)
    period: dict = Field(..., description="Time period")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "tiff_url": "http://localhost:8000/static/ndvi/ndvi_69.0_51.0_73.0_53.0_2024-06-01_2024-06-30.tif",
                    "filename": "ndvi_69.0_51.0_73.0_53.0_2024-06-01_2024-06-30.tif",
                    "bbox": [69.0, 51.0, 73.0, 53.0],
                    "period": {"start": "2024-06-01", "end": "2024-06-30"}
                }
            ]
        }
    }


class Zone(BaseModel):
    """Agricultural zone information"""
    name: str = Field(..., description="Zone name")
    description: str = Field(..., description="Zone description")
    center: List[float] = Field(..., description="Center coordinates [lat, lon]", min_length=2, max_length=2)
    area_ha: int = Field(..., description="Area in hectares", gt=0)
    typical_crops: List[str] = Field(..., description="Typical crops grown in this zone")


class NDVIZonesResponse(BaseModel):
    """Response for zones endpoint"""
    zones: List[Zone]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "zones": [
                        {
                            "name": "Northern Zone",
                            "description": "Main grain zone",
                            "center": [52.28, 70.4],
                            "area_ha": 1200000,
                            "typical_crops": ["Wheat", "Barley"]
                        }
                    ]
                }
            ]
        }
    }
