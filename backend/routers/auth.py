import datetime
import logging
import os

import jwt
from fastapi import APIRouter, HTTPException, Query
from supabase import create_client

from models.user import AuthURLResponse, TokenResponse
from services.google_auth import (
    InvalidOAuthStateError,
    build_authorization_url,
    exchange_code_for_tokens,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


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
        os.getenv("JWT_SECRET", "dev-secret-change-me"),
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

    # Upsert user in Supabase
    try:
        supabase = _get_supabase()
        existing = (
            supabase.table("users").select("id, email").eq("email", email).execute()
        )

        if existing.data:
            user = existing.data[0]
        else:
            result = supabase.table("users").insert({"email": email}).execute()
            user = result.data[0]
    except Exception:
        logger.exception("Database error during user upsert")
        raise HTTPException(status_code=500, detail="Database error")

    session_token = _create_session_token(user["id"], email)
    return {"token": session_token, "email": email}
