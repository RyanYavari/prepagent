import os
import datetime

import jwt
from fastapi import APIRouter, HTTPException, Query
from supabase import create_client

from models.user import AuthURLResponse, TokenResponse
from services.google_auth import build_authorization_url, exchange_code_for_tokens

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
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=7),
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
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to build auth URL: {e}"
        )


@router.get("/callback", response_model=TokenResponse)
async def auth_callback(
    code: str = Query(..., description="OAuth authorization code"),
):
    """Exchange OAuth code for tokens, upsert user, return session JWT."""
    # Exchange code for Google tokens + user info
    try:
        token_data = await exchange_code_for_tokens(code)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Token exchange failed: {e}"
        )

    email = token_data["email"]
    access_token = token_data["access_token"]
    refresh_token = token_data["refresh_token"]

    # Upsert user in Supabase
    try:
        supabase = _get_supabase()
        existing = (
            supabase.table("users")
            .select("id, email")
            .eq("email", email)
            .execute()
        )

        if existing.data:
            user = existing.data[0]
            supabase.table("users").update(
                {
                    "google_access_token": access_token,
                    "google_refresh_token": refresh_token,
                }
            ).eq("id", user["id"]).execute()
        else:
            result = (
                supabase.table("users")
                .insert(
                    {
                        "email": email,
                        "google_access_token": access_token,
                        "google_refresh_token": refresh_token,
                    }
                )
                .execute()
            )
            user = result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    session_token = _create_session_token(user["id"], email)
    return {"token": session_token, "email": email}
