"""Boundary checks for short free-text fields (company, role, interviewer).

These values come from users and, via calendar detection, from attacker-
controllable event text, and are later interpolated into search queries and LLM
prompts. Normal names ("AT&T", "O'Brien", "Procter & Gamble") pass; URLs,
markup-ish characters and control characters do not.
"""

import re
import unicodedata

_FORBIDDEN = re.compile(r"://|www\.|[<>`{}]", re.IGNORECASE)


def _strip_controls(value: str) -> str:
    return "".join(" " if unicodedata.category(c) in ("Cc", "Cf") else c for c in value)


def clean_field(value: str | None, max_len: int) -> str | None:
    """Lenient: normalize and truncate; return None if empty or unsafe."""
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value))
    text = " ".join(_strip_controls(text).split())
    if not text or _FORBIDDEN.search(text):
        return None
    return text[:max_len].strip() or None


def validate_safe_field(value: str | None) -> str | None:
    """Strict: reject (ValueError) instead of cleaning. For request models."""
    if value is None:
        return None
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in value):
        raise ValueError("must not contain control characters")
    if _FORBIDDEN.search(value):
        raise ValueError("must not contain URLs, angle brackets, backticks or braces")
    return value
