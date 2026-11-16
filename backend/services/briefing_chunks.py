"""
Briefing chunk writer.

After a briefing completes, each non-empty output section is embedded and stored in
`resume_embeddings` as a `doc_type='briefing'` row so later briefings for the same
company can retrieve it (ARCHITECTURE_DECISIONS.md section 3, specs/briefing-chunk-writer.md).
"""

import os
from typing import Any

from supabase import create_client

from services.embeddings import embed_text

_TABLE = "resume_embeddings"

# Output sections that are embedded; `warnings` is deliberately not one of them.
_SECTIONS = (
    "company_overview",
    "interviewer_profile",
    "role_insights",
    "talking_points",
)


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL", ""),
        os.getenv("SUPABASE_SERVICE_KEY", ""),
    )


def _render_field(name: str, value: Any) -> str:
    label = name.replace("_", " ")
    if isinstance(value, list):
        items = [str(v).strip() for v in value if str(v).strip()]
        if not items:
            return ""
        return f"{label}:\n" + "\n".join(f"- {i}" for i in items)
    text = str(value).strip() if value else ""
    return f"{label}: {text}" if text else ""


def render_sections(content: dict[str, Any]) -> list[tuple[str, str]]:
    """Render each non-empty section of a stored briefing to (section, text)."""
    out: list[tuple[str, str]] = []
    for section in _SECTIONS:
        fields = content.get(section) or {}
        lines = [
            line
            for name, value in fields.items()
            if (line := _render_field(name, value))
        ]
        if lines:
            out.append((section, "\n".join(lines)))
    return out


def write_briefing_chunks(
    user_id: str,
    briefing_id: str,
    company: str,
    role: str | None,
    content: dict[str, Any],
) -> int:
    """
    Embed and store a completed briefing's sections, replacing any existing chunks
    for that briefing. Returns the number of chunks written.

    All embeddings are computed before any DB write, so a failure leaves the
    previous state untouched. Errors propagate; the caller decides they are non-fatal.
    """
    sections = render_sections(content)
    if not sections:
        return 0

    embeddings = [embed_text(text) for _, text in sections]
    rows: list[dict[str, Any]] = [
        {
            "user_id": user_id,
            "doc_type": "briefing",
            "section": section,
            "content": text,
            "embedding": embedding,
            "company": company,
            "role": role,
            "briefing_id": briefing_id,
        }
        for (section, text), embedding in zip(sections, embeddings)
    ]

    supabase = _get_supabase()
    (
        supabase.table(_TABLE)
        .delete()
        .eq("user_id", user_id)
        .eq("briefing_id", briefing_id)
        .eq("doc_type", "briefing")
        .execute()
    )
    supabase.table(_TABLE).insert(rows).execute()
    return len(rows)
