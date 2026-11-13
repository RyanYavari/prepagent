"""
RAG retrieval for briefing synthesis.

Per ARCHITECTURE_DECISIONS.md section 3, retrieval is a SQL filter rather than a
similarity search: all of the user's resume chunks (~15) plus only the user's prior
briefing chunks for the target company. Every query is scoped to user_id.
"""

import os
from uuid import UUID

from supabase import create_client

from models.retrieval import RetrievalResult, RetrievedChunk

# Explicit column list: the embedding vector is never selected.
_COLUMNS = "doc_type, section, content, company, role, created_at"
_TABLE = "resume_embeddings"


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so the company name is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_chunks(rows: list[dict]) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(**{k: row.get(k) for k in RetrievedChunk.model_fields})
        for row in rows
    ]


def retrieve_user_context(user_id: str | UUID, company: str) -> RetrievalResult:
    """
    Fetch the user's resume chunks and prior briefing chunks for `company`.

    Args:
        user_id: Authenticated user's UUID (from the JWT, never request body)
        company: Target company; matched case-insensitively and literally

    Raises:
        Exception: Any Supabase failure propagates, so a DB outage is never
            mistaken for "user has no resume".
    """
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )

    resume_rows = (
        supabase.table(_TABLE)
        .select(_COLUMNS)
        .eq("user_id", str(user_id))
        .eq("doc_type", "resume")
        .execute()
        .data
    )

    briefing_rows = (
        supabase.table(_TABLE)
        .select(_COLUMNS)
        .eq("user_id", str(user_id))
        .eq("doc_type", "briefing")
        .ilike("company", _escape_like(company.strip()))
        .order("created_at", desc=True)
        .execute()
        .data
    )

    return RetrievalResult(
        resume_chunks=_to_chunks(resume_rows or []),
        briefing_chunks=_to_chunks(briefing_rows or []),
    )
