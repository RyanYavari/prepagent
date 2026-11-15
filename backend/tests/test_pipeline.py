"""Tests for the LangGraph pipeline (specs/langgraph-pipeline.md)."""

from unittest.mock import MagicMock, patch

import pytest

from agents import pipeline
from agents.pipeline import build_graph

INPUT = {
    "user_id": "user-1",
    "company": "Stripe",
    "interviewer": "Jane Doe",
    "role": "Backend Engineer",
}


def _patch_nodes(company=None, interviewer=None, rag=None, synthesis=None):
    """Patch the node functions the graph is built from; return the mocks."""
    mocks = {
        "company_research_node": MagicMock(
            side_effect=company
            or (lambda s: {"company_research": {"summary": "co"}, "warnings": []})
        ),
        "interviewer_research_node": MagicMock(
            side_effect=interviewer
            or (lambda s: {"interviewer_research": {"summary": "iv"}, "warnings": []})
        ),
        "rag_retrieval_node": MagicMock(
            side_effect=rag
            or (lambda s: {"retrieved_context": {"resume_chunks": []}, "warnings": []})
        ),
        "synthesis_node": MagicMock(
            side_effect=synthesis
            or (lambda s: {"briefing_content": {"done": True}, "warnings": []})
        ),
    }
    patches = [patch.object(pipeline, name, m) for name, m in mocks.items()]
    return mocks, patches


@pytest.fixture
def run_graph():
    def _run(state=None, **node_overrides):
        mocks, patches = _patch_nodes(**node_overrides)
        for p in patches:
            p.start()
        try:
            out = build_graph().invoke(dict(state or INPUT))
        finally:
            for p in patches:
                p.stop()
        return out, mocks

    return _run


def test_graph_topology_is_fixed_dag():
    """Scenario 1."""
    g = build_graph().get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert edges == {
        ("__start__", "company_research"),
        ("__start__", "interviewer_research"),
        ("company_research", "rag_retrieval"),
        ("interviewer_research", "rag_retrieval"),
        ("rag_retrieval", "synthesis"),
        ("synthesis", "__end__"),
    }
    assert not any("supervisor" in n for n in g.nodes)


def test_happy_path_passes_state_between_nodes(run_graph):
    """Scenario 2."""
    out, mocks = run_graph()

    assert out["briefing_content"] == {"done": True}
    for name in ("company_research_node", "interviewer_research_node"):
        state = mocks[name].call_args.args[0]
        assert state["company"] == "Stripe"
        assert state["user_id"] == "user-1"
        assert state["interviewer"] == "Jane Doe"
    rag_state = mocks["rag_retrieval_node"].call_args.args[0]
    assert rag_state["company_research"] == {"summary": "co"}
    assert rag_state["interviewer_research"] == {"summary": "iv"}
    syn_state = mocks["synthesis_node"].call_args.args[0]
    assert syn_state["retrieved_context"] == {"resume_chunks": []}
    assert syn_state["company_research"] == {"summary": "co"}


def test_parallel_warnings_are_merged_without_duplicates(run_graph):
    """Scenario 3."""

    def company(s):
        return {"company_research": {}, "warnings": list(s["warnings"]) + ["co warn"]}

    def interviewer(s):
        return {
            "interviewer_research": {},
            "warnings": list(s["warnings"]) + ["iv warn"],
        }

    def rag(s):
        return {"retrieved_context": {}, "warnings": list(s["warnings"]) + ["rag"]}

    def synthesis(s):
        return {"briefing_content": {}, "warnings": list(s["warnings"]) + ["syn"]}

    out, _ = run_graph(
        state={**INPUT, "warnings": []},
        company=company,
        interviewer=interviewer,
        rag=rag,
        synthesis=synthesis,
    )

    assert sorted(out["warnings"]) == ["co warn", "iv warn", "rag", "syn"]


def test_runs_without_interviewer(run_graph):
    """Scenario 4."""
    state = {k: v for k, v in INPUT.items() if k != "interviewer"}
    out, mocks = run_graph(state=state)

    assert out["briefing_content"] == {"done": True}
    assert "interviewer" not in mocks["interviewer_research_node"].call_args.args[0]
