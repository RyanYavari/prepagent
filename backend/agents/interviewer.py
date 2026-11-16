"""
Interviewer Research agent node.

Fixed-DAG step that runs in parallel with company research
(ARCHITECTURE_DECISIONS.md section 1). Retry on thin search results is a local,
deterministic loop inside this node, not a supervisor decision. Results that do
not mention the interviewer by name are dropped so a common name cannot pull in
a different person (section 6, failure mode 3).
"""

from typing import Any

from agents.llm import structured_llm
from models.briefing import InterviewerProfile
from models.research import SearchResult
from services.web_search import search_web

MAX_ATTEMPTS = 3
RETRY_THRESHOLD = 2  # retry while fewer than this many relevant results (ADR section 1)
WARNING_THRESHOLD = 3  # warn when fewer than this many results (ADR section 6)


def low_result_warning(interviewer: str, count: int) -> str:
    return (
        f"Limited public information available for {interviewer}. "
        f"The following profile is based on {count} sources and may be incomplete."
    )


def wrong_person_warning(interviewer: str, company: str) -> str:
    return (
        f"Could not confirm that these sources refer to {interviewer} at {company}. "
        "Verify this is the right person before relying on the profile."
    )


def _build_queries(interviewer: str, company: str, role: str | None) -> list[str]:
    base = f'"{interviewer}" {company}'
    with_role = " ".join(part for part in (base, role, "linkedin") if part)
    return [base, with_role, f"{base} blog talk interview podcast"]


def _mentions(result: SearchResult, text: str) -> bool:
    return text.lower() in f"{result.title} {result.content}".lower()


SYSTEM_PROMPT = (
    "You write the interviewer-profile section of an interview briefing. "
    "Use ONLY the numbered search results provided. Include facts only about a "
    "person who is clearly the named interviewer at the named company. If the "
    "results appear to describe different people with the same name, or you cannot "
    "tell, leave the fields empty rather than guessing. Every factual claim must "
    "come from those results; do not include claims the results do not support. "
    "Fill summary and background only; leave shared_interests and "
    "conversation_starters empty."
)


def _summarize(
    interviewer: str,
    company: str,
    role: str | None,
    results: list[SearchResult],
) -> InterviewerProfile:
    formatted = "\n\n".join(
        f"[{i}] {r.title}\nURL: {r.url}\n{r.content}"
        for i, r in enumerate(results, start=1)
    )
    role_line = f"Role being interviewed for: {role}\n" if role else ""
    structured = structured_llm(InterviewerProfile)
    profile = structured.invoke(
        [
            ("system", SYSTEM_PROMPT),
            (
                "human",
                f"Interviewer: {interviewer}\nCompany: {company}\n{role_line}\n"
                + f"Search results:\n{formatted}",
            ),
        ]
    )
    result = (
        profile
        if isinstance(profile, InterviewerProfile)
        else InterviewerProfile.model_validate(profile)
    )
    # Sources are set in code so the model cannot cite a URL it was not given.
    result.sources = [r.url for r in results]
    return result


def interviewer_research_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Research the interviewer via Tavily and summarize into an InterviewerProfile.

    State in:  interviewer (optional), company, optional role, optional warnings
    State out: interviewer_research (InterviewerProfile as dict), warnings

    Raises:
        ValueError: interviewer given but company missing/blank
        Exception: Tavily/LLM failures propagate
    """
    warnings = list(state.get("warnings") or [])
    interviewer = str(state.get("interviewer") or "").strip()
    if not interviewer:
        return {
            "interviewer_research": InterviewerProfile().model_dump(),
            "warnings": warnings,
        }

    company = str(state.get("company") or "").strip()
    if not company:
        raise ValueError("interviewer_research_node requires a company in state")
    role = str(state.get("role") or "").strip() or None

    collected: dict[str, SearchResult] = {}
    for query in _build_queries(interviewer, company, role)[:MAX_ATTEMPTS]:
        for result in search_web(query):
            if _mentions(result, interviewer):
                collected.setdefault(result.url, result)
        if len(collected) >= RETRY_THRESHOLD:
            break

    results = list(collected.values())
    if len(results) < WARNING_THRESHOLD:
        warnings.append(low_result_warning(interviewer, len(results)))
    if results and not any(_mentions(r, company) for r in results):
        warnings.append(wrong_person_warning(interviewer, company))

    profile = (
        _summarize(interviewer, company, role, results)
        if results
        else InterviewerProfile()
    )
    return {"interviewer_research": profile.model_dump(), "warnings": warnings}
