"""
Company Intelligence agent node.

Fixed-DAG step that runs in parallel with interviewer research
(ARCHITECTURE_DECISIONS.md section 1). Retry on thin search results is a local,
deterministic loop inside this node, not a supervisor decision.
"""

import os
from typing import Any

from langchain_anthropic import ChatAnthropic

from models.briefing import CompanyOverview
from models.research import SearchResult
from services.web_search import search_web

MAX_ATTEMPTS = 3
RETRY_THRESHOLD = 2  # retry while fewer than this many results (ADR section 1)
WARNING_THRESHOLD = 3  # warn when fewer than this many results (ADR section 6)
DEFAULT_MODEL = "claude-sonnet-5-5"

SYSTEM_PROMPT = (
    "You write the company-overview section of an interview briefing. "
    "Use ONLY the numbered search results provided. Every factual claim must come "
    "from those results; if the results do not support a claim, do not include it. "
    "Leave fields empty rather than guessing. Do not include claims about dates or "
    "events unless a result states them. Keep recent_news items short and note the "
    "date when a result gives one."
)


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
    formatted = "\n\n".join(
        f"[{i}] {r.title}\nURL: {r.url}\n{r.content}"
        for i, r in enumerate(results, start=1)
    )
    role_line = f"Role being interviewed for: {role}\n" if role else ""
    llm = ChatAnthropic(  # type: ignore[call-arg]
        model=os.getenv("COMPANY_AGENT_MODEL", DEFAULT_MODEL),
        temperature=0,
    )
    structured = llm.with_structured_output(CompanyOverview)
    overview = structured.invoke(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                f"Company: {company}\n{role_line}\nSearch results:\n{formatted}",
            ),
        ]
    )
    result = (
        overview
        if isinstance(overview, CompanyOverview)
        else CompanyOverview.model_validate(overview)
    )
    # Sources are set in code so the model cannot cite a URL it was not given.
    result.sources = [r.url for r in results]
    return result


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
