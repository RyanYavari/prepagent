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


# --- run_pipeline lifecycle (scenarios 5, 6, 7) ---


def _supabase_mock():
    sb = MagicMock()
    return sb


def _updates(sb):
    """List of (payload, eq-calls) for each briefings update."""
    out = []
    for call in sb.table.return_value.update.call_args_list:
        out.append(call.args[0])
    return out


def _run_pipeline(graph, sb):
    with (
        patch.object(pipeline, "_get_supabase", return_value=sb),
        patch.object(pipeline, "build_graph", return_value=graph),
        patch.object(pipeline, "write_briefing_chunks") as writer,
    ):
        _run_pipeline.writer = writer
        pipeline.run_pipeline(
            briefing_id="b-1",
            user_id="user-1",
            company="Stripe",
            interviewer="Jane Doe",
            role="Backend Engineer",
        )


def test_run_pipeline_success_lifecycle():
    """Scenario 5."""
    sb = _supabase_mock()
    graph = MagicMock()
    graph.invoke.return_value = {
        "briefing_content": {"company_overview": {"summary": "x"}},
        "warnings": ["careful"],
    }

    _run_pipeline(graph, sb)

    state = graph.invoke.call_args.args[0]
    assert state["user_id"] == "user-1"
    assert state["company"] == "Stripe"
    assert state["briefing_id"] == "b-1"
    assert state["warnings"] == []
    assert graph.invoke.call_args.kwargs["config"]["metadata"] == {"briefing_id": "b-1"}

    updates = _updates(sb)
    assert updates[0] == {"status": "running"}
    assert updates[1]["status"] == "complete"
    assert updates[1]["content"]["company_overview"]["summary"] == "x"
    assert updates[1]["content"]["warnings"] == ["careful"]
    # every update is scoped by id and user_id
    first_eq = sb.table.return_value.update.return_value.eq
    first_eq.assert_called_with("id", "b-1")
    first_eq.return_value.eq.assert_called_with("user_id", "user-1")


def test_run_pipeline_failure_marks_failed(caplog):
    """Scenario 6."""
    sb = _supabase_mock()
    graph = MagicMock()
    graph.invoke.side_effect = RuntimeError("tavily down")

    with caplog.at_level("ERROR"):
        _run_pipeline(graph, sb)  # must not raise

    updates = _updates(sb)
    assert updates[-1] == {
        "status": "failed",
        "failure_reason": pipeline.REASON_ERROR,
    }
    assert not any("content" in u for u in updates)
    assert "tavily down" in caplog.text


def test_run_pipeline_failed_status_write_error_is_contained(caplog):
    """Scenario 7."""
    sb = _supabase_mock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = [
        None,
        RuntimeError("db down"),
    ]
    graph = MagicMock()
    graph.invoke.side_effect = RuntimeError("boom")

    with caplog.at_level("ERROR"):
        _run_pipeline(graph, sb)  # must not raise

    assert "db down" in caplog.text


def test_run_pipeline_persist_error_marks_failed():
    """A DB error while writing the result is still a failure, not a crash."""
    sb = _supabase_mock()
    graph = MagicMock()
    graph.invoke.return_value = {"briefing_content": {}, "warnings": []}
    execute = sb.table.return_value.update.return_value.eq.return_value.eq.return_value
    execute.execute.side_effect = [None, RuntimeError("write failed"), None]

    _run_pipeline(graph, sb)

    assert _updates(sb)[-1]["status"] == "failed"


# --- briefing chunk writer wiring (specs/briefing-chunk-writer.md scenarios 5, 6, 7) ---


def test_run_pipeline_writes_chunks_after_complete():
    sb = _supabase_mock()
    graph = MagicMock()
    graph.invoke.return_value = {
        "briefing_content": {"company_overview": {"summary": "x"}},
        "warnings": [],
    }
    _run_pipeline(graph, sb)
    args = _run_pipeline.writer.call_args.args
    assert args[:4] == ("user-1", "b-1", "Stripe", "Backend Engineer")
    assert args[4]["company_overview"]["summary"] == "x"
    assert _updates(sb)[-1]["status"] == "complete"


@pytest.mark.parametrize("error", [RuntimeError("openai down"), ValueError("no key")])
def test_chunk_writer_failure_keeps_briefing_complete(error, caplog):
    sb = _supabase_mock()
    graph = MagicMock()
    graph.invoke.return_value = {"briefing_content": {}, "warnings": []}

    def boom(*a, **k):
        raise error

    with (
        patch.object(pipeline, "_get_supabase", return_value=sb),
        patch.object(pipeline, "build_graph", return_value=graph),
        patch.object(pipeline, "write_briefing_chunks", side_effect=boom),
        caplog.at_level("ERROR"),
    ):
        pipeline.run_pipeline("b-1", "user-1", "Stripe")  # must not raise

    updates = _updates(sb)
    assert updates[-1]["status"] == "complete"
    assert not any(u.get("status") == "failed" for u in updates)
    assert str(error) in caplog.text


def test_failed_pipeline_writes_no_chunks():
    sb = _supabase_mock()
    graph = MagicMock()
    graph.invoke.side_effect = RuntimeError("tavily down")
    _run_pipeline(graph, sb)
    _run_pipeline.writer.assert_not_called()
