"""Boundary checks for short free-text fields (company, role, interviewer).

These values come from users and, via calendar detection, from attacker-
controllable event text, and are later interpolated into search queries and LLM
prompts. Normal names ("AT&T", "O'Brien", "Procter & Gamble") pass; URLs,
markup-ish characters and control characters do not.
"""

import re
import unicodedata

_FORBIDDEN = re.compile(r"://|www\.|[<>`{}]", re.IGNORECASE)
_BLANK_RUNS = re.compile(r"\n{3,}")


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


def clean_long_text(value: str | None) -> str | None:
    """
    For long pasted text that goes into an LLM prompt (job description).

    Unlike `validate_safe_field` it accepts URLs and markup-ish characters, which
    real postings contain. It normalizes newlines, keeps `\\n` and `\\t`, removes
    other control (Cc) and format (Cf: zero-width, bidi override) characters that
    can hide injected text, collapses runs of blank lines and strips the ends.
    No NFKC (it would rewrite legitimate characters). Returns None when nothing is
    left. Injection safety comes from the prompt layer, not from rejecting content.
    """
    if value is None:
        return None
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf")
    )
    text = _BLANK_RUNS.sub("\n\n", text).strip()
    return text or None
