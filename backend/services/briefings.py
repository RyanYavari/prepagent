"""Shared briefing creation used by every entry point.

`POST /briefings` and the calendar detection flow both create a `pending`
briefing and start the pipeline through this one function, so what an event's
text can trigger is exactly what a manual request can trigger.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from models.briefing import BriefingCreate, BriefingStatus
from services.net_config import env_float
from services.supabase_client import execute

logger = logging.getLogger(__name__)


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


REASON_STALE = "This briefing was interrupted and did not finish. Please try again."


def sweep_stale_running(supabase: Any, user_id: str | None = None) -> int:
    """
    Mark briefings stuck on `running` for longer than STALE_RUNNING_MINUTES as failed.

    A run stays `running` only while its pipeline is alive (bounded by the pipeline
    deadline), so anything older than the threshold was orphaned, for example by a
    server restart. `user_id` scopes the sweep to one user (used when listing); the
    startup sweep covers everyone. Returns the number of rows changed.

    If the `failure_reason` column does not exist yet (migration 007) the update is
    retried with the status alone.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=env_float("STALE_RUNNING_MINUTES"))

    def run(fields: dict[str, Any]) -> Any:
        query = (
            supabase.table("briefings")
            .update(fields)
            .eq("status", BriefingStatus.running.value)
            .lt("created_at", cutoff.isoformat())
        )
        if user_id is not None:
            query = query.eq("user_id", user_id)
        return execute(query)

    failed = BriefingStatus.failed.value
    try:
        result = run({"status": failed, "failure_reason": REASON_STALE})
    except Exception:  # noqa: BLE001 - e.g. failure_reason column missing: status only
        result = run({"status": failed})

    count = len(result.data or [])
    if count:
        logger.warning("Marked %d stale running briefing(s) as failed", count)
    return count
