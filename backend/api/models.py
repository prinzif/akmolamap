"""
Standardized API response models for consistent error handling
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class ErrorDetail(BaseModel):
    """Detailed error information"""
    code: str = Field(..., description="Error code (e.g., INVALID_BBOX, NOT_FOUND)")
    message: str = Field(..., description="User-friendly error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional technical details")


class APIResponse(BaseModel):
    """Standardized API response wrapper"""
    status: str = Field(..., description="success or error")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data (when successful)")
    error: Optional[ErrorDetail] = Field(None, description="Error details (when failed)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    api_version: str = Field(default="1.1.0", description="API version")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Response timestamp")
    request_id: Optional[str] = Field(None, description="Request tracking ID")


def success_response(
    data: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a standardized success response

    Args:
        data: Response data
        metadata: Optional metadata (e.g., pagination info)
        request_id: Optional request ID for tracking

    Returns:
        Standardized response dict
    """
    response = APIResponse(
        status="success",
        data=data,
        metadata=metadata,
        request_id=request_id
    )
    return response.model_dump(exclude_none=True)


def error_response(
    code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a standardized error response

    Args:
        code: Error code (INVALID_BBOX, NOT_FOUND, etc.)
        message: User-friendly error message
        details: Optional technical details
        request_id: Optional request ID for tracking

    Returns:
        Standardized error response dict
    """
    response = APIResponse(
        status="error",
        error=ErrorDetail(
            code=code,
            message=message,
            details=details
        ),
        request_id=request_id
    )
    return response.model_dump(exclude_none=True)


# Common error codes
class ErrorCodes:
    """Standard error code constants"""
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_BBOX = "INVALID_BBOX"
    INVALID_DATE = "INVALID_DATE"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    NOT_FOUND = "NOT_FOUND"
    NO_DATA_AVAILABLE = "NO_DATA_AVAILABLE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
