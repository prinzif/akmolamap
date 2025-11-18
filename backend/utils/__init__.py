"""Shared utility modules for the Akmola Sentinel API"""

from backend.utils.geo import choose_optimal_resolution
from backend.utils.stats import compute_basic_stats
from backend.utils.validation import (
    validate_bbox,
    validate_dates,
    validate_bins,
    validate_image_dimensions,
    validate_coordinates,
)
from backend.utils.cache import (
    file_lock,
    atomic_write_cache,
    safe_cache_read,
    cleanup_old_cache,
    get_cache_stats,
    is_cache_valid,
    get_cache_age_seconds,
    touch_cache_file,
    cleanup_expired_cache,
)

__all__ = [
    "choose_optimal_resolution",
    "compute_basic_stats",
    "validate_bbox",
    "validate_dates",
    "validate_bins",
    "validate_image_dimensions",
    "validate_coordinates",
    "file_lock",
    "atomic_write_cache",
    "safe_cache_read",
    "cleanup_old_cache",
    "get_cache_stats",
    "is_cache_valid",
    "get_cache_age_seconds",
    "touch_cache_file",
    "cleanup_expired_cache",
]
