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
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Calendar connect flow (specs/calendar-detection.md): exactly one scope, read-only
# events. Sign-in scopes above are intentionally separate.
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"

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


# --- Calendar connect flow (incremental, separate from sign-in) ---

# Same in-process caveat as _pending_verifiers. Entries also record the user who
# started the flow so another account cannot complete someone else's connect URL.
_pending_calendar: dict[str, tuple[str, str, float]] = {}


class CalendarConnectError(Exception):
    """The calendar consent could not be turned into a usable connection."""


class CalendarAuthError(Exception):
    """Google rejected the stored refresh token (revoked/expired): reconnect."""


class CalendarUnavailableError(Exception):
    """Transient Google/network failure: retry later, connection is fine."""


def _calendar_redirect_uri() -> str:
    return f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/calendar/callback"


def build_calendar_authorization_url(user_id: str) -> tuple[str, str]:
    """Consent URL for the calendar scope only, bound to `user_id`.

    include_granted_scopes is "false" on purpose: accounts that signed in before
    the sign-in scopes were trimmed may still hold gmail/drive grants, and
    incremental authorization ("true") would fold them into this token.
    """
    config = _get_client_config()
    config["web"]["redirect_uris"] = [_calendar_redirect_uri()]
    flow = Flow.from_client_config(
        config,
        scopes=[CALENDAR_SCOPE],
        redirect_uri=_calendar_redirect_uri(),
    )
    state = secrets.token_urlsafe(32)
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="false",
        prompt="consent",
        state=state,
    )
    now = time.monotonic()
    with _pending_lock:
        for key in [k for k, (_, _, exp) in _pending_calendar.items() if exp <= now]:
            del _pending_calendar[key]
        _pending_calendar[state] = (
            flow.code_verifier,
            user_id,
            now + STATE_TTL_SECONDS,
        )
    return url, state


def _pop_calendar_state(state: str, user_id: str) -> str:
    now = time.monotonic()
    with _pending_lock:
        entry = _pending_calendar.get(state)
        if entry is None or entry[2] <= now or entry[1] != user_id:
            # A state started by someone else is not consumed, so the owner can
            # still finish their own flow.
            if entry is not None and entry[2] <= now:
                del _pending_calendar[state]
            raise InvalidOAuthStateError("Invalid or expired OAuth state")
        del _pending_calendar[state]
    return entry[0]


async def revoke_token(token: str) -> bool:
    """Best-effort revoke at Google. Returns whether Google confirmed it."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(GOOGLE_REVOKE_URL, data={"token": token})
        return response.status_code == 200
    except httpx.HTTPError:
        return False


async def exchange_calendar_code(code: str, state: str, user_id: str) -> dict:
    """Exchange the calendar consent code; return {refresh_token, scope}.

    Raises InvalidOAuthStateError (unknown/expired/other user's state) or
    CalendarConnectError (exchange failed, no refresh token, or scope is not
    exactly the calendar scope; in the last two cases the token is revoked).
    """
    verifier = _pop_calendar_state(state, user_id)
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "redirect_uri": _calendar_redirect_uri(),
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
    except httpx.HTTPError as e:
        raise CalendarConnectError("Token exchange failed") from e
    if response.status_code != 200:
        raise CalendarConnectError(f"Token exchange failed ({response.status_code})")

    data = response.json()
    refresh_token = data.get("refresh_token")
    granted = set((data.get("scope") or "").split())
    if granted != {CALENDAR_SCOPE} or not refresh_token:
        # Never keep a token with the wrong scope set (or one we can't refresh).
        leaked = refresh_token or data.get("access_token")
        if leaked:
            await revoke_token(leaked)
        raise CalendarConnectError("Unexpected scope or missing refresh token")
    return {"refresh_token": refresh_token, "scope": CALENDAR_SCOPE}


async def refresh_calendar_access_token(refresh_token: str) -> str:
    """New access token (memory only). Distinguishes revoked from transient."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
    except httpx.HTTPError as e:
        raise CalendarUnavailableError("Token refresh network error") from e
    if response.status_code == 200:
        token = response.json().get("access_token")
        if token:
            return token
        raise CalendarUnavailableError("Token refresh returned no access token")
    if response.status_code == 400:
        try:
            error = response.json().get("error")
        except ValueError:
            error = None
        if error == "invalid_grant":
            raise CalendarAuthError("Refresh token revoked or expired")
    raise CalendarUnavailableError(f"Token refresh failed ({response.status_code})")
