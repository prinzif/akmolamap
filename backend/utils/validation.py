"""
Validation utilities for NDVI and BIOPAR modules.
"""

from datetime import datetime, timedelta, timezone
from typing import List


def validate_bbox(bbox: List[float]) -> None:
    """
    Validate bounding box coordinates.

    Args:
        bbox: List of 4 floats [minLon, minLat, maxLon, maxLat]

    Raises:
        ValueError: If bbox is invalid
    """
    if not isinstance(bbox, (list, tuple)):
        raise ValueError("bbox must be a list or tuple")

    if len(bbox) != 4:
        raise ValueError(
            f"bbox must have exactly 4 values: [minLon, minLat, maxLon, maxLat], got {len(bbox)}"
        )

    try:
        minlon, minlat, maxlon, maxlat = [float(x) for x in bbox]
    except (TypeError, ValueError) as e:
        raise ValueError(f"bbox values must be numeric: {e}")

    # Validate longitude range
    if not (-180 <= minlon <= 180 and -180 <= maxlon <= 180):
        raise ValueError(
            f"Longitude must be between -180 and 180, got minLon={minlon}, maxLon={maxlon}"
        )

    # Validate latitude range
    if not (-90 <= minlat <= 90 and -90 <= maxlat <= 90):
        raise ValueError(
            f"Latitude must be between -90 and 90, got minLat={minlat}, maxLat={maxlat}"
        )

    # Validate min < max
    if minlon >= maxlon:
        raise ValueError(
            f"minLon ({minlon}) must be < maxLon ({maxlon})"
        )

    if minlat >= maxlat:
        raise ValueError(
            f"minLat ({minlat}) must be < maxLat ({maxlat})"
        )

    # Check reasonable area size (prevent too large requests)
    area = (maxlon - minlon) * (maxlat - minlat)
    MAX_AREA = 100  # ~11,000 km² at equator

    if area > MAX_AREA:
        raise ValueError(
            f"bbox area too large: {area:.2f}° (max {MAX_AREA}°). "
            "Please use a smaller area."
        )


def validate_dates(start_date: str, end_date: str, max_days: int = 365) -> None:
    """
    Validate date format and logic.

    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        max_days: Maximum allowed date range in days (default: 365)

    Raises:
        ValueError: If dates are invalid
    """
    # Validate format
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(
            f"Dates must be in YYYY-MM-DD format. Error: {e}"
        )

    # Validate start <= end
    if start > end:
        raise ValueError(
            f"start_date ({start_date}) must be <= end_date ({end_date})"
        )

    # Check reasonable time range
    delta = (end - start).days
    if delta > max_days:
        raise ValueError(
            f"Date range too large: {delta} days (max {max_days} days). "
            "Please use a shorter period."
        )

    # Check not in future
    now = datetime.now(timezone.utc)
    if end > now:
        raise ValueError(
            f"end_date ({end_date}) cannot be in the future"
        )

    # Warn if dates are very old (satellite data may not be available)
    MIN_SENTINEL_DATE = datetime(2015, 6, 23, tzinfo=timezone.utc)  # Sentinel-2A launch
    if start < MIN_SENTINEL_DATE:
        raise ValueError(
            f"start_date ({start_date}) is before Sentinel-2 launch ({MIN_SENTINEL_DATE.date()}). "
            "No data available before this date."
        )


def validate_bins(bins_str: str) -> List[float]:
    """
    Validate and parse histogram bins parameter.

    Args:
        bins_str: Comma-separated bin edges (e.g., "-1,0,0.2,0.6,1")

    Returns:
        List of validated bin edges

    Raises:
        ValueError: If bins are invalid
    """
    try:
        bin_edges = [float(x.strip()) for x in bins_str.split(",")]
    except ValueError as e:
        raise ValueError(f"Invalid bins parameter: {e}")

    if len(bin_edges) < 2:
        raise ValueError(
            f"bins must have at least 2 values, got {len(bin_edges)}"
        )

    # Validate NDVI range
    if any(b < -1 or b > 1 for b in bin_edges):
        raise ValueError(
            "Bin edges must be between -1 and 1 (NDVI range). "
            f"Got: {bin_edges}"
        )

    # Validate ascending order
    if bin_edges != sorted(bin_edges):
        raise ValueError(
            f"Bin edges must be in ascending order. Got: {bin_edges}"
        )

    return bin_edges


def validate_image_dimensions(width: int, height: int, max_total_pixels: int = 16_000_000) -> None:
    """
    Validate image dimensions to prevent OOM errors.

    Args:
        width: Image width in pixels
        height: Image height in pixels
        max_total_pixels: Maximum total pixels allowed (default: 16M = 4000x4000)

    Raises:
        ValueError: If dimensions are invalid
    """
    if width <= 0 or height <= 0:
        raise ValueError(
            f"Image dimensions must be positive, got width={width}, height={height}"
        )

    total_pixels = width * height

    if total_pixels > max_total_pixels:
        raise ValueError(
            f"Image dimensions too large: {width}x{height} = {total_pixels:,} pixels "
            f"(max {max_total_pixels:,} pixels). "
            f"Maximum dimensions: {int(max_total_pixels**0.5)}x{int(max_total_pixels**0.5)}"
        )


def validate_coordinates(lon: float, lat: float) -> None:
    """
    Validate point coordinates.

    Args:
        lon: Longitude
        lat: Latitude

    Raises:
        ValueError: If coordinates are invalid
    """
    if not (-180 <= lon <= 180):
        raise ValueError(
            f"Longitude must be between -180 and 180, got {lon}"
        )

    if not (-90 <= lat <= 90):
        raise ValueError(
            f"Latitude must be between -90 and 90, got {lat}"
        )
