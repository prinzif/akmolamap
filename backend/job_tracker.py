"""
backend/job_tracker.py - Job progress tracking for long-running operations

Tracks status and progress of long-running jobs like BIOPAR processing.
In-memory implementation, can be extended to use Redis for distributed systems.
"""

import logging
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, List
from threading import Lock

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job status enumeration"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobProgress:
    """Progress information for a job"""
    job_id: str
    job_type: str  # e.g., "biopar_geotiff", "ndvi_timeline"
    status: JobStatus = JobStatus.PENDING
    progress_pct: float = 0.0
    current_step: Optional[str] = None
    total_steps: Optional[int] = None
    completed_steps: int = 0
    message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "status": self.status.value,
            "progress_pct": round(self.progress_pct, 1),
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata
        }


class JobTracker:
    """
    Thread-safe job tracker for long-running operations.

    Provides:
    - Job creation and tracking
    - Progress updates
    - Status queries
    - Job history (last N jobs)
    """

    def __init__(self, max_history: int = 1000):
        """
        Initialize job tracker.

        Args:
            max_history: Maximum number of completed jobs to keep in history
        """
        self._jobs: Dict[str, JobProgress] = {}
        self._lock = Lock()
        self._max_history = max_history
        self._completed_count = 0
        self._failed_count = 0

    def create_job(
        self,
        job_id: str,
        job_type: str,
        total_steps: Optional[int] = None,
        metadata: Optional[Dict] = None
    ) -> JobProgress:
        """
        Create a new job for tracking.

        Args:
            job_id: Unique identifier for the job
            job_type: Type of job (e.g., "biopar_geotiff")
            total_steps: Total number of steps (if known)
            metadata: Additional metadata

        Returns:
            JobProgress object
        """
        with self._lock:
            job = JobProgress(
                job_id=job_id,
                job_type=job_type,
                total_steps=total_steps,
                metadata=metadata or {}
            )
            self._jobs[job_id] = job
            logger.info(f"Created job: {job_id} ({job_type})")
            return job

    def start_job(self, job_id: str, message: Optional[str] = None):
        """
        Mark job as started.

        Args:
            job_id: Job identifier
            message: Optional status message
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job not found: {job_id}")

            job = self._jobs[job_id]
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc).isoformat()
            if message:
                job.message = message
            logger.info(f"Started job: {job_id}")

    def update_progress(
        self,
        job_id: str,
        progress_pct: Optional[float] = None,
        current_step: Optional[str] = None,
        message: Optional[str] = None,
        increment_steps: bool = False
    ):
        """
        Update job progress.

        Args:
            job_id: Job identifier
            progress_pct: Progress percentage (0-100)
            current_step: Description of current step
            message: Status message
            increment_steps: If True, increment completed_steps counter
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job not found: {job_id}")

            job = self._jobs[job_id]

            if progress_pct is not None:
                job.progress_pct = min(100.0, max(0.0, progress_pct))

            if current_step is not None:
                job.current_step = current_step

            if message is not None:
                job.message = message

            if increment_steps:
                job.completed_steps += 1
                # Auto-calculate progress if total_steps is known
                if job.total_steps and job.total_steps > 0:
                    job.progress_pct = (job.completed_steps / job.total_steps) * 100

    def complete_job(
        self,
        job_id: str,
        result: Optional[dict] = None,
        message: Optional[str] = None
    ):
        """
        Mark job as completed.

        Args:
            job_id: Job identifier
            result: Job result data
            message: Completion message
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job not found: {job_id}")

            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.progress_pct = 100.0
            job.completed_at = datetime.now(timezone.utc).isoformat()
            if result is not None:
                job.result = result
            if message:
                job.message = message
            self._completed_count += 1
            logger.info(f"Completed job: {job_id}")

            self._cleanup_old_jobs()

    def fail_job(self, job_id: str, error: str, message: Optional[str] = None):
        """
        Mark job as failed.

        Args:
            job_id: Job identifier
            error: Error message
            message: Additional context message
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job not found: {job_id}")

            job = self._jobs[job_id]
            job.status = JobStatus.FAILED
            job.error = error
            job.completed_at = datetime.now(timezone.utc).isoformat()
            if message:
                job.message = message
            self._failed_count += 1
            logger.error(f"Failed job: {job_id} - {error}")

            self._cleanup_old_jobs()

    def cancel_job(self, job_id: str, message: Optional[str] = None):
        """
        Cancel a running job.

        Args:
            job_id: Job identifier
            message: Cancellation reason
        """
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError(f"Job not found: {job_id}")

            job = self._jobs[job_id]
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc).isoformat()
            if message:
                job.message = message
            logger.info(f"Cancelled job: {job_id}")

    def get_job(self, job_id: str) -> Optional[dict]:
        """
        Get job status.

        Args:
            job_id: Job identifier

        Returns:
            Job status dictionary or None if not found
        """
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        job_type: Optional[str] = None,
        limit: int = 100
    ) -> List[dict]:
        """
        List jobs with optional filtering.

        Args:
            status: Filter by status
            job_type: Filter by job type
            limit: Maximum number of jobs to return

        Returns:
            List of job dictionaries
        """
        with self._lock:
            jobs = list(self._jobs.values())

            # Filter by status
            if status:
                jobs = [j for j in jobs if j.status == status]

            # Filter by type
            if job_type:
                jobs = [j for j in jobs if j.job_type == job_type]

            # Sort by created_at (newest first)
            jobs.sort(key=lambda j: j.created_at, reverse=True)

            # Limit results
            jobs = jobs[:limit]

            return [j.to_dict() for j in jobs]

    def get_stats(self) -> dict:
        """
        Get tracker statistics.

        Returns:
            Dictionary with tracker stats
        """
        with self._lock:
            status_counts = {}
            for status in JobStatus:
                count = sum(1 for j in self._jobs.values() if j.status == status)
                status_counts[status.value] = count

            return {
                "total_jobs": len(self._jobs),
                "completed_total": self._completed_count,
                "failed_total": self._failed_count,
                "status_counts": status_counts,
                "max_history": self._max_history
            }

    def _cleanup_old_jobs(self):
        """Remove old completed/failed jobs if exceeding max_history"""
        # Get all completed/failed/cancelled jobs
        finished_jobs = [
            (job_id, job)
            for job_id, job in self._jobs.items()
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]

        # If exceeding limit, remove oldest
        if len(finished_jobs) > self._max_history:
            # Sort by completion time
            finished_jobs.sort(key=lambda x: x[1].completed_at or "")
            to_remove = len(finished_jobs) - self._max_history

            for job_id, _ in finished_jobs[:to_remove]:
                del self._jobs[job_id]
                logger.debug(f"Removed old job from history: {job_id}")

    def clear_completed(self, older_than_hours: Optional[int] = None):
        """
        Clear completed jobs.

        Args:
            older_than_hours: Only clear jobs completed more than N hours ago
        """
        from datetime import timedelta

        with self._lock:
            if older_than_hours:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
                cutoff_str = cutoff.isoformat()

                to_remove = [
                    job_id
                    for job_id, job in self._jobs.items()
                    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
                    and job.completed_at
                    and job.completed_at < cutoff_str
                ]
            else:
                to_remove = [
                    job_id
                    for job_id, job in self._jobs.items()
                    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
                ]

            for job_id in to_remove:
                del self._jobs[job_id]

            logger.info(f"Cleared {len(to_remove)} completed jobs")
            return len(to_remove)


# Global job tracker instance
job_tracker = JobTracker(max_history=1000)
