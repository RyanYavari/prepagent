import asyncio
import datetime
import logging
import os

import jwt
from fastapi import APIRouter, HTTPException, Query

from models.user import AuthURLResponse, TokenResponse
from services.google_auth import (
    InvalidOAuthStateError,
    build_authorization_url,
    exchange_code_for_tokens,
)
from services.limits import email_allowed, signups_enabled
from services.log_safety import log_failure
from services.prod_config import get_jwt_secret
from services.supabase_client import create_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_NOT_AVAILABLE = "Sign-in is not available for this account"


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


def _create_session_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "iat": datetime.datetime.now(datetime.UTC),
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=7),
    }
    return jwt.encode(
        payload,
        get_jwt_secret(),
        algorithm="HS256",
    )


@router.get("/google", response_model=AuthURLResponse)
async def auth_google():
    """Generate Google OAuth consent URL."""
    try:
        url, state = build_authorization_url()
        return {"url": url, "state": state}
    except Exception:
        logger.exception("Failed to build auth URL")
        raise HTTPException(status_code=500, detail="Failed to build auth URL")


def _find_or_create_user(email: str) -> dict:
    """Existing user, or a new one when signups are open. Raises HTTPException."""
    try:
        supabase = _get_supabase()
        existing = (
            supabase.table("users").select("id, email").eq("email", email).execute()
        )

        if existing.data:
            return existing.data[0]
        if not signups_enabled():
            raise HTTPException(status_code=403, detail=_NOT_AVAILABLE)
        result = supabase.table("users").insert({"email": email}).execute()
        return result.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        log_failure(logger, "Database error during user upsert", exc)
        raise HTTPException(status_code=500, detail="Database error")


@router.get("/callback", response_model=TokenResponse)
async def auth_callback(
    code: str = Query(..., description="OAuth authorization code"),
    state: str = Query(..., description="OAuth state issued by /auth/google"),
):
    """Exchange OAuth code for identity, upsert user, return session JWT.

    Google tokens are used in memory only and never stored or logged.
    """
    # Exchange code for Google tokens + user info
    try:
        token_data = await exchange_code_for_tokens(code, state)
    except InvalidOAuthStateError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Token exchange failed")
        raise HTTPException(status_code=400, detail="Token exchange failed")

    email = token_data["email"]

    # Invite list / signup switch (specs/deployment.md). One generic refusal for both,
    # and the address is never logged or echoed.
    if not email_allowed(email):
        raise HTTPException(status_code=403, detail=_NOT_AVAILABLE)

    # Upsert user in Supabase (blocking client: off the event loop, see Slice 2)
    user = await asyncio.to_thread(_find_or_create_user, email)

    session_token = _create_session_token(user["id"], email)
    return {"token": session_token, "email": email}
