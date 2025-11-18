"""
backend/metrics.py - Simple in-memory metrics collection

Tracks API usage, response times, and error rates without external dependencies.
For production, consider migrating to Prometheus or similar.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from threading import Lock


@dataclass
class EndpointMetrics:
    """Metrics for a single endpoint"""
    path: str
    total_requests: int = 0
    success_count: int = 0
    error_count: int = 0
    total_time_ms: float = 0.0
    min_time_ms: float = float('inf')
    max_time_ms: float = 0.0
    status_codes: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    last_request: Optional[str] = None

    @property
    def avg_time_ms(self) -> float:
        """Calculate average response time"""
        if self.total_requests == 0:
            return 0.0
        return self.total_time_ms / self.total_requests

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.success_count / self.total_requests) * 100

    @property
    def error_rate(self) -> float:
        """Calculate error rate percentage"""
        if self.total_requests == 0:
            return 0.0
        return (self.error_count / self.total_requests) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "path": self.path,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "success_rate": round(self.success_rate, 2),
            "error_rate": round(self.error_rate, 2),
            "avg_time_ms": round(self.avg_time_ms, 2),
            "min_time_ms": round(self.min_time_ms, 2) if self.min_time_ms != float('inf') else 0.0,
            "max_time_ms": round(self.max_time_ms, 2),
            "status_codes": dict(self.status_codes),
            "last_request": self.last_request
        }


class MetricsCollector:
    """
    Thread-safe metrics collector for API endpoints.

    Collects:
    - Request counts
    - Response times (min/max/avg)
    - Status code distribution
    - Success/error rates
    - Last request timestamp
    """

    def __init__(self):
        self._metrics: Dict[str, EndpointMetrics] = {}
        self._lock = Lock()
        self._start_time = datetime.now(timezone.utc)
        self._total_requests = 0
        self._slow_requests: List[Dict] = []  # Last 100 slow requests
        self._max_slow_requests = 100

    def record_request(
        self,
        path: str,
        method: str,
        status_code: int,
        response_time_ms: float,
        request_id: str
    ):
        """
        Record metrics for a completed request.

        Args:
            path: API endpoint path (without query params)
            method: HTTP method (GET, POST, etc.)
            status_code: HTTP status code
            response_time_ms: Response time in milliseconds
            request_id: Unique request identifier
        """
        # Normalize path (group dynamic segments)
        normalized_path = self._normalize_path(path)
        key = f"{method} {normalized_path}"

        with self._lock:
            # Update endpoint metrics
            if key not in self._metrics:
                self._metrics[key] = EndpointMetrics(path=key)

            metrics = self._metrics[key]
            metrics.total_requests += 1
            metrics.total_time_ms += response_time_ms
            metrics.min_time_ms = min(metrics.min_time_ms, response_time_ms)
            metrics.max_time_ms = max(metrics.max_time_ms, response_time_ms)
            metrics.status_codes[status_code] += 1
            metrics.last_request = datetime.now(timezone.utc).isoformat()

            if 200 <= status_code < 400:
                metrics.success_count += 1
            else:
                metrics.error_count += 1

            # Update global counters
            self._total_requests += 1

            # Track slow requests (if > 1 second)
            if response_time_ms > 1000:
                self._slow_requests.append({
                    "path": key,
                    "status_code": status_code,
                    "time_ms": round(response_time_ms, 2),
                    "request_id": request_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                # Keep only last N slow requests
                if len(self._slow_requests) > self._max_slow_requests:
                    self._slow_requests = self._slow_requests[-self._max_slow_requests:]

    def _normalize_path(self, path: str) -> str:
        """
        Normalize path to group similar endpoints.

        Examples:
            /api/v1/ndvi/geotiff -> /api/v1/ndvi/geotiff
            /static/ndvi/abc123.tif -> /static/ndvi/{file}
            /titiler/cog/info -> /titiler/{service}
        """
        parts = path.split('/')

        # Handle static file paths
        if len(parts) > 2 and parts[1] == 'static':
            return f"/{parts[1]}/{parts[2]}/{{file}}"

        # Handle titiler proxy paths
        if len(parts) > 1 and parts[1] == 'titiler':
            return f"/{parts[1]}/{{service}}"

        # Return as-is for API endpoints
        return path

    def get_metrics(self) -> dict:
        """Get all collected metrics"""
        with self._lock:
            uptime_seconds = (datetime.now(timezone.utc) - self._start_time).total_seconds()

            # Calculate global stats
            total_success = sum(m.success_count for m in self._metrics.values())
            total_errors = sum(m.error_count for m in self._metrics.values())
            total_time = sum(m.total_time_ms for m in self._metrics.values())

            global_avg_time = (total_time / self._total_requests) if self._total_requests > 0 else 0.0
            global_success_rate = (total_success / self._total_requests * 100) if self._total_requests > 0 else 0.0

            # Sort endpoints by request count
            sorted_endpoints = sorted(
                self._metrics.values(),
                key=lambda m: m.total_requests,
                reverse=True
            )

            return {
                "collector": {
                    "started_at": self._start_time.isoformat(),
                    "uptime_seconds": round(uptime_seconds, 2),
                    "uptime_hours": round(uptime_seconds / 3600, 2),
                },
                "global": {
                    "total_requests": self._total_requests,
                    "success_count": total_success,
                    "error_count": total_errors,
                    "success_rate": round(global_success_rate, 2),
                    "avg_response_time_ms": round(global_avg_time, 2),
                    "requests_per_second": round(self._total_requests / uptime_seconds, 2) if uptime_seconds > 0 else 0.0,
                },
                "endpoints": [m.to_dict() for m in sorted_endpoints],
                "slow_requests": self._slow_requests[-20:]  # Last 20 slow requests
            }

    def get_endpoint_metrics(self, path: str, method: str = "GET") -> Optional[dict]:
        """Get metrics for a specific endpoint"""
        key = f"{method} {path}"
        with self._lock:
            metrics = self._metrics.get(key)
            return metrics.to_dict() if metrics else None

    def reset_metrics(self):
        """Reset all metrics (useful for testing or periodic resets)"""
        with self._lock:
            self._metrics.clear()
            self._start_time = datetime.now(timezone.utc)
            self._total_requests = 0
            self._slow_requests.clear()

    def get_summary(self) -> dict:
        """Get a summary of key metrics"""
        with self._lock:
            if self._total_requests == 0:
                return {
                    "message": "No requests recorded yet",
                    "total_requests": 0
                }

            total_success = sum(m.success_count for m in self._metrics.values())
            total_errors = sum(m.error_count for m in self._metrics.values())

            # Top 5 endpoints by request count
            top_endpoints = sorted(
                self._metrics.values(),
                key=lambda m: m.total_requests,
                reverse=True
            )[:5]

            # Slowest endpoints by average time
            slowest_endpoints = sorted(
                self._metrics.values(),
                key=lambda m: m.avg_time_ms,
                reverse=True
            )[:5]

            return {
                "total_requests": self._total_requests,
                "success_rate": round((total_success / self._total_requests * 100), 2),
                "error_rate": round((total_errors / self._total_requests * 100), 2),
                "unique_endpoints": len(self._metrics),
                "slow_requests_count": len(self._slow_requests),
                "top_endpoints": [
                    {"path": m.path, "requests": m.total_requests}
                    for m in top_endpoints
                ],
                "slowest_endpoints": [
                    {"path": m.path, "avg_time_ms": round(m.avg_time_ms, 2)}
                    for m in slowest_endpoints
                ]
            }


# Global metrics collector instance
metrics_collector = MetricsCollector()
