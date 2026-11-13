"""
RAG retrieval node for the briefing pipeline.

Fixed-DAG step that runs after company/interviewer research and before synthesis
(ARCHITECTURE_DECISIONS.md sections 1 and 3). Follows the LangGraph node contract:
takes the state dict and returns a partial state update.
"""

from typing import Any

from services.retrieval import retrieve_user_context

NO_RESUME_WARNING = (
    "No resume on file; talking points will not reference your background."
)


def rag_retrieval_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieve the user's resume chunks and prior same-company briefing chunks.

    State in:  user_id (from JWT upstream), company, optional warnings
    State out: retrieved_context (RetrievalResult as dict), warnings

    Raises:
        ValueError: user_id or company missing/blank (never query unscoped)
        Exception: Supabase failures propagate
    """
    user_id = state.get("user_id")
    company = state.get("company")

    if not user_id or not str(user_id).strip():
        raise ValueError("rag_retrieval_node requires a user_id in state")
    if not company or not str(company).strip():
        raise ValueError("rag_retrieval_node requires a company in state")

    result = retrieve_user_context(user_id, company)

    warnings = list(state.get("warnings") or [])
    if not result.resume_chunks:
        warnings.append(NO_RESUME_WARNING)

    return {"retrieved_context": result.model_dump(), "warnings": warnings}
