"""Calendar sync: read events, classify candidates, create/queue briefings.

`sync_user_calendar` is idempotent and transport-agnostic: today it is called
on demand (and optionally by an interval loop); a push-notification webhook
would call the same function (specs/calendar-detection.md, Decision 4).

Dedupe is enforced by the database: UNIQUE (user_id, google_event_id). Before
spending an LLM call, the sync *claims* the event by inserting a `processing`
row with insert-ignore semantics; only the call that actually inserted proceeds.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agents.calendar_detect import (
    MAX_AUTO_PER_SYNC,
    auto_threshold,
    classify_event,
    decide,
)
from models.briefing import BriefingCreate
from services.briefings import create_pending_briefing
from services.calendar import (
    CalendarApiError,
    NormalizedEvent,
    fetch_events,
    normalize_event,
    passes_prefilter,
)
from services.google_auth import (
    CalendarAuthError,
    refresh_calendar_access_token,
)
from services.token_crypto import decrypt_token

logger = logging.getLogger(__name__)

MAX_LLM_CALLS_PER_SYNC = 20
SYNC_COOLDOWN_SECONDS = 30
STALE_PROCESSING = timedelta(minutes=10)
DEFAULT_LOOKAHEAD_DAYS = 14


class CalendarNotConnectedError(Exception):
    pass


class CalendarReconnectRequired(Exception):
    """Connection is revoked/expired; the user must reconnect."""


@dataclass
class SyncResult:
    events_scanned: int = 0
    candidates: int = 0
    briefings_created: int = 0
    needs_confirmation: int = 0
    ignored: int = 0
    errors: int = 0
    truncated: bool = False
    skipped: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _lookahead_days() -> int:
    try:
        return max(1, int(os.getenv("CALENDAR_LOOKAHEAD_DAYS", DEFAULT_LOOKAHEAD_DAYS)))
    except ValueError:
        return DEFAULT_LOOKAHEAD_DAYS


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def briefing_fields(
    company: str | None,
    role: str | None,
    interviewer_names: list[str],
    start_date: str | None,
) -> BriefingCreate:
    """Build the same validated request `/prep/new` would (first interviewer only)."""
    return BriefingCreate(
        company=company or "",
        role=role,
        interviewer=interviewer_names[0] if interviewer_names else None,
        interview_date=start_date,
    )


def _claim(supabase: Any, user_id: str, event: NormalizedEvent, now: datetime) -> bool:
    """Try to take ownership of this event. True means we must process it."""
    table = supabase.table("calendar_detections")
    inserted = table.upsert(
        {
            "user_id": user_id,
            "google_event_id": event.id,
            "event_etag": event.etag,
            "event_start": event.start,
            "status": "processing",
        },
        on_conflict="user_id,google_event_id",
        ignore_duplicates=True,
    ).execute()
    if inserted.data:
        return True

    existing = (
        supabase.table("calendar_detections")
        .select("id, status, event_etag, updated_at")
        .eq("user_id", user_id)
        .eq("google_event_id", event.id)
        .execute()
    )
    if not existing.data:
        return False
    row = existing.data[0]
    status = row["status"]

    if status in ("briefing_created", "dismissed"):
        return False
    if status == "processing":
        updated = _parse_ts(row.get("updated_at"))
        if updated is None or now - updated < STALE_PROCESSING:
            return False
        guard = ("updated_at", row["updated_at"])
    elif row.get("event_etag") != event.etag:  # ignored / needs_confirmation, changed
        guard = ("event_etag", row.get("event_etag"))
    else:
        return False

    # Conditional update: of two racing syncs, only one matches the guard.
    update = (
        supabase.table("calendar_detections")
        .update(
            {
                "status": "processing",
                "event_etag": event.etag,
                "event_start": event.start,
                "updated_at": _iso(now),
            }
        )
        .eq("id", row["id"])
        .eq(guard[0], guard[1])
        .eq("status", status)
        .execute()
    )
    return bool(update.data)


def _finish(supabase: Any, user_id: str, event_id: str, values: dict, now: datetime):
    supabase.table("calendar_detections").update(
        {**values, "updated_at": _iso(now)}
    ).eq("user_id", user_id).eq("google_event_id", event_id).execute()


async def sync_user_calendar(
    supabase: Any,
    user_id: str,
    start_pipeline: Callable[..., Any],
    *,
    now: datetime | None = None,
    respect_cooldown: bool = True,
) -> SyncResult:
    """Sync one user's calendar. Raises CalendarNotConnectedError,
    CalendarReconnectRequired, CalendarUnavailableError or CalendarApiError;
    per-event failures are logged and counted, never raised."""
    now = now or datetime.now(UTC)
    conn_rows = (
        supabase.table("calendar_connections")
        .select("encrypted_refresh_token, status, last_synced_at")
        .eq("user_id", user_id)
        .execute()
    )
    if not conn_rows.data:
        raise CalendarNotConnectedError()
    conn = conn_rows.data[0]
    if conn["status"] != "active":
        raise CalendarReconnectRequired()

    last = _parse_ts(conn.get("last_synced_at"))
    if (
        respect_cooldown
        and last
        and now - last < timedelta(seconds=SYNC_COOLDOWN_SECONDS)
    ):
        return SyncResult(skipped="recently_synced")

    refresh_token = decrypt_token(conn["encrypted_refresh_token"])
    try:
        access_token = await refresh_calendar_access_token(refresh_token)
    except CalendarAuthError:
        supabase.table("calendar_connections").update(
            {"status": "revoked", "last_error_code": "invalid_grant"}
        ).eq("user_id", user_id).execute()
        raise CalendarReconnectRequired()

    raw_events, truncated = await fetch_events(access_token, now, _lookahead_days())
    result = SyncResult(events_scanned=len(raw_events), truncated=truncated)
    threshold = auto_threshold()
    llm_calls = 0
    autos = 0

    for raw in raw_events:
        event = normalize_event(raw, now)
        if event is None or not passes_prefilter(event):
            continue
        result.candidates += 1
        if llm_calls >= MAX_LLM_CALLS_PER_SYNC:
            continue  # left for the next sync
        try:
            if not _claim(supabase, user_id, event, now):
                continue
            llm_calls += 1
            try:
                detection = classify_event(event)
            except Exception:
                logger.exception("Calendar classification failed for an event")
                result.errors += 1
                # Release the claim so the event is retried on the next sync.
                supabase.table("calendar_detections").delete().eq(
                    "user_id", user_id
                ).eq("google_event_id", event.id).execute()
                continue

            decision = decide(detection, event, threshold=threshold, auto_so_far=autos)
            classification = decision.classification(event.title)
            if decision.action == "ignore":
                _finish(
                    supabase,
                    user_id,
                    event.id,
                    {"status": "ignored", "classification": classification},
                    now,
                )
                result.ignored += 1
            elif decision.action == "auto":
                try:
                    briefing = create_pending_briefing(
                        supabase,
                        user_id,
                        briefing_fields(
                            decision.company,
                            decision.role,
                            decision.interviewer_names,
                            event.start_date,
                        ),
                        start_pipeline,
                    )
                except Exception:
                    logger.exception("Auto-creating briefing failed; asking user")
                    _finish(
                        supabase,
                        user_id,
                        event.id,
                        {
                            "status": "needs_confirmation",
                            "classification": classification,
                        },
                        now,
                    )
                    result.needs_confirmation += 1
                    result.errors += 1
                else:
                    autos += 1
                    _finish(
                        supabase,
                        user_id,
                        event.id,
                        {
                            "status": "briefing_created",
                            "classification": classification,
                            "briefing_id": briefing["id"],
                        },
                        now,
                    )
                    result.briefings_created += 1
            else:
                _finish(
                    supabase,
                    user_id,
                    event.id,
                    {"status": "needs_confirmation", "classification": classification},
                    now,
                )
                result.needs_confirmation += 1
        except Exception:
            logger.exception("Calendar sync failed for an event")
            result.errors += 1

    supabase.table("calendar_connections").update(
        {"last_synced_at": _iso(now), "last_error_code": None}
    ).eq("user_id", user_id).execute()
    return result


__all__ = [
    "MAX_AUTO_PER_SYNC",
    "MAX_LLM_CALLS_PER_SYNC",
    "CalendarApiError",
    "CalendarNotConnectedError",
    "CalendarReconnectRequired",
    "SyncResult",
    "briefing_fields",
    "sync_user_calendar",
]
