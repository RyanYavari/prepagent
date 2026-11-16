"""Optional in-process interval poller (CALENDAR_POLL_INTERVAL_MINUTES, default off).

Runs the same `sync_user_calendar` the on-demand endpoint uses, over every
active connection. Single-process only: with multiple workers each would poll
(harmless, since dedupe is enforced by the database, but wasteful). The
production trigger is push notifications (specs/calendar-detection.md).
"""

import asyncio
import logging
import os
from typing import Any

from services.calendar_sync import sync_user_calendar

logger = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()


def poll_interval_minutes() -> float:
    try:
        return max(0.0, float(os.getenv("CALENDAR_POLL_INTERVAL_MINUTES", "0")))
    except ValueError:
        return 0.0


def _start_pipeline(**kwargs: Any) -> None:
    """Run the (blocking) pipeline off the event loop, keeping a task reference."""
    from agents.pipeline import run_pipeline

    task = asyncio.get_running_loop().create_task(
        asyncio.to_thread(run_pipeline, **kwargs)
    )
    _background.add(task)
    task.add_done_callback(_background.discard)


async def poll_once(supabase: Any) -> None:
    """Sync every active connection; one user's failure never stops the rest."""
    rows = (
        supabase.table("calendar_connections")
        .select("user_id")
        .eq("status", "active")
        .execute()
    )
    for row in rows.data or []:
        try:
            await sync_user_calendar(supabase, row["user_id"], _start_pipeline)
        except Exception:
            logger.exception("Calendar poll failed for a user")


async def run_poller(get_supabase: Any, interval_minutes: float) -> None:
    while True:
        try:
            await poll_once(get_supabase())
        except Exception:
            logger.exception("Calendar poll cycle failed")
        await asyncio.sleep(interval_minutes * 60)
