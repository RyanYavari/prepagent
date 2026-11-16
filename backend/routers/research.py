import logging
import os
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from openai import OpenAIError

from agents.pipeline import run_pipeline
from dependencies.auth import CurrentUser, get_current_user
from models.briefing import (
    BriefingCreate,
    BriefingListItem,
    BriefingListResponse,
    BriefingResponse,
    BriefingSections,
    BriefingStatus,
)
from routers.limit_errors import briefing_blocked_http
from services.briefings import (
    create_pending_briefing,
    sweep_stale_pending,
    sweep_stale_running,
)
from services.embeddings import process_resume_embedding
from services.limits import (
    BriefingBlockedError,
    check_briefing_allowed,
    creation_lock,
)
from services.log_safety import log_failure
from services.supabase_client import create_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/briefings", tags=["briefings"])


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


@router.post("", response_model=BriefingResponse, status_code=status.HTTP_201_CREATED)
def create_briefing(
    body: BriefingCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
):
    """Create a briefing request (status 'pending') and run the pipeline in the background."""
    # Handlers run in a thread pool, so the cap check and the insert must be atomic or a
    # burst of parallel requests would all read the same count and overshoot. One worker
    # (a deployment requirement) makes a process-wide lock sufficient; it serializes
    # creates, which is fine at this scale and is also what bounds concurrent spend.
    with creation_lock:
        return _create_briefing(body, background_tasks, user)


def _create_briefing(
    body: BriefingCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
):
    supabase = _get_supabase()

    # Kill switch and caps come first: a blocked request must not spend an embedding
    # call or touch the user's stored resume.
    try:
        check_briefing_allowed(supabase, user.user_id)
    except BriefingBlockedError as exc:
        raise briefing_blocked_http(exc)
    except Exception:
        # Fail closed: if the caps cannot be checked, refuse rather than spend.
        logger.exception("Briefing limit check failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create briefing",
        )

    # If resume_text is provided, store it and create embeddings for RAG
    if body.resume_text:
        try:
            # Save raw resume text to user record
            supabase.table("users").update({"resume_text": body.resume_text}).eq(
                "id", user.user_id
            ).execute()

            # Chunk, embed, and store in pgvector
            process_resume_embedding(user.user_id, body.resume_text)

        except OpenAIError as exc:
            # OpenAI API failures should be temporary
            log_failure(logger, "Resume embedding failed (OpenAI)", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Embedding service temporarily unavailable",
            )
        except ValueError as exc:
            # Missing API key or invalid input
            log_failure(logger, "Resume embedding configuration error", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Configuration error",
            )
        except Exception as exc:
            log_failure(logger, "Failed to save resume", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save resume",
            )

    try:
        briefing = create_pending_briefing(
            supabase,
            user.user_id,
            body,
            lambda **kw: background_tasks.add_task(run_pipeline, **kw),
            check_limits=False,  # already checked above, before the embedding call
        )
    except BriefingBlockedError as exc:
        raise briefing_blocked_http(exc)
    except Exception as exc:
        log_failure(logger, "Failed to create briefing", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create briefing",
        )

    return BriefingResponse(
        id=briefing["id"],
        user_id=briefing["user_id"],
        company=briefing["company"],
        interviewer=briefing.get("interviewer"),
        role=briefing.get("role"),
        interview_date=briefing.get("interview_date"),
        status=BriefingStatus.pending,
        content=None,
        created_at=briefing["created_at"],
    )


@router.get("", response_model=BriefingListResponse)
def list_briefings(
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List briefings for the authenticated user, newest first."""
    supabase = _get_supabase()

    # Fail runs orphaned on `running` before listing; never let it break the list.
    try:
        sweep_stale_running(supabase, user.user_id)
        sweep_stale_pending(supabase, user.user_id)
    except Exception:
        logger.exception("Stale briefing sweep failed")

    try:
        result = (
            supabase.table("briefings")
            .select("id, company, interviewer, role, status, created_at")
            .eq("user_id", user.user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        count_result = (
            supabase.table("briefings")
            .select("id", count="exact")
            .eq("user_id", user.user_id)
            .execute()
        )
    except Exception:
        logger.exception("Failed to fetch briefings")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch briefings",
        )

    items = [BriefingListItem(**row) for row in result.data]
    total = count_result.count if count_result.count is not None else len(items)

    return BriefingListResponse(briefings=items, total=total)


@router.get("/{briefing_id}", response_model=BriefingResponse)
def get_briefing(
    briefing_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Get a specific briefing with full section content."""
    # Briefing ids are UUIDs; a malformed id can never match a row, and would
    # otherwise reach Postgres as an invalid uuid cast and surface as a 500.
    try:
        UUID(briefing_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Briefing not found",
        )

    supabase = _get_supabase()

    try:
        result = (
            supabase.table("briefings")
            .select("*")
            .eq("id", briefing_id)
            .eq("user_id", user.user_id)
            .execute()
        )
    except Exception:
        logger.exception("Failed to fetch briefing")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch briefing",
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Briefing not found",
        )

    briefing = result.data[0]

    content_data = briefing.get("content")
    content = None
    if content_data and isinstance(content_data, dict):
        content = BriefingSections(**content_data)

    return BriefingResponse(
        id=briefing["id"],
        user_id=briefing["user_id"],
        company=briefing["company"],
        interviewer=briefing.get("interviewer"),
        role=briefing.get("role"),
        interview_date=briefing.get("interview_date"),
        status=briefing["status"],
        content=content,
        failure_reason=briefing.get("failure_reason"),
        created_at=briefing["created_at"],
    )
