"""Authentication modules for external services"""

from backend.auth.cdse_auth import get_cdse_token, AuthenticationError

__all__ = [
    "get_cdse_token",
    "AuthenticationError",
]
