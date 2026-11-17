"""Google Calendar connection endpoints (specs/calendar-detection.md).

Identity always comes from the JWT. Errors returned to the client are generic;
the real exception is logged server-side.
"""

import logging
import os
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from agents.pipeline import run_pipeline
from dependencies.auth import CurrentUser, get_current_user
from models.calendar import (
    CalendarCallbackRequest,
    CalendarConnectURL,
    CalendarStatus,
    DetectionConfirmRequest,
    DetectionConfirmResponse,
    DetectionItem,
    DetectionListResponse,
    SyncResponse,
)
from routers.limit_errors import briefing_blocked_http
from services.briefings import create_pending_briefing
from services.calendar import CalendarApiError
from services.calendar_sync import (
    CalendarNotConnectedError,
    CalendarReconnectRequired,
    briefing_fields,
    sync_user_calendar,
)
from services.google_auth import (
    CalendarConnectError,
    CalendarUnavailableError,
    InvalidOAuthStateError,
    build_calendar_authorization_url,
    exchange_calendar_code,
    revoke_token,
)
from services.limits import BriefingBlockedError, calendar_enabled
from services.log_safety import log_failure
from services.supabase_client import create_client
from services.token_crypto import TokenCryptoError, decrypt_token, encrypt_token

logger = logging.getLogger(__name__)


def _require_calendar_enabled() -> None:
    if not calendar_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Calendar is not available"
        )


router = APIRouter(
    prefix="/calendar",
    tags=["calendar"],
    dependencies=[Depends(_require_calendar_enabled)],
)


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


@router.get("/connect", response_model=CalendarConnectURL)
async def connect_calendar(user: CurrentUser = Depends(get_current_user)):
    """Start the separate calendar consent flow (calendar scope only)."""
    try:
        url, _ = build_calendar_authorization_url(user.user_id)
    except Exception:
        logger.exception("Failed to build calendar authorization URL")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start calendar connection",
        )
    return CalendarConnectURL(url=url)


@router.post("/callback", response_model=CalendarStatus)
async def calendar_callback(
    body: CalendarCallbackRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Finish the consent flow and store the encrypted refresh token."""
    try:
        tokens = await exchange_calendar_code(body.code, body.state, user.user_id)
    except InvalidOAuthStateError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state",
        )
    except CalendarConnectError:
        logger.exception("Calendar token exchange failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not connect calendar",
        )

    try:
        encrypted = encrypt_token(tokens["refresh_token"])
    except TokenCryptoError:
        logger.exception("Token encryption unavailable")
        # The consent was granted but we cannot store it: don't leave it live.
        await revoke_token(tokens["refresh_token"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error",
        )

    try:
        _get_supabase().table("calendar_connections").upsert(
            {
                "user_id": user.user_id,
                "encrypted_refresh_token": encrypted,
                "scope": tokens["scope"],
                "status": "active",
                "last_error_code": None,
            },
            on_conflict="user_id",
        ).execute()
    except Exception as exc:
        log_failure(logger, "Failed to store calendar connection", exc)
        await revoke_token(tokens["refresh_token"])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to connect calendar",
        )
    return CalendarStatus(connected=True, status="active")


@router.get("/status", response_model=CalendarStatus)
def calendar_status(user: CurrentUser = Depends(get_current_user)):
    try:
        result = (
            _get_supabase()
            .table("calendar_connections")
            .select("status, last_synced_at")
            .eq("user_id", user.user_id)
            .execute()
        )
    except Exception:
        logger.exception("Failed to read calendar status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read calendar status",
        )
    if not result.data:
        return CalendarStatus(connected=False)
    row = result.data[0]
    return CalendarStatus(
        connected=True,
        status=row["status"],
        last_synced_at=row.get("last_synced_at"),
    )


@router.delete("/connection", response_model=CalendarStatus)
async def disconnect_calendar(user: CurrentUser = Depends(get_current_user)):
    """Revoke at Google (best effort), then delete the connection and detections.

    Detections that already produced a briefing are kept (classification
    cleared) solely so a reconnect cannot create a second briefing.
    """
    supabase = _get_supabase()
    try:
        result = (
            supabase.table("calendar_connections")
            .select("encrypted_refresh_token")
            .eq("user_id", user.user_id)
            .execute()
        )
        if result.data:
            try:
                token = decrypt_token(result.data[0]["encrypted_refresh_token"])
                if not await revoke_token(token):
                    logger.warning("Google did not confirm calendar token revoke")
            except TokenCryptoError:
                logger.exception("Could not decrypt token for revoke")
            supabase.table("calendar_connections").delete().eq(
                "user_id", user.user_id
            ).execute()
        supabase.table("calendar_detections").delete().eq("user_id", user.user_id).neq(
            "status", "briefing_created"
        ).execute()
        supabase.table("calendar_detections").update({"classification": None}).eq(
            "user_id", user.user_id
        ).eq("status", "briefing_created").execute()
    except Exception as exc:
        log_failure(logger, "Failed to disconnect calendar", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect calendar",
        )
    return CalendarStatus(connected=False)


@router.post("/sync", response_model=SyncResponse)
async def sync_calendar(
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    """Scan upcoming events for interviews (on-demand polling)."""
    try:
        result = await sync_user_calendar(
            _get_supabase(),
            user.user_id,
            lambda **kw: background_tasks.add_task(run_pipeline, **kw),
        )
    except CalendarNotConnectedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Calendar not connected"
        )
    except CalendarReconnectRequired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Calendar connection expired. Please reconnect.",
        )
    except (CalendarUnavailableError, CalendarApiError):
        logger.exception("Calendar sync failed (Google unavailable)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Calendar service temporarily unavailable",
        )
    except TokenCryptoError:
        logger.exception("Token decryption unavailable")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error",
        )
    except Exception:
        logger.exception("Calendar sync failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Calendar sync failed",
        )
    return SyncResponse(**result.as_dict())


def _detection_item(row: dict) -> DetectionItem:
    c = row.get("classification") or {}
    return DetectionItem(
        id=row["id"],
        status=row["status"],
        event_start=row.get("event_start"),
        event_title=c.get("event_title"),
        confidence=c.get("confidence"),
        company=c.get("company"),
        role=c.get("role"),
        interviewer_names=c.get("interviewer_names") or [],
        reasons=c.get("reasons") or [],
    )


@router.get("/detections", response_model=DetectionListResponse)
def list_detections(user: CurrentUser = Depends(get_current_user)):
    """Detected interviews waiting for the user's confirmation."""
    try:
        result = (
            _get_supabase()
            .table("calendar_detections")
            .select("*")
            .eq("user_id", user.user_id)
            .eq("status", "needs_confirmation")
            .order("event_start")
            .execute()
        )
    except Exception as exc:
        log_failure(logger, "Failed to list detections", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list detections",
        )
    return DetectionListResponse(detections=[_detection_item(r) for r in result.data])


def _parse_detection_id(detection_id: str) -> str:
    try:
        return str(UUID(detection_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found"
        )


@router.post(
    "/detections/{detection_id}/confirm", response_model=DetectionConfirmResponse
)
def confirm_detection(
    detection_id: str,
    background_tasks: BackgroundTasks,
    body: DetectionConfirmRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
):
    """Create the briefing for a detected interview (idempotent)."""
    detection_id = _parse_detection_id(detection_id)
    body = body or DetectionConfirmRequest()
    supabase = _get_supabase()
    now = datetime.now(UTC).isoformat()

    try:
        # Atomic claim: only one concurrent confirm can move the row out of
        # needs_confirmation, so a double click yields one briefing.
        claimed = (
            supabase.table("calendar_detections")
            .update({"status": "processing", "updated_at": now})
            .eq("id", detection_id)
            .eq("user_id", user.user_id)
            .eq("status", "needs_confirmation")
            .execute()
        )
        if not claimed.data:
            existing = (
                supabase.table("calendar_detections")
                .select("status, briefing_id")
                .eq("id", detection_id)
                .eq("user_id", user.user_id)
                .execute()
            )
            if not existing.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Detection not found",
                )
            row = existing.data[0]
            if row["status"] == "briefing_created" and row.get("briefing_id"):
                return DetectionConfirmResponse(briefing_id=row["briefing_id"])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Detection is not awaiting confirmation",
            )
        row = claimed.data[0]
    except HTTPException:
        raise
    except Exception as exc:
        log_failure(logger, "Failed to confirm detection", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to confirm detection",
        )

    def _release():
        supabase.table("calendar_detections").update(
            {"status": "needs_confirmation"}
        ).eq("id", detection_id).execute()

    c = row.get("classification") or {}
    names = c.get("interviewer_names") or []
    try:
        fields = briefing_fields(
            body.company or c.get("company"),
            body.role if body.role is not None else c.get("role"),
            [body.interviewer] if body.interviewer else names,
            (row.get("event_start") or "")[:10] or None,
        )
    except ValueError:
        _release()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A company is required",
        )

    try:
        briefing = create_pending_briefing(
            supabase,
            user.user_id,
            fields,
            lambda **kw: background_tasks.add_task(run_pipeline, **kw),
        )
        supabase.table("calendar_detections").update(
            {"status": "briefing_created", "briefing_id": briefing["id"]}
        ).eq("id", detection_id).execute()
    except BriefingBlockedError as exc:
        # Kill switch or cap: nothing is lost, the detection goes back to the list.
        try:
            _release()
        except Exception as release_exc:
            log_failure(logger, "Failed to release detection after block", release_exc)
        raise briefing_blocked_http(exc)
    except Exception as exc:
        log_failure(logger, "Failed to create briefing from detection", exc)
        try:
            _release()
        except Exception as exc:
            log_failure(logger, "Failed to release detection after error", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create briefing",
        )
    return DetectionConfirmResponse(briefing_id=briefing["id"])


@router.post("/detections/{detection_id}/dismiss", response_model=DetectionItem)
def dismiss_detection(
    detection_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    detection_id = _parse_detection_id(detection_id)
    try:
        result = (
            _get_supabase()
            .table("calendar_detections")
            .update({"status": "dismissed"})
            .eq("id", detection_id)
            .eq("user_id", user.user_id)
            .eq("status", "needs_confirmation")
            .execute()
        )
    except Exception as exc:
        log_failure(logger, "Failed to dismiss detection", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to dismiss detection",
        )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found"
        )
    return _detection_item(result.data[0])
