"""Shared briefing creation used by every entry point.

`POST /briefings` and the calendar detection flow both create a `pending`
briefing and start the pipeline through this one function, so what an event's
text can trigger is exactly what a manual request can trigger.
"""

from collections.abc import Callable
from typing import Any

from models.briefing import BriefingCreate, BriefingStatus


def create_pending_briefing(
    supabase: Any,
    user_id: str,
    fields: BriefingCreate,
    start_pipeline: Callable[..., Any],
) -> dict:
    """Insert a pending briefing for `user_id` and start the pipeline.

    `start_pipeline(**kwargs)` is supplied by the caller (typically
    `partial(background_tasks.add_task, run_pipeline)`). resume_text is not
    handled here; callers that accept it embed it first.

    Raises whatever the insert raises; callers map that to a generic error.
    """
    row = {
        "user_id": user_id,
        "company": fields.company,
        "interviewer": fields.interviewer,
        "role": fields.role,
        "interview_date": fields.interview_date,
        "status": BriefingStatus.pending.value,
    }
    result = supabase.table("briefings").insert(row).execute()
    briefing = result.data[0]

    start_pipeline(
        briefing_id=briefing["id"],
        user_id=user_id,
        company=briefing["company"],
        interviewer=briefing.get("interviewer"),
        role=briefing.get("role"),
    )
    return briefing
