import os
import secrets
from typing import Optional

from google_auth_oauthlib.flow import Flow
import httpx

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def _get_redirect_uri() -> str:
    return f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/auth/callback"


def _get_client_config() -> dict:
    return {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_get_redirect_uri()],
        }
    }


def build_authorization_url() -> tuple[str, str]:
    """Generate Google OAuth consent URL and CSRF state token."""
    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=_get_redirect_uri(),
    )
    state = secrets.token_urlsafe(32)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return authorization_url, state


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange authorization code for tokens and fetch user info.

    Returns dict with access_token, refresh_token, email, and name.
    """
    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=_get_redirect_uri(),
    )
    flow.fetch_token(code=code)

    credentials = flow.credentials

    async with httpx.AsyncClient() as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {credentials.token}"},
        )
        response.raise_for_status()
        user_info = response.json()

    return {
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "email": user_info["email"],
        "name": user_info.get("name", ""),
    }


async def refresh_access_token(refresh_token_value: str) -> Optional[str]:
    """Use a refresh token to get a new access token. Returns None on failure."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                "refresh_token": refresh_token_value,
                "grant_type": "refresh_token",
            },
        )
        if response.status_code == 200:
            return response.json().get("access_token")
        return None
