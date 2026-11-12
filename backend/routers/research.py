import os

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import create_client

from dependencies.auth import CurrentUser, get_current_user
from models.briefing import (
    BriefingCreate,
    BriefingListItem,
    BriefingListResponse,
    BriefingResponse,
    BriefingSections,
    BriefingStatus,
)

router = APIRouter(prefix="/briefings", tags=["briefings"])


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


@router.post("", response_model=BriefingResponse, status_code=status.HTTP_201_CREATED)
async def create_briefing(
    body: BriefingCreate,
    user: CurrentUser = Depends(get_current_user),
):
    """Create a new briefing request. Saves to Supabase with status 'pending'."""
    supabase = _get_supabase()

    row = {
        "user_id": user.user_id,
        "company": body.company,
        "interviewer": body.interviewer,
        "role": body.role,
        "interview_date": body.interview_date,
        "status": BriefingStatus.pending.value,
    }

    # If resume_text is provided, store it on the user record for RAG later
    if body.resume_text:
        try:
            supabase.table("users").update(
                {"resume_text": body.resume_text}
            ).eq("id", user.user_id).execute()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save resume: {e}",
            )

    try:
        result = supabase.table("briefings").insert(row).execute()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create briefing: {e}",
        )

    briefing = result.data[0]

    # TODO: Kick off LangGraph pipeline as a background task.

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
async def list_briefings(
    user: CurrentUser = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List briefings for the authenticated user, newest first."""
    supabase = _get_supabase()

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
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch briefings: {e}",
        )

    items = [BriefingListItem(**row) for row in result.data]
    total = count_result.count if count_result.count is not None else len(items)

    return BriefingListResponse(briefings=items, total=total)


@router.get("/{briefing_id}", response_model=BriefingResponse)
async def get_briefing(
    briefing_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Get a specific briefing with full section content."""
    supabase = _get_supabase()

    try:
        result = (
            supabase.table("briefings")
            .select("*")
            .eq("id", briefing_id)
            .eq("user_id", user.user_id)
            .execute()
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch briefing: {e}",
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
        created_at=briefing["created_at"],
    )
