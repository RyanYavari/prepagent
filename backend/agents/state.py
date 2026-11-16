"""Shared state for the briefing pipeline graph."""

from typing import Annotated, Any, TypedDict


def merge_warnings(existing: list[str] | None, update: list[str] | None) -> list[str]:
    """
    Reducer for `warnings`.

    Nodes return the full warnings list they were handed plus their own, so the
    two parallel research branches each echo the same prior warnings. Append only
    items not already present, preserving order.
    """
    merged = list(existing or [])
    for warning in update or []:
        if warning not in merged:
            merged.append(warning)
    return merged


class PipelineState(TypedDict, total=False):
    user_id: str
    briefing_id: str
    company: str
    interviewer: str | None
    role: str | None
    job_description: str | None  # request-scoped; synthesis only, never persisted
    company_research: dict[str, Any]
    interviewer_research: dict[str, Any]
    retrieved_context: dict[str, Any]
    briefing_content: dict[str, Any]
    warnings: Annotated[list[str], merge_warnings]
