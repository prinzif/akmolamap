"""
Copernicus Data Space Ecosystem (CDSE) authentication module
"""

import os
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

# CDSE credentials
CDSE_CLIENT_ID = os.getenv("CDSE_CLIENT_ID")
CDSE_CLIENT_SECRET = os.getenv("CDSE_CLIENT_SECRET")
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass


def get_cdse_token() -> str:
    """
    Obtain OAuth2 token for Copernicus Data Space Ecosystem.

    Returns:
        str: Access token

    Raises:
        AuthenticationError: When authentication fails
    """
    if not CDSE_CLIENT_ID or not CDSE_CLIENT_SECRET:
        raise AuthenticationError("CDSE credentials not configured in .env file")

    data = {
        "grant_type": "client_credentials",
        "client_id": CDSE_CLIENT_ID,
        "client_secret": CDSE_CLIENT_SECRET,
    }

    try:
        response = requests.post(CDSE_TOKEN_URL, data=data, timeout=30)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise AuthenticationError("No access_token in response")

        logger.debug("Successfully obtained CDSE access token")
        return access_token

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to obtain CDSE token: {e}")
        raise AuthenticationError(f"Token request failed: {e}") from e
    except (KeyError, ValueError) as e:
        logger.error(f"Invalid token response: {e}")
        raise AuthenticationError(f"Invalid token response: {e}") from e
