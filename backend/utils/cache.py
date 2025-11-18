"""
Cache management utilities for cleaning up old files and safe file operations
"""

import fcntl
import logging
import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, TypeVar, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

T = TypeVar('T')


def cleanup_old_cache(
    cache_dir: Path,
    max_age_days: int = 7,
    max_size_mb: Optional[int] = None,
    dry_run: bool = False
) -> dict:
    """
    Clean up old cache files based on age and/or size limits.

    Args:
        cache_dir: Directory to clean
        max_age_days: Delete files older than this many days (default: 7)
        max_size_mb: Maximum total cache size in MB (optional)
        dry_run: If True, don't actually delete files, just report

    Returns:
        Dictionary with cleanup statistics
    """
    if not cache_dir.exists():
        logger.warning(f"Cache directory does not exist: {cache_dir}")
        return {"deleted": 0, "freed_mb": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    deleted_count = 0
    freed_bytes = 0

    # Collect all files with their metadata
    files = []
    for file_path in cache_dir.rglob("*"):
        if file_path.is_file():
            stat = file_path.stat()
            files.append({
                "path": file_path,
                "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                "size": stat.st_size
            })

    # Sort by modification time (oldest first)
    files.sort(key=lambda x: x["mtime"])

    # Delete old files
    for file_info in files:
        if file_info["mtime"] < cutoff:
            try:
                if not dry_run:
                    file_info["path"].unlink()
                deleted_count += 1
                freed_bytes += file_info["size"]
                logger.debug(f"Deleted old file: {file_info['path']}")
            except Exception as e:
                logger.error(f"Failed to delete {file_info['path']}: {e}")

    # If max_size specified, delete oldest files until under limit
    if max_size_mb is not None:
        max_bytes = max_size_mb * 1024 * 1024
        total_size = sum(f["size"] for f in files if f["path"].exists())

        for file_info in files:
            if total_size <= max_bytes:
                break
            if not file_info["path"].exists():
                continue  # Already deleted

            try:
                if not dry_run:
                    file_info["path"].unlink()
                deleted_count += 1
                freed_bytes += file_info["size"]
                total_size -= file_info["size"]
                logger.debug(f"Deleted for size limit: {file_info['path']}")
            except Exception as e:
                logger.error(f"Failed to delete {file_info['path']}: {e}")

    freed_mb = freed_bytes / (1024 * 1024)
    logger.info(
        f"Cache cleanup {'(dry run)' if dry_run else ''}: "
        f"deleted {deleted_count} files, freed {freed_mb:.2f} MB"
    )

    return {
        "deleted": deleted_count,
        "freed_mb": round(freed_mb, 2)
    }


def get_cache_stats(cache_dir: Path) -> dict:
    """
    Get statistics about cache directory.

    Args:
        cache_dir: Directory to analyze

    Returns:
        Dictionary with cache statistics
    """
    if not cache_dir.exists():
        return {
            "exists": False,
            "files": 0,
            "size_mb": 0,
            "oldest": None,
            "newest": None
        }

    files = list(cache_dir.rglob("*"))
    file_count = sum(1 for f in files if f.is_file())
    total_size = sum(f.stat().st_size for f in files if f.is_file())

    mtimes = [
        datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        for f in files if f.is_file()
    ]

    return {
        "exists": True,
        "files": file_count,
        "size_mb": round(total_size / (1024 * 1024), 2),
        "oldest": min(mtimes).isoformat() if mtimes else None,
        "newest": max(mtimes).isoformat() if mtimes else None
    }


@contextmanager
def file_lock(lock_path: Path, timeout: float = 30.0):
    """
    Context manager for file-based locking to prevent race conditions.

    Args:
        lock_path: Path to the lock file
        timeout: Maximum time to wait for lock in seconds (default: 30)

    Yields:
        File object with exclusive lock

    Raises:
        TimeoutError: If lock cannot be acquired within timeout

    Example:
        with file_lock(Path("cache/myfile.lock")):
            # Do atomic operations
            pass
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = None

    try:
        # Create or open lock file
        lock_file = open(lock_path, 'w')

        # Try to acquire exclusive lock with timeout
        import time
        start_time = time.time()
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.debug(f"Acquired lock: {lock_path}")
                break
            except IOError:
                if time.time() - start_time >= timeout:
                    raise TimeoutError(f"Could not acquire lock on {lock_path} within {timeout}s")
                time.sleep(0.1)

        yield lock_file

    finally:
        # Release lock and close file
        if lock_file is not None:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                logger.debug(f"Released lock: {lock_path}")
            except Exception as e:
                logger.error(f"Error releasing lock {lock_path}: {e}")

        # Clean up lock file
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception as e:
            logger.warning(f"Could not delete lock file {lock_path}: {e}")


def atomic_write_cache(
    cache_path: Path,
    content: bytes,
    use_lock: bool = True
) -> None:
    """
    Atomically write content to cache file with optional locking.

    This prevents partial writes and race conditions by:
    1. Writing to a temporary file
    2. Using file locking to prevent concurrent access
    3. Atomically renaming temp file to final path

    Args:
        cache_path: Final path for the cached file
        content: Binary content to write
        use_lock: Whether to use file locking (default: True)

    Example:
        atomic_write_cache(Path("cache/data.tif"), geotiff_bytes)
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Lock file path (same name with .lock extension)
    lock_path = cache_path.with_suffix(cache_path.suffix + '.lock')

    def write_atomic():
        # Create temporary file in same directory (for atomic rename)
        with tempfile.NamedTemporaryFile(
            mode='wb',
            dir=cache_path.parent,
            delete=False,
            prefix='.tmp_',
            suffix=cache_path.suffix
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            try:
                # Write content to temp file
                tmp_file.write(content)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())  # Ensure written to disk

                # Atomic rename (replaces existing file if present)
                tmp_path.rename(cache_path)
                logger.debug(f"Atomically wrote cache file: {cache_path}")

            except Exception as e:
                # Clean up temp file on error
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                raise e

    # Execute with or without locking
    if use_lock:
        with file_lock(lock_path):
            write_atomic()
    else:
        write_atomic()


def safe_cache_read(
    cache_path: Path,
    use_lock: bool = True
) -> Optional[bytes]:
    """
    Safely read cache file with optional locking.

    Args:
        cache_path: Path to cached file
        use_lock: Whether to use file locking (default: True)

    Returns:
        File content as bytes, or None if file doesn't exist

    Example:
        data = safe_cache_read(Path("cache/data.tif"))
        if data:
            process(data)
    """
    if not cache_path.exists():
        return None

    lock_path = cache_path.with_suffix(cache_path.suffix + '.lock')

    def read_file():
        try:
            with open(cache_path, 'rb') as f:
                return f.read()
        except FileNotFoundError:
            return None

    # Execute with or without locking
    if use_lock:
        with file_lock(lock_path):
            return read_file()
    else:
        return read_file()


def is_cache_valid(
    cache_path: Path,
    max_age_seconds: Optional[int] = None
) -> bool:
    """
    Check if a cache file is valid (exists and not expired).

    Args:
        cache_path: Path to cached file
        max_age_seconds: Maximum age in seconds (None = no age check)

    Returns:
        True if cache is valid, False otherwise

    Example:
        if is_cache_valid(cache_path, max_age_seconds=3600):  # 1 hour
            return read_cache(cache_path)
        else:
            data = fetch_fresh_data()
            write_cache(cache_path, data)
    """
    if not cache_path.exists():
        return False

    # If no TTL specified, just check existence
    if max_age_seconds is None:
        return True

    try:
        # Get file modification time
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        age = (datetime.now(timezone.utc) - mtime).total_seconds()

        is_valid = age <= max_age_seconds
        if not is_valid:
            logger.debug(f"Cache expired: {cache_path} (age: {age:.0f}s, max: {max_age_seconds}s)")

        return is_valid

    except Exception as e:
        logger.error(f"Error checking cache validity for {cache_path}: {e}")
        return False


def get_cache_age_seconds(cache_path: Path) -> Optional[float]:
    """
    Get the age of a cache file in seconds.

    Args:
        cache_path: Path to cached file

    Returns:
        Age in seconds, or None if file doesn't exist

    Example:
        age = get_cache_age_seconds(cache_path)
        if age and age > 3600:
            print("Cache is over 1 hour old")
    """
    if not cache_path.exists():
        return None

    try:
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - mtime).total_seconds()
    except Exception as e:
        logger.error(f"Error getting cache age for {cache_path}: {e}")
        return None


def touch_cache_file(cache_path: Path) -> bool:
    """
    Update the modification time of a cache file to "now".
    Useful for extending TTL of frequently accessed cache entries.

    Args:
        cache_path: Path to cached file

    Returns:
        True if successful, False otherwise

    Example:
        if is_cache_valid(cache_path, 3600):
            touch_cache_file(cache_path)  # Extend TTL
            return read_cache(cache_path)
    """
    if not cache_path.exists():
        return False

    try:
        cache_path.touch()
        logger.debug(f"Touched cache file: {cache_path}")
        return True
    except Exception as e:
        logger.error(f"Error touching cache file {cache_path}: {e}")
        return False


def cleanup_expired_cache(
    cache_dir: Path,
    max_age_seconds: int,
    file_pattern: str = "*",
    dry_run: bool = False
) -> dict:
    """
    Clean up expired cache files based on TTL.

    Args:
        cache_dir: Directory to clean
        max_age_seconds: Maximum age in seconds
        file_pattern: Glob pattern for files to check (default: "*")
        dry_run: If True, don't actually delete files

    Returns:
        Dictionary with cleanup statistics

    Example:
        # Delete all .tif files older than 7 days
        cleanup_expired_cache(
            Path("cache/ndvi"),
            max_age_seconds=7 * 24 * 3600,
            file_pattern="*.tif"
        )
    """
    if not cache_dir.exists():
        logger.warning(f"Cache directory does not exist: {cache_dir}")
        return {"deleted": 0, "freed_mb": 0}

    deleted_count = 0
    freed_bytes = 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)

    for file_path in cache_dir.rglob(file_pattern):
        if not file_path.is_file():
            continue

        try:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                size = file_path.stat().st_size
                if not dry_run:
                    file_path.unlink()
                deleted_count += 1
                freed_bytes += size
                logger.debug(f"Deleted expired cache file: {file_path} (age: {(datetime.now(timezone.utc) - mtime).total_seconds():.0f}s)")
        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}")

    freed_mb = freed_bytes / (1024 * 1024)
    logger.info(
        f"Expired cache cleanup {'(dry run)' if dry_run else ''}: "
        f"deleted {deleted_count} files, freed {freed_mb:.2f} MB"
    )

    return {
        "deleted": deleted_count,
        "freed_mb": round(freed_mb, 2)
    }
