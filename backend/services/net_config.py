"""
Timeouts, retry counts and deadlines for every outbound call.

Each value is read from the environment at call time and falls back to a default
when unset, non-numeric or out of range, so a bad `.env` can never disable a limit.
Retries are bounded and only for transient failures; messages from the failed call
are never logged (they can carry URLs or request details).
"""

import logging
import os
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# name -> (default, minimum, maximum)
_FLOATS = {
    "LLM_TIMEOUT_SECONDS": (45.0, 1.0, 600.0),
    "EMBEDDING_TIMEOUT_SECONDS": (15.0, 1.0, 120.0),
    "TAVILY_TIMEOUT_SECONDS": (12.0, 1.0, 120.0),
    "SUPABASE_TIMEOUT_SECONDS": (10.0, 1.0, 120.0),
    "PIPELINE_DEADLINE_SECONDS": (120.0, 10.0, 900.0),
    "STALE_RUNNING_MINUTES": (10.0, 1.0, 1440.0),
}
_INTS = {
    "LLM_MAX_RETRIES": (1, 0, 5),
    "EMBEDDING_MAX_RETRIES": (2, 0, 5),
    "TAVILY_MAX_RETRIES": (1, 0, 5),
    "SUPABASE_MAX_RETRIES": (2, 0, 5),
}


def env_float(name: str) -> float:
    default, low, high = _FLOATS[name]
    try:
        value = float(os.getenv(name, ""))
    except ValueError:
        return default
    return value if low <= value <= high else default


def env_int(name: str) -> int:
    default, low, high = _INTS[name]
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if low <= value <= high else default


def retry_call(
    fn: Callable[[], T],
    *,
    retries: int,
    retry_on: tuple[type[BaseException], ...],
    label: str,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """
    Call `fn`, retrying up to `retries` more times when it raises one of `retry_on`.

    Backoff doubles from `base_delay` up to `max_delay`. Any other exception, and
    the last failure once retries are spent, propagates unchanged.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except retry_on as exc:
            if attempt >= retries:
                raise
            attempt += 1
            logger.warning(
                "Retrying %s after %s (attempt %d of %d)",
                label,
                type(exc).__name__,
                attempt,
                retries,
            )
            (sleep or time.sleep)(min(base_delay * 2 ** (attempt - 1), max_delay))
