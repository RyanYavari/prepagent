"""Plumbing and log hygiene for the optional job description
(specs/job-description-input.md): request-scoped, never stored, never logged."""

import inspect
import json
import logging
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents import pipeline
from dependencies.auth import CurrentUser, get_current_user
from main import app
from services.briefings import create_pending_briefing

MARKER = "UNIQUE-JD-MARKER-9c1e"
JD = f"Backend Engineer\n- 4+ years building services {MARKER}"


# --- POST /briefings ---------------------------------------------------------


@pytest.fixture
def client():
    uid = str(uuid4())

    async def _user():
        return CurrentUser(user_id=uid, email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    c = TestClient(app)
    c.user_id = uid
    yield c
    app.dependency_overrides.clear()


def _supabase():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [
        {
            "id": "b-1",
            "user_id": "u",
            "company": "Stripe",
            "interviewer": None,
            "role": "Engineer",
            "interview_date": None,
            "status": "pending",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    return sb


def _post(client, **body):
    sb = _supabase()
    with (
        patch("routers.research._get_supabase", return_value=sb),
        patch("routers.research.run_pipeline") as run,
    ):
        resp = client.post("/briefings", json={"company": "Stripe", **body})
    return resp, run, sb


def test_jd_is_passed_to_the_pipeline_and_not_inserted(client):
    resp, run, sb = _post(client, job_description=JD)
    assert resp.status_code == 201
    assert run.call_args.kwargs["job_description"] == JD
    row = sb.table.return_value.insert.call_args.args[0]
    assert "job_description" not in row
    assert MARKER not in json.dumps(row)
    # nothing else written during the request carries it either
    for call in sb.mock_calls:
        assert MARKER not in repr(call)
    assert MARKER not in resp.text  # never returned to the client


@pytest.mark.parametrize(
    "absent", [{}, {"job_description": None}, {"job_description": "  \n "}]
)
def test_absent_jd_means_none(client, absent):
    resp, run, _ = _post(client, **absent)
    assert resp.status_code == 201
    assert run.call_args.kwargs["job_description"] is None


# --- calendar path -----------------------------------------------------------


def test_calendar_built_fields_cannot_carry_a_jd():
    from services.calendar_sync import briefing_fields

    assert "job_description" not in inspect.signature(briefing_fields).parameters
    fields = briefing_fields("Acme", "Engineer", ["Pat"], "2026-06-01")
    assert fields.job_description is None

    start = MagicMock()
    sb = _supabase()
    create_pending_briefing(sb, "u", fields, start)
    assert start.call_args.kwargs["job_description"] is None


# --- run_pipeline ------------------------------------------------------------


def _nodes(synthesis=None):
    mocks = {
        "company_research_node": lambda s: {"company_research": {}, "warnings": []},
        "interviewer_research_node": lambda s: {
            "interviewer_research": {},
            "warnings": [],
        },
        "rag_retrieval_node": lambda s: {"retrieved_context": {}, "warnings": []},
        "synthesis_node": synthesis
        or (lambda s: {"briefing_content": {"company_overview": {}}, "warnings": []}),
    }
    return [
        patch.object(pipeline, n, MagicMock(side_effect=f)) for n, f in mocks.items()
    ]


def _run(synthesis=None, jd=JD, deadline=None, env=None):
    sb = MagicMock()
    patches = _nodes(synthesis)
    seen: dict = {}
    real_build = pipeline.build_graph

    def spy_build():
        graph = real_build()
        real_invoke = graph.invoke

        def invoke(state, config=None):
            seen["state"], seen["config"] = dict(state), config
            return real_invoke(state, config=config)

        graph.invoke = invoke
        return graph

    writer = MagicMock()
    ctx = [
        patch.object(pipeline, "_get_supabase", return_value=sb),
        patch.object(pipeline, "build_graph", spy_build),
        patch.object(pipeline, "write_briefing_chunks", writer),
        *patches,
    ]
    if deadline is not None:
        ctx.append(
            patch.object(
                pipeline,
                "env_float",
                side_effect=lambda name: (
                    deadline if name == "PIPELINE_DEADLINE_SECONDS" else 1.0
                ),
            )
        )
    for p in ctx:
        p.start()
    try:
        pipeline.run_pipeline(
            "b-1", "user-1", "Stripe", "Jane", "Engineer", job_description=jd
        )
    finally:
        for p in reversed(ctx):
            p.stop()
    return sb, seen, writer


def test_run_pipeline_puts_the_jd_in_graph_state():
    _, seen, _ = _run()
    assert seen["state"]["job_description"] == JD


def test_run_pipeline_defaults_to_no_jd():
    sb = MagicMock()
    with (
        patch.object(pipeline, "_get_supabase", return_value=sb),
        patch.object(pipeline, "build_graph") as build,
        patch.object(pipeline, "write_briefing_chunks"),
    ):
        build.return_value.invoke.return_value = {
            "briefing_content": {},
            "warnings": [],
        }
        pipeline.run_pipeline("b-1", "user-1", "Stripe")
    assert build.return_value.invoke.call_args.args[0]["job_description"] is None


def _assert_clean(sb, seen, caplog, writer):
    assert MARKER not in caplog.text
    for call in sb.mock_calls:  # every DB write, incl. content and failure_reason
        assert MARKER not in repr(call)
    assert MARKER not in repr(seen["config"])  # LangGraph metadata / tags / run name
    for call in writer.mock_calls:
        assert MARKER not in repr(call)


def test_jd_never_logged_or_persisted_on_success(caplog):
    with caplog.at_level(logging.DEBUG):
        sb, seen, writer = _run()
    assert seen["state"]["job_description"] == JD  # it did reach the graph
    _assert_clean(sb, seen, caplog, writer)


def test_jd_never_logged_or_persisted_on_node_error(caplog):
    def boom(state):
        raise RuntimeError("synthesis failed")

    with caplog.at_level(logging.DEBUG):
        sb, seen, writer = _run(synthesis=boom)
    assert "event=error error=RuntimeError" in caplog.text
    _assert_clean(sb, seen, caplog, writer)
    assert any("failed" in repr(c) for c in sb.mock_calls)


def test_jd_never_logged_or_persisted_on_timeout(caplog):
    def slow(state):
        time.sleep(0.5)
        return {"briefing_content": {}, "warnings": []}

    with caplog.at_level(logging.DEBUG):
        sb, seen, writer = _run(synthesis=slow, deadline=0.1)
    assert "deadline" in caplog.text
    _assert_clean(sb, seen, caplog, writer)
