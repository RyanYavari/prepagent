"""Request-side tests for the optional job description (specs/job-description-input.md)."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dependencies.auth import CurrentUser, get_current_user
from main import app
from models.briefing import BriefingCreate
from models.text_safety import clean_long_text

MARKER = "UNIQUE-JD-MARKER-7f3a"
LIMIT = 12_000


def _create(jd):
    return BriefingCreate(company="Acme", job_description=jd)


# --- clean_long_text / model -------------------------------------------------


def test_valid_jd_is_accepted_unchanged():
    jd = "Backend Engineer\n\nRequirements\n- 4+ years\n- C++ and <5ms latency {x}"
    assert _create(jd).job_description == jd


@pytest.mark.parametrize("empty", [None, "", "   ", "\n\t \n"])
def test_absent_null_and_whitespace_become_none(empty):
    assert _create(empty).job_description is None


def test_field_defaults_to_none():
    assert BriefingCreate(company="Acme").job_description is None


def test_exactly_at_limit_ok_and_over_limit_rejected():
    assert len(_create("a" * LIMIT).job_description) == LIMIT
    with pytest.raises(ValidationError):
        _create("a" * (LIMIT + 1))


def test_urls_markup_and_non_ascii_are_allowed():
    jd = "Apply at https://example.com/jobs <b>now</b> `code` {x} café 日本語"
    assert _create(jd).job_description == jd


def test_control_zero_width_bidi_and_nul_are_stripped_newlines_tabs_kept():
    zero_width, bidi_override, nul, bell = (chr(c) for c in (0x200B, 0x202E, 0, 7))
    jd = f"Req{zero_width}ui{bidi_override}re{nul}d\ta\r\nb{bell}"
    assert clean_long_text(jd) == "Required\ta\nb"


def test_crlf_normalised_and_blank_runs_collapsed():
    assert clean_long_text("a\r\n\r\n\r\n\r\n\r\nb\r\n") == "a\n\nb"
    assert clean_long_text("  hi  ") == "hi"


def test_limit_applies_to_the_raw_request_text():
    # the limit applies to the raw request; cleaning cannot be used to smuggle length
    with pytest.raises(ValidationError):
        _create("a" * (LIMIT + 1) + "\u200b")


# --- HTTP: 422 must not echo the JD -----------------------------------------


@pytest.fixture
def client():
    async def _user():
        return CurrentUser(user_id=str(uuid4()), email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_oversize_jd_returns_422_without_echoing_it_and_inserts_nothing(client):
    big = MARKER + "x" * LIMIT
    with (
        patch("routers.research._get_supabase") as sb,
        patch("routers.research.run_pipeline") as run,
    ):
        resp = client.post(
            "/briefings", json={"company": "Acme", "job_description": big}
        )
    assert resp.status_code == 422
    assert MARKER not in resp.text
    detail = resp.json()["detail"]
    assert any(e["loc"][-1] == "job_description" for e in detail)
    assert all("input" not in e for e in detail if e["loc"][-1] == "job_description")
    sb.assert_not_called()
    run.assert_not_called()


def test_other_422s_are_unchanged_and_still_report_input(client):
    resp = client.post("/briefings", json={"company": ""})
    assert resp.status_code == 422
    errors = resp.json()["detail"]
    assert errors[0]["loc"] == ["body", "company"]
    assert "input" in errors[0]


def test_unsafe_company_error_still_reports_input_while_jd_error_does_not(client):
    resp = client.post(
        "/briefings",
        json={"company": "<x>", "job_description": "a" * (LIMIT + 1)},
    )
    by_field = {e["loc"][-1]: e for e in resp.json()["detail"]}
    assert "input" in by_field["company"]
    assert "input" not in by_field["job_description"]


def test_missing_company_with_a_jd_does_not_echo_the_body(client):
    # pydantic's "missing" error carries the whole request body as `input`
    resp = client.post(
        "/briefings", json={"job_description": f"{MARKER} call 555-0100"}
    )
    assert resp.status_code == 422
    assert MARKER not in resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", "company"]


@pytest.mark.parametrize("body", [[MARKER], MARKER, {"company": 5, "x": MARKER}])
def test_non_object_or_wrong_typed_bodies_do_not_echo_the_body(client, body):
    resp = client.post("/briefings", json=body)
    assert resp.status_code == 422
    assert MARKER not in resp.text


def test_scalar_field_errors_still_report_input(client):
    resp = client.post("/briefings", json={"company": ""})
    assert resp.json()["detail"][0]["input"] == ""
