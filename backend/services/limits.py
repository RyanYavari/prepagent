"""Kill switches and briefing cost caps (specs/deployment.md).

Flags are read from the environment at call time, so flipping one needs a container
recreate and no code change. A value that cannot be parsed falls back to the safe
default (feature on), so a typo never silently locks everyone out; the caps fall
back to their default numbers for the same reason.
"""

import logging
import os
import threading
from datetime import UTC, datetime, timedelta

from services.net_config import env_float
from services.supabase_client import execute

logger = logging.getLogger(__name__)

_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}


# Held across "check the caps, then insert" so parallel requests cannot all pass the same
# count. Re-entrant: the router holds it around its whole create (cap check, resume
# embedding, insert) and `create_pending_briefing` takes it again for other callers.
# Correct only with a single worker process (see specs/deployment.md).
creation_lock = threading.RLock()


class BriefingBlockedError(Exception):
    """A briefing cannot be created right now. Messages are safe to show a user."""


class BriefingsDisabledError(BriefingBlockedError):
    """The BRIEFINGS_ENABLED kill switch is off."""


class BriefingLimitError(BriefingBlockedError):
    """A per-user, active or global cap is reached. `retry_after` is in seconds."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


DAY = timedelta(days=1)
_ACTIVE = ("pending", "running")
GLOBAL_RETRY_AFTER = 3600
ACTIVE_RETRY_AFTER = 60

_INTS = {
    "MAX_BRIEFINGS_PER_USER_PER_DAY": 3,
    "MAX_BRIEFINGS_GLOBAL_PER_DAY": 20,
    "MAX_ACTIVE_BRIEFINGS_PER_USER": 2,
}
_INT_MAX = 100_000


def _env_cap(name: str) -> int:
    """Non-negative integer cap from the environment; anything else is the default."""
    default = _INTS[name]
    raw = os.getenv(name, "").strip()
    if not raw.isdigit():
        return default
    value = int(raw)
    return value if value <= _INT_MAX else default


def max_briefings_per_user_per_day() -> int:
    return _env_cap("MAX_BRIEFINGS_PER_USER_PER_DAY")


def max_briefings_global_per_day() -> int:
    return _env_cap("MAX_BRIEFINGS_GLOBAL_PER_DAY")


def max_active_briefings_per_user() -> int:
    return _env_cap("MAX_ACTIVE_BRIEFINGS_PER_USER")


def env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if raw in _FALSE:
        return False
    if raw in _TRUE:
        return True
    return default


def signups_enabled() -> bool:
    return env_flag("SIGNUPS_ENABLED")


def briefings_enabled() -> bool:
    return env_flag("BRIEFINGS_ENABLED")


def calendar_enabled() -> bool:
    return env_flag("CALENDAR_ENABLED")


def allowed_emails() -> set[str] | None:
    """Lower-cased allowlist, or None when no allowlist is configured."""
    raw = os.getenv("ALLOWED_EMAILS", "")
    emails = {e.strip().lower() for e in raw.split(",") if e.strip()}
    return emails or None


def email_allowed(email: str) -> bool:
    allowed = allowed_emails()
    return allowed is None or email.strip().lower() in allowed


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _count(result) -> int:
    count = getattr(result, "count", None)
    return count if isinstance(count, int) else len(result.data or [])


def check_briefing_allowed(supabase, user_id: str) -> None:
    """Raise BriefingBlockedError when this user may not create a briefing now.

    Counted from the `briefings` table so the caps survive restarts and need no new
    storage. The check is not atomic with the insert, so simultaneous requests can
    overshoot by the number in flight; that is accepted. Any database error
    propagates (fail closed: the request is refused rather than allowed uncounted).
    Messages never reveal counts or other users' activity.
    """
    if not briefings_enabled():
        raise BriefingsDisabledError("Briefing creation is temporarily unavailable")

    now = datetime.now(UTC)
    window = (now - DAY).isoformat()
    briefings = supabase.table("briefings")

    # Only recent rows can be active: an older `pending`/`running` row was orphaned
    # (for example by a restart) and must never lock the user out.
    fresh = (now - timedelta(minutes=env_float("STALE_RUNNING_MINUTES"))).isoformat()
    active = execute(
        supabase.table("briefings")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .in_("status", list(_ACTIVE))
        .gte("created_at", fresh)
    )
    if _count(active) >= max_active_briefings_per_user():
        raise BriefingLimitError(
            "You already have briefings in progress", ACTIVE_RETRY_AFTER
        )

    mine = execute(
        briefings.select("created_at").eq("user_id", user_id).gte("created_at", window)
    )
    stamps = sorted(_parse(r["created_at"]) for r in (mine.data or []))
    cap = max_briefings_per_user_per_day()
    if len(stamps) >= cap:
        # Capacity returns when enough of the oldest rows leave the 24 h window.
        frees_at = stamps[len(stamps) - cap] + DAY if cap else now + DAY
        raise BriefingLimitError(
            "Daily briefing limit reached", int((frees_at - now).total_seconds())
        )

    everyone = execute(
        supabase.table("briefings")
        .select("id", count="exact")
        .gte("created_at", window)
    )
    if _count(everyone) >= max_briefings_global_per_day():
        raise BriefingLimitError(
            "The service is at capacity for today", GLOBAL_RETRY_AFTER
        )
