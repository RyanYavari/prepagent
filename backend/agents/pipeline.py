"""
Briefing pipeline: a fixed-DAG LangGraph StateGraph.

ARCHITECTURE_DECISIONS.md section 1: company research and interviewer research run
in parallel, then RAG retrieval, then synthesis. Fixed edges, no supervisor.
"""

import contextvars
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.company import company_research_node
from agents.interviewer import interviewer_research_node
from agents.rag import rag_retrieval_node
from agents.state import PipelineState
from agents.synthesis import synthesis_node
from models.briefing import BriefingSections, BriefingStatus
from services.briefing_chunks import write_briefing_chunks
from services.log_safety import log_failure
from services.net_config import env_float
from services.supabase_client import create_client, execute

logger = logging.getLogger(__name__)


# Generic, user-visible failure reasons. Never put exception text here.
REASON_TIMEOUT = "The briefing took too long to generate and was stopped."
REASON_ERROR = "Something went wrong while generating this briefing."

# Set by run_pipeline when the deadline passes so a straggling graph thread stops
# before starting its next node instead of spending more API calls.
_CANCELLED: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "pipeline_cancelled", default=None
)


class PipelineDeadlineExceeded(Exception):
    """The graph did not finish within PIPELINE_DEADLINE_SECONDS."""


class PipelineCancelled(Exception):
    """A node was about to start after the pipeline deadline had passed."""


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


def _update_briefing(supabase, briefing_id: str, user_id: str, fields: dict) -> None:
    execute(
        supabase.table("briefings")
        .update(fields)
        .eq("id", briefing_id)
        .eq("user_id", user_id)
    )


def _mark_failed(supabase, briefing_id: str, user_id: str, reason: str) -> None:
    """
    Set status failed with a generic reason.

    If the `failure_reason` column is missing (migration 007 not applied) the
    update is retried with the status alone, so a run can never be left `running`
    just because of the reason field.
    """
    failed = BriefingStatus.failed.value
    try:
        _update_briefing(
            supabase,
            briefing_id,
            user_id,
            {"status": failed, "failure_reason": reason},
        )
    except Exception:  # noqa: BLE001 - any failure here (e.g. missing column) falls back
        logger.warning(
            "Could not save failure reason for briefing %s; saving status only",
            briefing_id,
        )
        _update_briefing(supabase, briefing_id, user_id, {"status": failed})


def _timed(name: str, node: Callable[[dict[str, Any]], Any]):
    """Wrap a node to log start/end and elapsed seconds (ids and timings only)."""

    def wrapper(state: dict[str, Any]):
        briefing_id = state.get("briefing_id")
        cancelled = _CANCELLED.get()
        if cancelled is not None and cancelled.is_set():
            raise PipelineCancelled(name)
        start = time.monotonic()
        logger.info("node=%s briefing_id=%s event=start", name, briefing_id)
        try:
            out = node(state)
        except Exception as exc:
            logger.info(
                "node=%s briefing_id=%s event=error error=%s elapsed=%.2fs",
                name,
                briefing_id,
                type(exc).__name__,
                time.monotonic() - start,
            )
            raise
        logger.info(
            "node=%s briefing_id=%s event=end elapsed=%.2fs",
            name,
            briefing_id,
            time.monotonic() - start,
        )
        return out

    return wrapper


def _invoke_with_deadline(graph, state: dict[str, Any], config: dict, deadline: float):
    """
    Run `graph.invoke` in a worker thread and give up after `deadline` seconds.

    A thread cannot be killed, so on timeout the cancel flag stops it before its next
    node and every call inside it is bounded by its own timeout. Its result is
    discarded: only the caller persists anything.
    """
    cancelled = threading.Event()
    token = _CANCELLED.set(cancelled)
    ctx = contextvars.copy_context()
    _CANCELLED.reset(token)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="briefing-pipeline")
    future = executor.submit(ctx.run, lambda: graph.invoke(state, config=config))
    try:
        done, _ = wait([future], timeout=deadline)
        if not done:
            cancelled.set()
            raise PipelineDeadlineExceeded()
        return future.result()  # re-raises the graph's own error, if any
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _write_chunks(
    briefing_id: str,
    user_id: str,
    company: str,
    role: str | None,
    content: dict,
) -> None:
    """Embed the completed briefing for later retrieval; never affects its status."""
    try:
        write_briefing_chunks(user_id, briefing_id, company, role, content)
    except Exception as exc:  # noqa: BLE001 - logged via log_failure
        log_failure(
            logger, f"Could not write briefing chunks for briefing {briefing_id}", exc
        )


def build_graph():
    """Compile the fixed-DAG briefing graph."""
    graph = StateGraph(PipelineState)
    graph.add_node(
        "company_research", _timed("company_research", company_research_node)
    )
    graph.add_node(
        "interviewer_research",
        _timed("interviewer_research", interviewer_research_node),
    )
    graph.add_node("rag_retrieval", _timed("rag_retrieval", rag_retrieval_node))
    graph.add_node("synthesis", _timed("synthesis", synthesis_node))

    graph.add_edge(START, "company_research")
    graph.add_edge(START, "interviewer_research")
    graph.add_edge(["company_research", "interviewer_research"], "rag_retrieval")
    graph.add_edge("rag_retrieval", "synthesis")
    graph.add_edge("synthesis", END)
    return graph.compile()


def run_pipeline(
    briefing_id: str,
    user_id: str,
    company: str,
    interviewer: str | None = None,
    role: str | None = None,
    job_description: str | None = None,
) -> None:
    """
    Run the graph for a briefing and persist the outcome.

    `job_description` is request-scoped: it goes into graph state for synthesis only
    and is never persisted, logged or put in run metadata.

    Status moves pending -> running -> complete (content saved) or failed.
    Runs as a background task, so it never raises: errors are logged and the
    row is marked failed.
    """
    started = time.monotonic()
    outcome = "failed"
    try:
        supabase = _get_supabase()
        _update_briefing(
            supabase, briefing_id, user_id, {"status": BriefingStatus.running.value}
        )

        final = _invoke_with_deadline(
            build_graph(),
            {
                "user_id": user_id,
                "briefing_id": briefing_id,
                "company": company,
                "interviewer": interviewer,
                "role": role,
                "job_description": job_description,
                "warnings": [],
            },
            {
                "run_name": "briefing_pipeline",
                "tags": ["briefing"],
                "metadata": {"briefing_id": briefing_id},
            },
            env_float("PIPELINE_DEADLINE_SECONDS"),
        )

        content = BriefingSections.model_validate(
            {**final["briefing_content"], "warnings": final.get("warnings", [])}
        ).model_dump()
        _update_briefing(
            supabase,
            briefing_id,
            user_id,
            {"status": BriefingStatus.complete.value, "content": content},
        )
        outcome = "complete"
        _write_chunks(briefing_id, user_id, company, role, content)
    except Exception as exc:  # noqa: BLE001 - logged via log_failure
        timed_out = isinstance(exc, PipelineDeadlineExceeded)
        if timed_out:
            logger.error(
                "Briefing %s exceeded the %.0fs pipeline deadline",
                briefing_id,
                env_float("PIPELINE_DEADLINE_SECONDS"),
            )
        else:
            # Class only: a pydantic or provider error message can quote the prompt
            # (resume, job description) or a database row.
            log_failure(
                logger, f"Briefing pipeline failed for briefing {briefing_id}", exc
            )
        try:
            _mark_failed(
                _get_supabase(),
                briefing_id,
                user_id,
                REASON_TIMEOUT if timed_out else REASON_ERROR,
            )
        except Exception as mark_exc:  # noqa: BLE001 - logged via log_failure
            log_failure(
                logger, f"Could not mark briefing {briefing_id} as failed", mark_exc
            )
    finally:
        logger.info(
            "pipeline briefing_id=%s event=end status=%s elapsed=%.2fs",
            briefing_id,
            outcome,
            time.monotonic() - started,
        )
