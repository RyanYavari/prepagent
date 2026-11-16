import os
import secrets
import threading
import time

import httpx
from google_auth_oauthlib.flow import Flow

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# PKCE: the code_verifier generated for the consent URL must be presented again
# at token exchange. It is kept server-side only, keyed by the OAuth `state`,
# single-use, with a short TTL. In-process storage: with multiple workers, move
# this to a shared store (e.g. a Supabase table) so any worker can serve the
# callback.
STATE_TTL_SECONDS = 600
_pending_verifiers: dict[str, tuple[str, float]] = {}
_pending_lock = threading.Lock()


class InvalidOAuthStateError(Exception):
    """OAuth state is unknown, expired, or already used."""


def _purge_expired(now: float) -> None:
    for key in [k for k, (_, exp) in _pending_verifiers.items() if exp <= now]:
        del _pending_verifiers[key]


def _store_code_verifier(state: str, verifier: str) -> None:
    now = time.monotonic()
    with _pending_lock:
        _purge_expired(now)
        _pending_verifiers[state] = (verifier, now + STATE_TTL_SECONDS)


def pop_code_verifier(state: str) -> str:
    """Return and remove the verifier for `state`; raise if unknown/expired."""
    now = time.monotonic()
    with _pending_lock:
        entry = _pending_verifiers.pop(state, None)
    if entry is None or entry[1] <= now:
        raise InvalidOAuthStateError("Invalid or expired OAuth state")
    return entry[0]


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
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )
    _store_code_verifier(state, flow.code_verifier)
    return authorization_url, state


async def exchange_code_for_tokens(code: str, state: str) -> dict:
    """Exchange authorization code for tokens and fetch user info.

    Raises InvalidOAuthStateError if `state` was not issued by us, expired, or
    was already used.

    Returns dict with access_token, refresh_token, email, and name.
    """
    code_verifier = pop_code_verifier(state)
    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=SCOPES,
        redirect_uri=_get_redirect_uri(),
        code_verifier=code_verifier,
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


async def refresh_access_token(refresh_token_value: str) -> str | None:
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
