"""
Company Intelligence agent node.

Fixed-DAG step that runs in parallel with interviewer research
(ARCHITECTURE_DECISIONS.md section 1). Retry on thin search results is a local,
deterministic loop inside this node, not a supervisor decision.
"""

from typing import Any

from models.briefing import CompanyOverview
from models.research import SearchResult
from services.web_search import search_web

MAX_ATTEMPTS = 3
RETRY_THRESHOLD = 2  # retry while fewer than this many results (ADR section 1)
WARNING_THRESHOLD = 3  # warn when fewer than this many results (ADR section 6)


def low_result_warning(company: str, count: int) -> str:
    return (
        f"Limited public information available for {company}. "
        f"The following profile is based on {count} sources and may be incomplete."
    )


def _build_queries(company: str, role: str | None) -> list[str]:
    retry = " ".join(
        part for part in (company, role, "engineering tech stack recent news") if part
    )
    return [
        f"{company} company overview",
        retry,
        f"{company} about funding products",
    ]


def _summarize(
    company: str, role: str | None, results: list[SearchResult]
) -> CompanyOverview:
    raise NotImplementedError


def company_research_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Research the target company via Tavily and summarize into a CompanyOverview.

    State in:  company, optional role, optional warnings
    State out: company_research (CompanyOverview as dict), warnings

    Raises:
        ValueError: company missing/blank
        Exception: Tavily/LLM failures propagate
    """
    company = str(state.get("company") or "").strip()
    if not company:
        raise ValueError("company_research_node requires a company in state")
    role = str(state.get("role") or "").strip() or None

    collected: dict[str, SearchResult] = {}
    for query in _build_queries(company, role)[:MAX_ATTEMPTS]:
        for result in search_web(query):
            collected.setdefault(result.url, result)
        if len(collected) >= RETRY_THRESHOLD:
            break

    results = list(collected.values())
    warnings = list(state.get("warnings") or [])
    if len(results) < WARNING_THRESHOLD:
        warnings.append(low_result_warning(company, len(results)))

    overview = _summarize(company, role, results) if results else CompanyOverview()
    return {"company_research": overview.model_dump(), "warnings": warnings}
