"""Timeouts, bounded retries, pipeline deadline, per-node timing and stale sweep."""

import threading
import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
import requests

from agents import llm, pipeline
from main import _startup_sweep as real_startup_sweep  # conftest patches the attribute
from services import briefings, embeddings, net_config, supabase_client, web_search
from services.net_config import retry_call


@pytest.fixture(autouse=True)
def no_sleep():
    # Patch net_config's own `time` reference only; patching `time.sleep` itself
    # would also turn the sleeps in these tests into no-ops.
    with patch("services.net_config.time") as fake_time:
        yield fake_time.sleep


# --- env-configurable limits ---


def test_defaults_and_bad_env_fall_back(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    assert net_config.env_float("LLM_TIMEOUT_SECONDS") == 45.0
    for bad in ("abc", "-5", "0", "99999", ""):
        monkeypatch.setenv("LLM_TIMEOUT_SECONDS", bad)
        assert net_config.env_float("LLM_TIMEOUT_SECONDS") == 45.0
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "20")
    assert net_config.env_float("LLM_TIMEOUT_SECONDS") == 20.0
    monkeypatch.setenv("TAVILY_MAX_RETRIES", "3")
    assert net_config.env_int("TAVILY_MAX_RETRIES") == 3
    monkeypatch.setenv("TAVILY_MAX_RETRIES", "x")
    assert net_config.env_int("TAVILY_MAX_RETRIES") == 1


# --- retry helper ---


def test_retry_then_success(no_sleep):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("dns")
        return "ok"

    assert retry_call(flaky, retries=2, retry_on=(ConnectionError,), label="t") == "ok"
    assert len(calls) == 3
    assert no_sleep.call_count == 2


def test_retry_exhausted_raises_last_error():
    fn = MagicMock(side_effect=ConnectionError("dns"))
    with pytest.raises(ConnectionError):
        retry_call(fn, retries=2, retry_on=(ConnectionError,), label="t")
    assert fn.call_count == 3  # 1 try + 2 retries: bounded


def test_non_retryable_error_is_not_retried():
    fn = MagicMock(side_effect=ValueError("bad"))
    with pytest.raises(ValueError):
        retry_call(fn, retries=3, retry_on=(ConnectionError,), label="t")
    assert fn.call_count == 1


def test_retry_log_has_class_name_not_message(caplog):
    fn = MagicMock(side_effect=[ConnectionError("https://secret.example/?key=abc"), 1])
    with caplog.at_level("WARNING"):
        retry_call(fn, retries=1, retry_on=(ConnectionError,), label="t")
    assert "ConnectionError" in caplog.text
    assert "secret.example" not in caplog.text


# --- every outbound client gets a timeout ---


def test_llm_has_timeout_and_bounded_retries(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    with patch("agents.llm.ChatAnthropic") as ctor:
        llm.structured_llm(MagicMock())
    assert ctor.call_args.kwargs["timeout"] == 30.0
    assert ctor.call_args.kwargs["max_retries"] == 2


def test_embeddings_client_has_timeout_and_retries(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    with patch("services.embeddings.OpenAI") as ctor:
        ctor.return_value.embeddings.create.return_value.data = [
            MagicMock(embedding=[0.0])
        ]
        embeddings.embed_text("x")
    assert ctor.call_args.kwargs["timeout"] == 15.0
    assert ctor.call_args.kwargs["max_retries"] == 2


def test_tavily_passes_timeout_and_retries_transient_errors(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    client = MagicMock()
    client.search.side_effect = [
        requests.exceptions.ConnectionError("dns"),
        TimeoutError(12),
        {"results": [{"url": "https://a.com"}]},
    ]
    monkeypatch.setenv("TAVILY_MAX_RETRIES", "2")
    with patch("services.web_search.TavilyClient", return_value=client):
        results = web_search.search_web("Stripe")
    assert len(results) == 1
    assert client.search.call_count == 3
    assert all(c.kwargs["timeout"] == 12.0 for c in client.search.call_args_list)


def test_tavily_retries_are_bounded(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    client = MagicMock()
    client.search.side_effect = TimeoutError(12)
    with (
        patch("services.web_search.TavilyClient", return_value=client),
        pytest.raises(TimeoutError),
    ):
        web_search.search_web("Stripe")
    assert client.search.call_count == 2  # default: 1 try + 1 retry


KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.abc"


def test_supabase_client_has_timeout_and_keeps_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_TIMEOUT_SECONDS", "7")
    session = supabase_client.create_client(
        "https://abc.supabase.co", KEY
    ).postgrest.session
    assert session.timeout.read == 7.0
    assert "apikey" in session.headers


def test_supabase_execute_retries_connection_errors_only():
    builder = MagicMock()
    builder.execute.side_effect = [httpx.ConnectError("dns"), "rows"]
    assert supabase_client.execute(builder) == "rows"

    builder = MagicMock()
    builder.execute.side_effect = httpx.ReadTimeout("slow")  # may have been applied
    with pytest.raises(httpx.ReadTimeout):
        supabase_client.execute(builder)
    assert builder.execute.call_count == 1

    builder = MagicMock()
    builder.execute.side_effect = httpx.ConnectError("dns")
    with pytest.raises(httpx.ConnectError):
        supabase_client.execute(builder)
    assert builder.execute.call_count == 3  # bounded


# --- pipeline deadline ---


def _updates(sb):
    return [c.args[0] for c in sb.table.return_value.update.call_args_list]


def _run(graph, sb, deadline=0.2):
    def fake_env(name):
        return deadline if name == "PIPELINE_DEADLINE_SECONDS" else 1.0

    with (
        patch.object(pipeline, "_get_supabase", return_value=sb),
        patch.object(pipeline, "build_graph", return_value=graph),
        patch.object(pipeline, "write_briefing_chunks") as writer,
        patch.object(pipeline, "env_float", side_effect=fake_env),
    ):
        start = time.monotonic()
        pipeline.run_pipeline("b-1", "user-1", "Stripe")
        return time.monotonic() - start, writer


def test_deadline_marks_failed_with_generic_reason_and_returns_promptly(caplog):
    release = threading.Event()
    graph = MagicMock()
    graph.invoke.side_effect = lambda *a, **k: (
        release.wait(5)
        or {"briefing_content": {"company_overview": {"summary": "LATE SECRET"}}}
    )
    sb = MagicMock()

    with caplog.at_level("INFO"):
        elapsed, writer = _run(graph, sb)
    release.set()

    assert elapsed < 2
    last = _updates(sb)[-1]
    assert last == {"status": "failed", "failure_reason": pipeline.REASON_TIMEOUT}
    assert "deadline" in caplog.text
    writer.assert_not_called()
    time.sleep(0.2)  # a late result from the abandoned thread is never persisted
    assert not any(u.get("status") == "complete" for u in _updates(sb))
    assert "LATE SECRET" not in caplog.text


def test_node_error_is_not_mistaken_for_deadline():
    graph = MagicMock()
    graph.invoke.side_effect = TimeoutError(
        "tavily timed out"
    )  # same type as a deadline
    sb = MagicMock()
    _run(graph, sb, deadline=5)
    assert _updates(sb)[-1]["failure_reason"] == pipeline.REASON_ERROR


def test_failure_reason_column_missing_falls_back_to_status_only():
    sb = MagicMock()
    execute = sb.table.return_value.update.return_value.eq.return_value.eq.return_value
    execute.execute.side_effect = [None, RuntimeError("no column"), None]
    graph = MagicMock()
    graph.invoke.side_effect = RuntimeError("boom")
    _run(graph, sb, deadline=5)
    assert _updates(sb)[-1] == {"status": "failed"}


def test_straggler_thread_stops_before_next_node_after_deadline():
    release = threading.Event()
    ran = []

    def company(state):
        release.wait(5)
        return {"company_research": {}, "warnings": []}

    def other(name):
        def node(state):
            ran.append(name)
            return {
                "warnings": [],
                **({"briefing_content": {}} if name == "syn" else {}),
            }

        return node

    sb = MagicMock()
    with (
        patch.object(pipeline, "company_research_node", company),
        patch.object(pipeline, "interviewer_research_node", other("iv")),
        patch.object(pipeline, "rag_retrieval_node", other("rag")),
        patch.object(pipeline, "synthesis_node", other("syn")),
    ):
        _run(pipeline.build_graph(), sb)
        release.set()
        time.sleep(0.5)
    assert "rag" not in ran and "syn" not in ran


# --- per-node timing logs ---


def test_node_start_end_and_pipeline_elapsed_logged_without_content(caplog):
    def node(key):
        return lambda s: {key: {"summary": "SECRET-CONTENT"}, "warnings": []}

    sb = MagicMock()
    with (
        patch.object(pipeline, "company_research_node", node("company_research")),
        patch.object(
            pipeline, "interviewer_research_node", node("interviewer_research")
        ),
        patch.object(
            pipeline,
            "rag_retrieval_node",
            lambda s: {"retrieved_context": {}, "warnings": []},
        ),
        patch.object(
            pipeline,
            "synthesis_node",
            lambda s: {"briefing_content": {}, "warnings": []},
        ),
        caplog.at_level("INFO", logger="agents.pipeline"),
    ):
        _run(pipeline.build_graph(), sb, deadline=5)

    for name in (
        "company_research",
        "interviewer_research",
        "rag_retrieval",
        "synthesis",
    ):
        assert f"node={name} briefing_id=b-1 event=start" in caplog.text
        assert f"node={name} briefing_id=b-1 event=end elapsed=" in caplog.text
    assert "pipeline briefing_id=b-1 event=end status=complete elapsed=" in caplog.text
    assert "SECRET-CONTENT" not in caplog.text


def test_node_error_logs_class_only(caplog):
    def boom(state):
        raise RuntimeError("https://x.example/?token=SECRET")

    wrapped = pipeline._timed("company_research", boom)
    with caplog.at_level("INFO", logger="agents.pipeline"), pytest.raises(RuntimeError):
        wrapped({"briefing_id": "b-1"})
    assert "event=error error=RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text


# --- stale-running sweep ---


def _sweep_sb(data=None):
    sb = MagicMock()
    chain = sb.table.return_value.update.return_value.eq.return_value.lt.return_value
    chain.eq.return_value.execute.return_value.data = data or []
    chain.execute.return_value.data = data or []
    return sb, chain


def test_sweep_marks_old_running_failed_scoped_to_user():
    sb, chain = _sweep_sb([{"id": "1"}, {"id": "2"}])
    assert briefings.sweep_stale_running(sb, "user-1") == 2

    sb.table.assert_called_with("briefings")
    update = sb.table.return_value.update
    assert update.call_args.args[0] == {
        "status": "failed",
        "failure_reason": briefings.REASON_STALE,
    }
    update.return_value.eq.assert_called_with("status", "running")
    lt = update.return_value.eq.return_value.lt
    col, cutoff = lt.call_args.args
    assert col == "created_at"
    from datetime import UTC, datetime, timedelta

    age = datetime.now(UTC) - datetime.fromisoformat(cutoff)
    assert timedelta(minutes=9, seconds=50) < age < timedelta(minutes=10, seconds=10)
    chain.eq.assert_called_with("user_id", "user-1")


def test_sweep_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("STALE_RUNNING_MINUTES", "30")
    sb, _ = _sweep_sb()
    briefings.sweep_stale_running(sb, "u")
    from datetime import UTC, datetime, timedelta

    cutoff = (
        sb.table.return_value.update.return_value.eq.return_value.lt.call_args.args[1]
    )
    age = datetime.now(UTC) - datetime.fromisoformat(cutoff)
    assert timedelta(minutes=29) < age < timedelta(minutes=31)


def test_sweep_without_user_covers_everyone():
    sb, chain = _sweep_sb([{"id": "1"}])
    assert briefings.sweep_stale_running(sb) == 1
    chain.eq.assert_not_called()


def test_sweep_falls_back_when_failure_reason_column_missing():
    sb = MagicMock()
    chain = sb.table.return_value.update.return_value.eq.return_value.lt.return_value
    chain.execute.side_effect = [RuntimeError("no column"), MagicMock(data=[{"id": 1}])]
    assert briefings.sweep_stale_running(sb) == 1
    assert sb.table.return_value.update.call_args.args[0] == {"status": "failed"}


def test_startup_sweep_swallows_errors(caplog):
    with (
        patch("services.supabase_client.get_service_client", side_effect=RuntimeError),
        caplog.at_level("ERROR"),
    ):
        real_startup_sweep()  # must not raise
    assert "Startup stale briefing sweep failed" in caplog.text


def test_startup_sweep_runs_on_app_startup():
    from fastapi.testclient import TestClient

    from main import app

    with patch("main._startup_sweep") as sweep, TestClient(app):
        pass
    sweep.assert_called_once()


def test_list_endpoint_sweeps_and_survives_sweep_failure():
    from fastapi.testclient import TestClient

    from dependencies.auth import CurrentUser, get_current_user
    from main import app
    from routers import research

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-1", email="a@b.c"
    )
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.count = 0
    try:
        with (
            patch.object(research, "_get_supabase", return_value=sb),
            patch.object(
                research, "sweep_stale_running", side_effect=RuntimeError("db")
            ) as sweep,
        ):
            resp = TestClient(app).get("/briefings")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    sweep.assert_called_once_with(sb, "user-1")
