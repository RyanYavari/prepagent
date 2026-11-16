"""Run one golden case through the real graph and capture what scoring needs.

Production code is untouched. Three seams are swapped for the duration of a run:

* retrieval: in-memory (chunked synthetic resume + seeded prior briefings), so the
  eval never reads or writes Supabase;
* web search: wrapped to record every result each research node saw (graph state
  keeps only summaries), with optional record/replay caching;
* LLM construction: wrapped so every pipeline LLM call is charged to the budget.
"""

import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from agents.pipeline import build_graph
from evals.budget import BudgetExceeded, CallBudget
from evals.dataset import GoldenCase
from evals.webcache import WebCache
from models.briefing import BriefingSections
from models.research import SearchResult
from models.retrieval import RetrievalResult, RetrievedChunk
from services.embeddings import chunk_resume
from services.web_search import search_web as real_search_web

logger = logging.getLogger(__name__)

EVAL_USER_ID = "eval-user"


@dataclass
class CollectedCase:
    case: GoldenCase
    sections: BriefingSections | None = None
    web_company: list[SearchResult] = field(default_factory=list)
    web_interviewer: list[SearchResult] = field(default_factory=list)
    resume_chunks: list[RetrievedChunk] = field(default_factory=list)
    prior_chunks: list[RetrievedChunk] = field(default_factory=list)
    pipeline_warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: str | None = None  # exception class name only
    trace_run_id: str | None = None  # LangSmith run id, used for score feedback


def make_retrieval(case: GoldenCase) -> Callable[..., RetrievalResult]:
    """In-memory stand-in for `retrieve_user_context`, same filter semantics."""

    def retrieve(user_id: Any, company: str) -> RetrievalResult:
        resume = [
            RetrievedChunk(doc_type="resume", section=c.section, content=c.content)
            for c in chunk_resume(case.resume_text)
        ]
        target = company.strip().casefold()
        prior = [
            RetrievedChunk(
                doc_type="briefing",
                section=p.section,
                content=p.content,
                company=p.company,
                role=p.role,
            )
            for p in case.prior_briefings
            if p.company.strip().casefold() == target
        ]
        return RetrievalResult(resume_chunks=resume, briefing_chunks=prior)

    return retrieve


class _CountedLLM:
    """Wraps a structured-output runnable so each invoke is charged first."""

    def __init__(self, inner: Any, budget: CallBudget) -> None:
        self._inner = inner
        self._budget = budget

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        self._budget.charge("pipeline")
        return self._inner.invoke(*args, **kwargs)


def make_search(
    recorded: dict[str, SearchResult],
    cache: WebCache,
    budget: CallBudget,
    search: Callable[..., list[SearchResult]] = real_search_web,
) -> Callable[..., list[SearchResult]]:
    def wrapped(query: str, max_results: int = 5) -> list[SearchResult]:
        cached = cache.get(query, max_results)
        if cached is not None:
            budget.count_tavily(cached=True)
            results = cached
        else:
            budget.count_tavily()
            results = search(query, max_results)
            cache.put(query, max_results, results)
        for r in results:
            recorded.setdefault(r.url, r)
        return results

    return wrapped


@contextmanager
def seams(
    case: GoldenCase,
    budget: CallBudget,
    cache: WebCache,
    company_seen: dict[str, SearchResult],
    interviewer_seen: dict[str, SearchResult],
    search: Callable[..., list[SearchResult]] = real_search_web,
) -> Iterator[None]:
    from agents import company, interviewer, rag, synthesis

    real_llm = {m: m.structured_llm for m in (company, interviewer, synthesis)}

    def counted(module: Any) -> Callable[..., _CountedLLM]:
        return lambda schema: _CountedLLM(real_llm[module](schema), budget)

    with (
        patch.object(rag, "retrieve_user_context", make_retrieval(case)),
        patch.object(
            company, "search_web", make_search(company_seen, cache, budget, search)
        ),
        patch.object(
            interviewer,
            "search_web",
            make_search(interviewer_seen, cache, budget, search),
        ),
        patch.object(company, "structured_llm", counted(company)),
        patch.object(interviewer, "structured_llm", counted(interviewer)),
        patch.object(synthesis, "structured_llm", counted(synthesis)),
    ):
        yield


def _used(seen: dict[str, SearchResult], sources: list[str]) -> list[SearchResult]:
    """The results the node actually summarized (its `sources`), in order."""
    return [seen[url] for url in sources if url in seen]


def collect_case(
    case: GoldenCase,
    budget: CallBudget,
    cache: WebCache | None = None,
    graph: Any = None,
    search: Callable[..., list[SearchResult]] = real_search_web,
) -> CollectedCase:
    """Run `case` through the graph. Only BudgetExceeded propagates; any other
    failure is recorded as the exception class name so one bad case cannot sink a run."""
    cache = cache or WebCache("off")
    company_seen: dict[str, SearchResult] = {}
    interviewer_seen: dict[str, SearchResult] = {}
    out = CollectedCase(case=case)
    started = time.monotonic()
    out.trace_run_id = str(uuid.uuid4())
    try:
        with seams(case, budget, cache, company_seen, interviewer_seen, search):
            final = (graph or build_graph()).invoke(
                {
                    "user_id": EVAL_USER_ID,
                    "briefing_id": f"eval-{case.id}",
                    "company": case.company,
                    "interviewer": case.interviewer,
                    "role": case.role,
                    "job_description": case.job_description,
                    "warnings": [],
                },
                config={
                    "run_name": "eval_case",
                    "tags": ["eval"],
                    "run_id": out.trace_run_id,
                },
            )
        out.pipeline_warnings = list(final.get("warnings") or [])
        out.sections = BriefingSections.model_validate(
            {**final["briefing_content"], "warnings": out.pipeline_warnings}
        )
        sources_c = (final.get("company_research") or {}).get("sources") or []
        sources_i = (final.get("interviewer_research") or {}).get("sources") or []
        out.web_company = _used(company_seen, sources_c)
        out.web_interviewer = _used(interviewer_seen, sources_i)
        retrieved = RetrievalResult.model_validate(final.get("retrieved_context") or {})
        out.resume_chunks = retrieved.resume_chunks
        out.prior_chunks = retrieved.briefing_chunks
    except BudgetExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - one failing case must not end the run
        out.error = type(exc).__name__
        logger.warning("case=%s event=error error=%s", case.id, out.error)
    out.elapsed_seconds = round(time.monotonic() - started, 2)
    return out
