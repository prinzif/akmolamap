"""
backend/cache_monitor.py - Cache size monitoring and alerting

Monitors cache directories and provides alerts when size limits are exceeded.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Statistics for a cache directory"""
    path: Path
    name: str
    total_files: int = 0
    total_size_bytes: int = 0
    oldest_file: Optional[str] = None
    oldest_file_age_days: Optional[float] = None
    newest_file: Optional[str] = None
    file_types: Dict[str, int] = None

    @property
    def size_mb(self) -> float:
        """Size in megabytes"""
        return self.total_size_bytes / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        """Size in gigabytes"""
        return self.total_size_bytes / (1024 * 1024 * 1024)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "name": self.name,
            "path": str(self.path),
            "total_files": self.total_files,
            "total_size_mb": round(self.size_mb, 2),
            "total_size_gb": round(self.size_gb, 3),
            "oldest_file": self.oldest_file,
            "oldest_file_age_days": round(self.oldest_file_age_days, 1) if self.oldest_file_age_days else None,
            "newest_file": self.newest_file,
            "file_types": self.file_types or {}
        }


class CacheMonitor:
    """
    Monitor cache directories for size and provide alerts.

    Provides:
    - Total size per cache directory
    - File counts by type
    - Oldest/newest files
    - Alert status based on thresholds
    """

    def __init__(
        self,
        cache_dirs: Dict[str, Path],
        max_size_mb: int = 5000,
        warning_threshold_pct: float = 80.0,
        critical_threshold_pct: float = 95.0
    ):
        """
        Initialize cache monitor.

        Args:
            cache_dirs: Dictionary of {name: path} for cache directories
            max_size_mb: Maximum total cache size in MB
            warning_threshold_pct: Warning threshold percentage
            critical_threshold_pct: Critical threshold percentage
        """
        self.cache_dirs = cache_dirs
        self.max_size_mb = max_size_mb
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.warning_threshold_pct = warning_threshold_pct
        self.critical_threshold_pct = critical_threshold_pct

    def scan_directory(self, path: Path, name: str) -> CacheStats:
        """
        Scan a cache directory and collect statistics.

        Args:
            path: Directory path to scan
            name: Human-readable name for the directory

        Returns:
            CacheStats object with collected statistics
        """
        if not path.exists():
            logger.warning(f"Cache directory does not exist: {path}")
            return CacheStats(path=path, name=name, file_types={})

        stats = CacheStats(path=path, name=name, file_types={})
        oldest_mtime = None
        newest_mtime = None
        now = datetime.now(timezone.utc).timestamp()

        try:
            for file_path in path.rglob("*"):
                if not file_path.is_file():
                    continue

                # Count file
                stats.total_files += 1

                # Add size
                try:
                    file_size = file_path.stat().st_size
                    stats.total_size_bytes += file_size
                except OSError as e:
                    logger.warning(f"Cannot stat file {file_path}: {e}")
                    continue

                # Track file type
                ext = file_path.suffix.lower() or "no_extension"
                if stats.file_types is None:
                    stats.file_types = {}
                stats.file_types[ext] = stats.file_types.get(ext, 0) + 1

                # Track oldest/newest
                try:
                    mtime = file_path.stat().st_mtime
                    if oldest_mtime is None or mtime < oldest_mtime:
                        oldest_mtime = mtime
                        stats.oldest_file = file_path.name
                        stats.oldest_file_age_days = (now - mtime) / 86400

                    if newest_mtime is None or mtime > newest_mtime:
                        newest_mtime = mtime
                        stats.newest_file = file_path.name
                except OSError as e:
                    logger.warning(f"Cannot get mtime for {file_path}: {e}")

        except Exception as e:
            logger.error(f"Error scanning directory {path}: {e}", exc_info=True)

        return stats

    def get_cache_status(self) -> dict:
        """
        Get current cache status with alerts.

        Returns:
            Dictionary with cache statistics and alert status
        """
        all_stats: List[CacheStats] = []
        total_size_bytes = 0

        # Scan all cache directories
        for name, path in self.cache_dirs.items():
            stats = self.scan_directory(path, name)
            all_stats.append(stats)
            total_size_bytes += stats.total_size_bytes

        # Calculate totals
        total_files = sum(s.total_files for s in all_stats)
        total_size_mb = total_size_bytes / (1024 * 1024)
        total_size_gb = total_size_bytes / (1024 * 1024 * 1024)
        usage_pct = (total_size_bytes / self.max_size_bytes * 100) if self.max_size_bytes > 0 else 0

        # Determine alert status
        if usage_pct >= self.critical_threshold_pct:
            alert_level = "critical"
            alert_message = f"Cache usage at {usage_pct:.1f}% (critical threshold: {self.critical_threshold_pct}%)"
        elif usage_pct >= self.warning_threshold_pct:
            alert_level = "warning"
            alert_message = f"Cache usage at {usage_pct:.1f}% (warning threshold: {self.warning_threshold_pct}%)"
        else:
            alert_level = "ok"
            alert_message = None

        return {
            "status": alert_level,
            "message": alert_message,
            "total": {
                "files": total_files,
                "size_mb": round(total_size_mb, 2),
                "size_gb": round(total_size_gb, 3),
                "usage_pct": round(usage_pct, 2),
                "max_size_mb": self.max_size_mb,
                "available_mb": round(self.max_size_mb - total_size_mb, 2),
            },
            "thresholds": {
                "warning_pct": self.warning_threshold_pct,
                "critical_pct": self.critical_threshold_pct,
            },
            "directories": [s.to_dict() for s in all_stats]
        }

    def get_cleanup_recommendations(self) -> dict:
        """
        Get recommendations for cache cleanup.

        Returns:
            Dictionary with cleanup recommendations
        """
        all_stats = [self.scan_directory(path, name) for name, path in self.cache_dirs.items()]
        recommendations = []

        for stats in all_stats:
            if stats.total_files == 0:
                continue

            # Recommend cleanup if directory is large
            if stats.size_mb > 500:
                recommendations.append({
                    "directory": stats.name,
                    "reason": f"Large cache size: {stats.size_mb:.1f} MB",
                    "action": f"Consider cleaning files older than {stats.oldest_file_age_days:.0f} days",
                    "priority": "high" if stats.size_mb > 1000 else "medium"
                })

            # Recommend cleanup if oldest file is very old
            if stats.oldest_file_age_days and stats.oldest_file_age_days > 30:
                recommendations.append({
                    "directory": stats.name,
                    "reason": f"Old files present (oldest: {stats.oldest_file_age_days:.0f} days)",
                    "action": "Consider running cache cleanup for files older than 30 days",
                    "priority": "medium" if stats.oldest_file_age_days > 60 else "low"
                })

        return {
            "has_recommendations": len(recommendations) > 0,
            "count": len(recommendations),
            "recommendations": recommendations
        }

    def cleanup_old_files(self, max_age_days: int, dry_run: bool = True) -> dict:
        """
        Clean up files older than specified age.

        Args:
            max_age_days: Maximum age in days
            dry_run: If True, only report what would be deleted

        Returns:
            Dictionary with cleanup results
        """
        import time

        cutoff_time = time.time() - (max_age_days * 86400)
        deleted_count = 0
        deleted_size = 0
        errors = []

        for name, path in self.cache_dirs.items():
            if not path.exists():
                continue

            try:
                for file_path in path.rglob("*"):
                    if not file_path.is_file():
                        continue

                    try:
                        mtime = file_path.stat().st_mtime
                        if mtime < cutoff_time:
                            file_size = file_path.stat().st_size
                            if not dry_run:
                                file_path.unlink()
                                logger.info(f"Deleted old cache file: {file_path.name}")
                            deleted_count += 1
                            deleted_size += file_size
                    except OSError as e:
                        errors.append(f"{file_path.name}: {str(e)}")
            except Exception as e:
                logger.error(f"Error cleaning directory {name}: {e}", exc_info=True)
                errors.append(f"{name}: {str(e)}")

        return {
            "dry_run": dry_run,
            "max_age_days": max_age_days,
            "deleted_files": deleted_count,
            "deleted_size_mb": round(deleted_size / (1024 * 1024), 2),
            "errors": errors
        }
