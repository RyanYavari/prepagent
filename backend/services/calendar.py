"""Google Calendar read access and the sync loop (specs/calendar-detection.md).

Direct Google API via httpx (no MCP; see the spec's Decision 5). Event text is
attacker-controllable, so this module only normalizes/truncates it; deciding
what to do with it lives in agents/calendar_detect.py.
"""

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from services.net_config import aretry_call, env_float, env_int

logger = logging.getLogger(__name__)

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
MAX_EVENTS = 100
TITLE_MAX = 200
DESCRIPTION_MAX = 2000
MAX_ATTENDEES = 10

KEYWORDS = re.compile(
    r"\b(interview|screen|screening|on-?site|technical|panel|recruiter|"
    r"hiring manager|intro call|chat with)\b",
    re.IGNORECASE,
)
SCHEDULING_DOMAINS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "calendly.com",
    "goodtime.io",
)


class CalendarApiError(Exception):
    """Google Calendar API returned an error or could not be reached."""


@dataclass
class Attendee:
    name: str
    domain: str


@dataclass
class NormalizedEvent:
    id: str
    etag: str
    start: str  # ISO datetime as given by Google
    title: str
    description: str
    organizer_name: str
    organizer_domain: str
    attendees: list[Attendee] = field(default_factory=list)
    user_response: str = "needsAction"  # accepted | declined | tentative | needsAction

    @property
    def start_date(self) -> str:
        return self.start[:10]


def _strip_html(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", text)).split())


def _domain(email: str | None) -> str:
    return (email or "").rpartition("@")[2].lower()


async def fetch_events(
    access_token: str, now: datetime, lookahead_days: int
) -> tuple[list[dict], bool]:
    """Fetch the first page of upcoming primary-calendar events.

    Returns (raw events, truncated). The Google response body is never exposed
    to callers; failures raise CalendarApiError with a generic message.
    """
    params: dict[str, Any] = {
        "timeMin": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "timeMax": (now + timedelta(days=lookahead_days))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": MAX_EVENTS,
    }
    try:

        async def attempt() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=env_float("GOOGLE_TIMEOUT_SECONDS")
            ) as client:
                return await client.get(
                    EVENTS_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

        # events.list is a read, so any transport error (including a read timeout)
        # is safe to retry.
        response = await aretry_call(
            attempt,
            retries=env_int("GOOGLE_MAX_RETRIES"),
            retry_on=(httpx.TransportError,),
            label="google calendar events",
        )
    except httpx.HTTPError as e:
        raise CalendarApiError("Calendar request failed") from e
    if response.status_code != 200:
        logger.error(
            "Calendar events.list failed: %s %s",
            response.status_code,
            response.text[:500],
        )
        raise CalendarApiError(f"Calendar API returned {response.status_code}")
    data = response.json()
    return data.get("items", []), bool(data.get("nextPageToken"))


def normalize_event(raw: dict, now: datetime) -> NormalizedEvent | None:
    """Return a truncated event, or None if it can never be an interview.

    Skips cancelled, all-day (no dateTime), past and declined events.
    """
    if raw.get("status") == "cancelled":
        return None
    start = (raw.get("start") or {}).get("dateTime")
    if not start or not raw.get("id"):
        return None
    try:
        start_dt = datetime.fromisoformat(start)
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=UTC)
    if start_dt <= now:
        return None

    organizer = raw.get("organizer") or {}
    user_response = "accepted" if organizer.get("self") else "needsAction"
    attendees: list[Attendee] = []
    for a in raw.get("attendees") or []:
        if a.get("self"):
            user_response = a.get("responseStatus", user_response)
            continue
        if len(attendees) < MAX_ATTENDEES:
            email = a.get("email")
            attendees.append(
                Attendee(
                    name=_strip_html(a.get("displayName") or "")[:100],
                    domain=_domain(email),
                )
            )
    if user_response == "declined":
        return None

    return NormalizedEvent(
        id=raw["id"],
        etag=raw.get("etag", ""),
        start=start,
        title=_strip_html(raw.get("summary") or "")[:TITLE_MAX],
        description=_strip_html(raw.get("description") or "")[:DESCRIPTION_MAX],
        organizer_name=_strip_html(organizer.get("displayName") or "")[:100],
        organizer_domain=_domain(organizer.get("email")),
        attendees=attendees,
        user_response=user_response,
    )


def passes_prefilter(event: NormalizedEvent) -> bool:
    """Stage 1 (no LLM, recall-biased): keywords, scheduling platform, or others invited."""
    if KEYWORDS.search(event.title) or KEYWORDS.search(event.description):
        return True
    if any(event.organizer_domain.endswith(d) for d in SCHEDULING_DOMAINS):
        return True
    return bool(event.attendees)
