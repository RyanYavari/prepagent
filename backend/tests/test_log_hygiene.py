"""CORS tightening and log hygiene for user-supplied text (Slice 6)."""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError

from dependencies.auth import CurrentUser, get_current_user
from main import app
from tests.calendar_helpers import FakeSupabase
from tests.test_job_description_pipeline import _run

ORIGIN = "http://localhost:3000"  # the default FRONTEND_URL in tests

RESUME_MARK = "RESUME-MARKER-4471"
COMPANY_MARK = "CompanyMarker4471"
PERSON_MARK = "InterviewerMarker4471"
EMAIL_MARK = "marker4471@example.com"
# Postgres puts the whole failing row in the error detail.
ROW_ECHO = "Failing row contains ({}, secret-row-content)"


@pytest.fixture
def client():
    async def _user():
        return CurrentUser(user_id=str(uuid4()), email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_pipeline():
    with patch("routers.research.run_pipeline"), patch("routers.calendar.run_pipeline"):
        yield


# --- CORS -------------------------------------------------------------------------


def _preflight(client, origin, method="POST"):
    return client.options(
        "/briefings",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_preflight_from_frontend_origin_is_allowed_without_credentials():
    r = _preflight(TestClient(app), ORIGIN)
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in r.headers
    allowed = {m.strip() for m in r.headers["access-control-allow-methods"].split(",")}
    assert allowed == {"GET", "POST", "DELETE", "OPTIONS"}
    headers = r.headers["access-control-allow-headers"].lower()
    assert "authorization" in headers and "content-type" in headers


def test_retry_after_is_exposed_to_the_browser(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "1")
    client = TestClient(app)
    client.get("/auth/google", headers={"Origin": ORIGIN})
    r = client.get("/auth/google", headers={"Origin": ORIGIN})
    assert r.status_code == 429
    assert "retry-after" in r.headers["access-control-expose-headers"].lower()


def test_preflight_from_another_origin_gets_no_allow_origin():
    r = _preflight(TestClient(app), "https://evil.example.com")
    assert "access-control-allow-origin" not in r.headers


def test_disallowed_method_is_refused():
    r = _preflight(TestClient(app), ORIGIN, method="PUT")
    assert r.status_code == 400


def test_simple_request_from_other_origin_gets_no_allow_origin():
    r = TestClient(app).get("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in r.headers


# --- logs never carry user text -------------------------------------------------------


def _all_logs(caplog):
    return (
        "\n".join(
            r.getMessage() + (repr(r.exc_info[1]) if r.exc_info else "")
            for r in caplog.records
        )
        + caplog.text
    )


def test_resume_save_failure_does_not_log_the_row(client, caplog):
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.side_effect = (
        Exception(ROW_ECHO.format(RESUME_MARK))
    )
    with (
        patch("routers.research._get_supabase", return_value=sb),
        patch("routers.research.check_briefing_allowed"),
        caplog.at_level(logging.DEBUG),
    ):
        r = client.post(
            "/briefings", json={"company": "Acme", "resume_text": RESUME_MARK}
        )
    assert r.status_code == 500
    logs = _all_logs(caplog)
    assert "Failed to save resume" in logs  # still diagnosable
    assert RESUME_MARK not in logs and "secret-row-content" not in logs


def test_embedding_failure_does_not_log_provider_message(client, caplog):
    with (
        patch("routers.research._get_supabase", return_value=MagicMock()),
        patch("routers.research.check_briefing_allowed"),
        patch(
            "routers.research.process_resume_embedding",
            side_effect=OpenAIError(f"bad input {RESUME_MARK}"),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        r = client.post(
            "/briefings", json={"company": "Acme", "resume_text": RESUME_MARK}
        )
    assert r.status_code == 503
    logs = _all_logs(caplog)
    assert "OpenAIError" in logs and RESUME_MARK not in logs


def test_embedding_config_error_does_not_log_message(client, caplog):
    with (
        patch("routers.research._get_supabase", return_value=MagicMock()),
        patch("routers.research.check_briefing_allowed"),
        patch(
            "routers.research.process_resume_embedding",
            side_effect=ValueError(f"bad {RESUME_MARK}"),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        r = client.post(
            "/briefings", json={"company": "Acme", "resume_text": RESUME_MARK}
        )
    assert r.status_code == 500
    assert RESUME_MARK not in _all_logs(caplog)


def test_briefing_insert_failure_does_not_log_the_row(client, caplog):
    with (
        patch("routers.research._get_supabase", return_value=MagicMock()),
        patch("routers.research.check_briefing_allowed"),
        patch(
            "routers.research.create_pending_briefing",
            side_effect=Exception(ROW_ECHO.format(f"{COMPANY_MARK} {PERSON_MARK}")),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        r = client.post(
            "/briefings", json={"company": COMPANY_MARK, "interviewer": PERSON_MARK}
        )
    assert r.status_code == 500
    logs = _all_logs(caplog)
    assert "Failed to create briefing" in logs
    assert COMPANY_MARK not in logs and PERSON_MARK not in logs
    assert COMPANY_MARK not in r.text


def test_signin_user_upsert_failure_does_not_log_the_email(caplog):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = (
        Exception(ROW_ECHO.format(EMAIL_MARK))
    )
    with (
        patch("routers.auth._get_supabase", return_value=sb),
        patch(
            "routers.auth.exchange_code_for_tokens",
            new=AsyncMock(return_value={"email": EMAIL_MARK, "name": "N"}),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        r = TestClient(app).get("/auth/callback", params={"code": "c", "state": "s"})
    assert r.status_code == 500
    logs = _all_logs(caplog)
    assert "Database error during user upsert" in logs
    assert EMAIL_MARK not in logs


def test_calendar_confirm_failure_does_not_log_the_row(caplog):
    db = FakeSupabase()
    row = {
        "id": str(uuid4()),
        "user_id": "u-1",
        "google_event_id": "e",
        "event_start": "2026-11-18T12:00:00+00:00",
        "status": "needs_confirmation",
        "classification": {"company": COMPANY_MARK, "interviewer_names": [PERSON_MARK]},
    }

    async def _user():
        return CurrentUser(user_id="u-1", email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    db.tables["calendar_detections"] = [row]
    with (
        patch("routers.calendar._get_supabase", return_value=db),
        patch(
            "routers.calendar.create_pending_briefing",
            side_effect=Exception(ROW_ECHO.format(f"{COMPANY_MARK} {PERSON_MARK}")),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        r = TestClient(app).post(f"/calendar/detections/{row['id']}/confirm")
    app.dependency_overrides.clear()
    assert r.status_code == 500
    logs = _all_logs(caplog)
    assert "Failed to create briefing from detection" in logs
    assert COMPANY_MARK not in logs and PERSON_MARK not in logs


# --- the pipeline never logs company / interviewer / role ------------------------------


def _assert_no_names(caplog):
    logs = _all_logs(caplog)
    for text in ("Stripe", "Jane", "Engineer"):
        assert text not in logs


def test_pipeline_logs_no_names_on_success(caplog):
    with caplog.at_level(logging.DEBUG):
        _run()
    assert "pipeline" in caplog.text
    _assert_no_names(caplog)


def test_pipeline_logs_no_names_on_node_error(caplog):
    def boom(state):
        raise RuntimeError("synthesis failed")

    with caplog.at_level(logging.DEBUG):
        _run(synthesis=boom)
    assert "event=error" in caplog.text
    _assert_no_names(caplog)


def test_pipeline_logs_no_names_on_timeout(caplog):
    def slow(state):
        time.sleep(0.5)
        return {"briefing_content": {}, "warnings": []}

    with caplog.at_level(logging.DEBUG):
        _run(synthesis=slow, deadline=0.1)
    assert "deadline" in caplog.text
    _assert_no_names(caplog)


# --- pipeline / calendar paths whose exception messages carry user text ---------------

from agents import pipeline


def test_pipeline_failure_with_prompt_text_in_message_is_not_logged(caplog):
    def boom(state):
        raise RuntimeError(f"validation error input_value={RESUME_MARK} {COMPANY_MARK}")

    with caplog.at_level(logging.DEBUG):
        _run(synthesis=boom)
    logs = _all_logs(caplog)
    assert "Briefing pipeline failed" in logs and "RuntimeError" in logs
    assert RESUME_MARK not in logs and COMPANY_MARK not in logs


def test_chunk_writer_failure_is_not_logged_with_its_message(caplog):
    with (
        patch.object(
            pipeline,
            "write_briefing_chunks",
            side_effect=Exception(ROW_ECHO.format(RESUME_MARK)),
        ),
        caplog.at_level(logging.DEBUG),
    ):
        pipeline._write_chunks("b-1", "u-1", "Acme", "Eng", {})
    logs = _all_logs(caplog)
    assert "Could not write briefing chunks" in logs
    assert RESUME_MARK not in logs


def test_calendar_classifier_validation_error_is_not_logged(caplog):
    from agents import calendar_detect
    from tests.calendar_helpers import norm_event

    bad = MagicMock()
    bad.invoke.return_value = {"is_interview": "banana", "note": PERSON_MARK}
    with (
        patch.object(calendar_detect, "structured_llm", return_value=bad),
        caplog.at_level(logging.DEBUG),
    ):
        calendar_detect.classify_event(norm_event(title=PERSON_MARK))
    logs = _all_logs(caplog)
    assert "invalid structure" in logs
    assert PERSON_MARK not in logs
