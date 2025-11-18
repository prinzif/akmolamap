"""
Geospatial utilities for resolution calculation and bbox operations
"""

from typing import Tuple, List, Optional
import math


def choose_optimal_resolution(
    bbox: List[float],
    target_mpp: int = 60,
    min_mpp: int = 10,
    max_mpp: int = 1500,
    min_pixels: int = 64,
    max_pixels: int = 4096
) -> Tuple[int, int]:
    """
    Calculate optimal resolution for a given bounding box.

    Args:
        bbox: [minLon, minLat, maxLon, maxLat]
        target_mpp: Target meters per pixel (default: 60)
        min_mpp: Minimum meters per pixel allowed (default: 10)
        max_mpp: Maximum meters per pixel allowed (default: 1500)
        min_pixels: Minimum pixels per dimension (default: 64)
        max_pixels: Maximum pixels per dimension (default: 4096)

    Returns:
        Tuple of (width_pixels, height_pixels)
    """
    minLon, minLat, maxLon, maxLat = bbox

    # Calculate bbox dimensions in degrees
    lon_deg = abs(maxLon - minLon)
    lat_deg = abs(maxLat - minLat)

    # Convert to approximate meters (at latitude center)
    lat_center = (minLat + maxLat) / 2.0
    meters_per_deg_lon = 111320 * math.cos(math.radians(lat_center))
    meters_per_deg_lat = 110540

    width_m = lon_deg * meters_per_deg_lon
    height_m = lat_deg * meters_per_deg_lat

    # Calculate pixels based on target resolution
    width_px = int(width_m / target_mpp)
    height_px = int(height_m / target_mpp)

    # Constrain to min/max pixels
    if width_px < min_pixels:
        width_px = min_pixels
    elif width_px > max_pixels:
        width_px = max_pixels

    if height_px < min_pixels:
        height_px = min_pixels
    elif height_px > max_pixels:
        height_px = max_pixels

    # Recalculate actual mpp based on constrained pixels
    actual_mpp_x = width_m / width_px if width_px > 0 else target_mpp
    actual_mpp_y = height_m / height_px if height_px > 0 else target_mpp

    # If resolution is too fine or too coarse, adjust
    if actual_mpp_x < min_mpp or actual_mpp_y < min_mpp:
        # Too fine, reduce pixels
        scale_factor = max(min_mpp / actual_mpp_x, min_mpp / actual_mpp_y)
        width_px = max(min_pixels, int(width_px / scale_factor))
        height_px = max(min_pixels, int(height_px / scale_factor))
    elif actual_mpp_x > max_mpp or actual_mpp_y > max_mpp:
        # Too coarse, increase pixels
        scale_factor = min(max_mpp / actual_mpp_x, max_mpp / actual_mpp_y)
        width_px = min(max_pixels, int(width_px * (actual_mpp_x / max_mpp)))
        height_px = min(max_pixels, int(height_px * (actual_mpp_y / max_mpp)))

    return (width_px, height_px)


def bbox_from_geojson(geojson: dict) -> Optional[Tuple[float, float, float, float]]:
    """
    Extract bounding box from GeoJSON geometry.

    Args:
        geojson: GeoJSON geometry object

    Returns:
        Tuple of (minLon, minLat, maxLon, maxLat) or None if invalid
    """
    try:
        geom_type = geojson.get("type")
        coords = geojson.get("coordinates")

        if not coords:
            return None

        # Flatten coordinates based on geometry type
        if geom_type == "Point":
            lon, lat = coords
            return (lon, lat, lon, lat)
        elif geom_type == "Polygon":
            all_coords = coords[0]  # Outer ring
        elif geom_type == "MultiPolygon":
            all_coords = [pt for polygon in coords for pt in polygon[0]]
        else:
            return None

        # Calculate bbox
        lons = [pt[0] for pt in all_coords]
        lats = [pt[1] for pt in all_coords]

        return (min(lons), min(lats), max(lons), max(lats))
    except Exception:
        return None


def parse_bbox_string(bbox_str: str) -> Optional[Tuple[float, float, float, float]]:
    """
    Parse bbox string 'minLon,minLat,maxLon,maxLat' and normalize.

    Args:
        bbox_str: Comma-separated bbox string

    Returns:
        Normalized (minLon, minLat, maxLon, maxLat) or None if invalid
    """
    try:
        x1, y1, x2, y2 = [float(x) for x in bbox_str.split(",")]
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    except Exception:
        return None
