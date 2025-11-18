"""
Statistical computation utilities for raster data
"""

from typing import Dict
import numpy as np


def compute_basic_stats(data: np.ndarray) -> Dict[str, float]:
    """
    Compute basic statistics for numpy array, handling NaN/infinite values.

    Args:
        data: Numpy array (can contain NaN or infinite values)

    Returns:
        Dictionary with mean, median, std, min, max (or None if no valid data)
    """
    # Use masked arrays for efficient handling of invalid values
    masked = np.ma.masked_invalid(data)

    if masked.count() == 0:
        # Explicitly delete masked array to free memory
        del masked
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
        }

    result = {
        "mean": float(masked.mean()),
        "median": float(np.ma.median(masked)),
        "std": float(masked.std()),
        "min": float(masked.min()),
        "max": float(masked.max()),
    }

    # Explicitly delete masked array to free memory
    del masked
    return result


def compute_percentiles(
    data: np.ndarray,
    percentiles: list = [10, 25, 50, 75, 90]
) -> Dict[str, float]:
    """
    Compute percentiles for numpy array, handling NaN/infinite values.

    Args:
        data: Numpy array (can contain NaN or infinite values)
        percentiles: List of percentile values to compute (default: [10, 25, 50, 75, 90])

    Returns:
        Dictionary mapping percentile keys (p10, p25, etc.) to values
    """
    masked = np.ma.masked_invalid(data)

    if masked.count() == 0:
        # Clean up masked array before returning
        del masked
        return {f"p{p}": None for p in percentiles}

    # Use compressed() to get only valid values
    valid_data = masked.compressed()
    values = np.percentile(valid_data, percentiles)
    result = {f"p{p}": float(v) for p, v in zip(percentiles, values)}

    # Explicitly delete temporary arrays to free memory
    del valid_data
    del values
    del masked

    return result


def compute_comprehensive_stats(
    data: np.ndarray,
    percentiles: list = [10, 25, 50, 75, 90]
) -> Dict:
    """
    Compute comprehensive statistics including basic stats and percentiles.

    Args:
        data: Numpy array (can contain NaN or infinite values)
        percentiles: List of percentile values to compute

    Returns:
        Dictionary with all statistics
    """
    masked = np.ma.masked_invalid(data)

    if masked.count() == 0:
        # Clean up before returning
        del masked
        return {
            "mean": None,
            "median": None,
            "std": None,
            "min": None,
            "max": None,
            "percentiles": {f"p{p}": None for p in percentiles},
            "pixels": 0
        }

    valid_data = masked.compressed()
    pct_values = np.percentile(valid_data, percentiles)

    result = {
        "mean": float(masked.mean()),
        "median": float(np.ma.median(masked)),
        "std": float(masked.std()),
        "min": float(masked.min()),
        "max": float(masked.max()),
        "percentiles": {f"p{p}": float(v) for p, v in zip(percentiles, pct_values)},
        "pixels": int(masked.count())
    }

    # Explicitly delete temporary arrays to free memory
    del valid_data
    del pct_values
    del masked

    return result
