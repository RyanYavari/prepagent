"""Signup gate and kill switches (specs/deployment.md, Slice 3)."""

import logging
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dependencies.auth import CurrentUser, get_current_user
from main import app
from services import limits
from tests.calendar_helpers import FakeSupabase

NEW_EMAIL = "newcomer@example.com"
OWNER = "owner@example.com"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for name in (
        "SIGNUPS_ENABLED",
        "ALLOWED_EMAILS",
        "BRIEFINGS_ENABLED",
        "CALENDAR_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_real_pipeline():
    with (
        patch("routers.research.run_pipeline") as p,
        patch("routers.calendar.run_pipeline"),
    ):
        yield p


@pytest.fixture
def user_id():
    return str(uuid4())


@pytest.fixture
def client(user_id):
    async def _user():
        return CurrentUser(user_id=user_id, email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- flag parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, True),
        ("", True),
        ("true", True),
        ("1", True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("garbage", True),
    ],
)
def test_flag_defaults_to_enabled_on_unknown_values(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("SIGNUPS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("SIGNUPS_ENABLED", raw)
    assert limits.signups_enabled() is expected


def test_allowed_emails_parsing(monkeypatch):
    assert limits.allowed_emails() is None
    monkeypatch.setenv("ALLOWED_EMAILS", "  ")
    assert limits.allowed_emails() is None
    monkeypatch.setenv("ALLOWED_EMAILS", " A@x.com, b@x.com ,,")
    assert limits.allowed_emails() == {"a@x.com", "b@x.com"}


# --- sign-in gate ------------------------------------------------------------


def _signin(db, email):
    with (
        patch("routers.auth._get_supabase", return_value=db),
        patch(
            "routers.auth.exchange_code_for_tokens",
            new=AsyncMock(return_value={"email": email, "name": "N"}),
        ),
    ):
        return TestClient(app).get("/auth/callback", params={"code": "c", "state": "s"})


def _seed_user(db, email):
    db.tables.setdefault("users", []).append({"id": str(uuid4()), "email": email})


def test_default_new_user_can_sign_up():
    db = FakeSupabase()
    assert _signin(db, NEW_EMAIL).status_code == 200
    assert [u["email"] for u in db.rows("users")] == [NEW_EMAIL]


def test_signups_disabled_refuses_new_email_and_inserts_nothing(monkeypatch):
    monkeypatch.setenv("SIGNUPS_ENABLED", "false")
    db = FakeSupabase()
    r = _signin(db, NEW_EMAIL)
    assert r.status_code == 403
    assert db.rows("users") == []
    assert "token" not in r.text


def test_signups_disabled_still_lets_existing_user_in(monkeypatch):
    monkeypatch.setenv("SIGNUPS_ENABLED", "false")
    db = FakeSupabase()
    _seed_user(db, OWNER)
    r = _signin(db, OWNER)
    assert r.status_code == 200 and r.json()["email"] == OWNER
    assert len(db.rows("users")) == 1


def test_allowlist_blocks_others_even_existing_users(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", OWNER)
    db = FakeSupabase()
    _seed_user(db, "former@example.com")
    assert _signin(db, "former@example.com").status_code == 403
    assert _signin(db, NEW_EMAIL).status_code == 403
    assert [u["email"] for u in db.rows("users")] == ["former@example.com"]


def test_allowlist_allows_listed_email_case_insensitively(monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "Owner@Example.com")
    db = FakeSupabase()
    assert _signin(db, OWNER).status_code == 200


def test_refusal_is_generic_and_logs_no_email(monkeypatch, caplog):
    monkeypatch.setenv("ALLOWED_EMAILS", OWNER)
    with caplog.at_level(logging.DEBUG):
        r = _signin(FakeSupabase(), NEW_EMAIL)
    assert r.status_code == 403
    assert NEW_EMAIL not in r.text and NEW_EMAIL not in caplog.text
    assert OWNER not in r.text


# --- briefing creation switch -----------------------------------------------


def test_briefings_disabled_blocks_create_before_any_work(
    monkeypatch, client, _no_real_pipeline
):
    monkeypatch.setenv("BRIEFINGS_ENABLED", "false")
    db = FakeSupabase()
    with (
        patch("routers.research._get_supabase", return_value=db),
        patch("routers.research.process_resume_embedding") as embed,
    ):
        r = client.post("/briefings", json={"company": "Acme", "resume_text": "x"})
    assert r.status_code == 503
    embed.assert_not_called()
    assert db.rows("briefings") == [] and db.rows("users") == []
    _no_real_pipeline.assert_not_called()


def test_briefings_disabled_reads_still_work(monkeypatch, client, user_id):
    monkeypatch.setenv("BRIEFINGS_ENABLED", "false")
    db = FakeSupabase()
    db.tables["briefings"] = [
        {
            "id": str(uuid4()),
            "user_id": user_id,
            "company": "Acme",
            "interviewer": None,
            "role": None,
            "status": "complete",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    with patch("routers.research._get_supabase", return_value=db):
        r = client.get("/briefings")
    assert r.status_code == 200 and r.json()["total"] >= 1


def _detection(db, user_id):
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "google_event_id": "evt1",
        "event_start": "2026-11-18T12:00:00+00:00",
        "status": "needs_confirmation",
        "classification": {"company": "Acme", "role": "Eng", "interviewer_names": []},
    }
    db.tables.setdefault("calendar_detections", []).append(row)
    return row


def test_briefings_disabled_blocks_confirm_and_releases_detection(
    monkeypatch, client, user_id, _no_real_pipeline
):
    monkeypatch.setenv("BRIEFINGS_ENABLED", "false")
    db = FakeSupabase()
    d = _detection(db, user_id)
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert r.status_code == 503
    assert db.rows("briefings") == []
    assert db.rows("calendar_detections")[0]["status"] == "needs_confirmation"
    _no_real_pipeline.assert_not_called()


# --- calendar switch ---------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/calendar/connect"),
        ("get", "/calendar/status"),
        ("post", "/calendar/sync"),
        ("get", "/calendar/detections"),
        ("delete", "/calendar/connection"),
    ],
)
def test_calendar_disabled_returns_404(monkeypatch, client, method, path):
    monkeypatch.setenv("CALENDAR_ENABLED", "false")
    with patch("routers.calendar._get_supabase", return_value=FakeSupabase()):
        r = getattr(client, method)(path)
    assert r.status_code == 404


def test_calendar_enabled_by_default(client):
    assert client.get("/calendar/connect").status_code == 200


def test_blocked_confirm_still_answers_429_if_release_fails(
    monkeypatch, client, user_id
):
    monkeypatch.setenv("BRIEFINGS_ENABLED", "false")

    class FlakyRelease(FakeSupabase):
        def table(self, name):
            t = super().table(name)
            if name != "calendar_detections":
                return t
            real_update = t.update

            def update(values):
                if values.get("status") == "needs_confirmation":
                    raise RuntimeError("db hiccup")
                return real_update(values)

            t.update = update
            return t

    db = FlakyRelease()
    d = _detection(db, user_id)
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert r.status_code == 503
