"""
Common API response schemas
"""

from typing import Literal
from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response schema"""
    status: Literal["error"] = "error"
    message: str = Field(..., description="Error message describing what went wrong")
    detail: str | None = Field(None, description="Additional error details")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "error",
                    "message": "No satellite data available",
                    "detail": "Try a different date range"
                }
            ]
        }
    }


class SuccessResponse(BaseModel):
    """Generic success response schema"""
    status: Literal["success"] = "success"
    message: str | None = Field(None, description="Success message")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "success",
                    "message": "Operation completed successfully"
                }
            ]
        }
    }
