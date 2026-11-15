"""
Briefing pipeline: a fixed-DAG LangGraph StateGraph.

ARCHITECTURE_DECISIONS.md section 1: company research and interviewer research run
in parallel, then RAG retrieval, then synthesis. Fixed edges, no supervisor.
"""

import logging
import os

from langgraph.graph import END, START, StateGraph
from supabase import create_client

from agents.company import company_research_node
from agents.interviewer import interviewer_research_node
from agents.rag import rag_retrieval_node
from agents.state import PipelineState
from agents.synthesis import synthesis_node
from models.briefing import BriefingSections, BriefingStatus

logger = logging.getLogger(__name__)


def _get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


def _update_briefing(supabase, briefing_id: str, user_id: str, fields: dict) -> None:
    (
        supabase.table("briefings")
        .update(fields)
        .eq("id", briefing_id)
        .eq("user_id", user_id)
        .execute()
    )


def build_graph():
    """Compile the fixed-DAG briefing graph."""
    graph = StateGraph(PipelineState)
    graph.add_node("company_research", company_research_node)
    graph.add_node("interviewer_research", interviewer_research_node)
    graph.add_node("rag_retrieval", rag_retrieval_node)
    graph.add_node("synthesis", synthesis_node)

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
) -> None:
    """
    Run the graph for a briefing and persist the outcome.

    Status moves pending -> running -> complete (content saved) or failed.
    Runs as a background task, so it never raises: errors are logged and the
    row is marked failed.
    """
    try:
        supabase = _get_supabase()
        _update_briefing(
            supabase, briefing_id, user_id, {"status": BriefingStatus.running.value}
        )

        final = build_graph().invoke(
            {
                "user_id": user_id,
                "company": company,
                "interviewer": interviewer,
                "role": role,
                "warnings": [],
            },
            config={
                "run_name": "briefing_pipeline",
                "tags": ["briefing"],
                "metadata": {"briefing_id": briefing_id},
            },
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
    except Exception:
        logger.exception("Briefing pipeline failed for briefing %s", briefing_id)
        try:
            _update_briefing(
                _get_supabase(),
                briefing_id,
                user_id,
                {"status": BriefingStatus.failed.value},
            )
        except Exception:
            logger.exception("Could not mark briefing %s as failed", briefing_id)
