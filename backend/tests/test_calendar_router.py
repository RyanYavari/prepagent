"""Tests for the /calendar connection endpoints."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dependencies.auth import CurrentUser, get_current_user
from main import app
from services import google_auth
from services.token_crypto import decrypt_token


@pytest.fixture
def user_id():
    return str(uuid4())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    google_auth._pending_calendar.clear()


@pytest.fixture
def client(user_id):
    async def _user():
        return CurrentUser(user_id=user_id, email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sb():
    return MagicMock()


def test_connect_returns_calendar_only_url(client):
    r = client.get("/calendar/connect")
    assert r.status_code == 200
    url = r.json()["url"]
    assert "calendar.events.readonly" in url
    assert "gmail" not in url and "drive" not in url
    assert "include_granted_scopes=false" in url


def test_connect_requires_auth():
    assert TestClient(app).get("/calendar/connect").status_code in (401, 403)


def test_callback_stores_encrypted_token_for_jwt_user(client, user_id):
    sb = _sb()
    with (
        patch("routers.calendar._get_supabase", return_value=sb),
        patch(
            "routers.calendar.exchange_calendar_code",
            new=AsyncMock(
                return_value={
                    "refresh_token": "1//plain-refresh",
                    "scope": google_auth.CALENDAR_SCOPE,
                }
            ),
        ),
    ):
        r = client.post("/calendar/callback", json={"code": "c", "state": "s"})
    assert r.status_code == 200
    assert r.json()["connected"] is True
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["user_id"] == user_id
    assert row["encrypted_refresh_token"] != "1//plain-refresh"
    assert decrypt_token(row["encrypted_refresh_token"]) == "1//plain-refresh"
    assert row["status"] == "active"


def test_callback_body_cannot_set_user_id(client):
    r = client.post(
        "/calendar/callback", json={"code": "c", "state": "s", "user_id": "evil"}
    )
    assert r.status_code == 422


def test_callback_other_users_state_rejected(client, user_id):
    _, state = google_auth.build_calendar_authorization_url("someone-else")
    with patch("routers.calendar._get_supabase", return_value=_sb()) as sb:
        r = client.post("/calendar/callback", json={"code": "c", "state": state})
    assert r.status_code == 400
    sb.return_value.table.assert_not_called()


def test_callback_unknown_state_rejected(client):
    r = client.post("/calendar/callback", json={"code": "c", "state": "nope"})
    assert r.status_code == 400


def test_callback_connect_error_is_generic_and_logged(client, caplog):
    with (
        patch("routers.calendar._get_supabase", return_value=_sb()) as sb,
        patch(
            "routers.calendar.exchange_calendar_code",
            new=AsyncMock(
                side_effect=google_auth.CalendarConnectError("secret-detail-xyz")
            ),
        ),
        caplog.at_level(logging.ERROR, logger="routers.calendar"),
    ):
        r = client.post("/calendar/callback", json={"code": "c", "state": "s"})
    assert r.status_code == 400
    assert "secret-detail-xyz" not in r.text
    assert "secret-detail-xyz" in caplog.text
    sb.return_value.table.assert_not_called()


def test_callback_missing_encryption_key_fails_closed(client, monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    sb = _sb()
    revoke = AsyncMock(return_value=True)
    with (
        patch("routers.calendar._get_supabase", return_value=sb),
        patch(
            "routers.calendar.exchange_calendar_code",
            new=AsyncMock(
                return_value={
                    "refresh_token": "rt",
                    "scope": google_auth.CALENDAR_SCOPE,
                }
            ),
        ),
        patch("routers.calendar.revoke_token", new=revoke),
    ):
        r = client.post("/calendar/callback", json={"code": "c", "state": "s"})
    assert r.status_code == 500
    assert r.json()["detail"] == "Server configuration error"
    sb.table.assert_not_called()
    revoke.assert_awaited_once_with("rt")


def test_callback_db_failure_is_generic_and_revokes(client, caplog):
    sb = _sb()
    sb.table.return_value.upsert.return_value.execute.side_effect = RuntimeError(
        "db-secret-123"
    )
    revoke = AsyncMock(return_value=True)
    with (
        patch("routers.calendar._get_supabase", return_value=sb),
        patch(
            "routers.calendar.exchange_calendar_code",
            new=AsyncMock(
                return_value={
                    "refresh_token": "rt",
                    "scope": google_auth.CALENDAR_SCOPE,
                }
            ),
        ),
        patch("routers.calendar.revoke_token", new=revoke),
        caplog.at_level(logging.ERROR, logger="routers.calendar"),
    ):
        r = client.post("/calendar/callback", json={"code": "c", "state": "s"})
    assert r.status_code == 500
    assert "db-secret-123" not in r.text
    assert "db-secret-123" not in caplog.text  # class only: the row holds the token
    assert "Failed to store calendar connection" in caplog.text
    revoke.assert_awaited_once()


def test_status_not_connected(client):
    sb = _sb()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    with patch("routers.calendar._get_supabase", return_value=sb):
        r = client.get("/calendar/status")
    assert r.json() == {"connected": False, "status": None, "last_synced_at": None}


def test_status_connected(client):
    sb = _sb()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"status": "revoked", "last_synced_at": "2026-01-01T00:00:00Z"}
    ]
    with patch("routers.calendar._get_supabase", return_value=sb):
        r = client.get("/calendar/status")
    assert r.json()["connected"] is True
    assert r.json()["status"] == "revoked"


def _disconnect_sb(encrypted):
    sb = _sb()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
        [{"encrypted_refresh_token": encrypted}] if encrypted else []
    )
    return sb


def test_disconnect_revokes_and_deletes(client):
    from services.token_crypto import encrypt_token

    sb = _disconnect_sb(encrypt_token("rt-1"))
    revoke = AsyncMock(return_value=True)
    with (
        patch("routers.calendar._get_supabase", return_value=sb),
        patch("routers.calendar.revoke_token", new=revoke),
    ):
        r = client.delete("/calendar/connection")
    assert r.status_code == 200
    assert r.json()["connected"] is False
    revoke.assert_awaited_once_with("rt-1")
    tables = [c.args[0] for c in sb.table.call_args_list]
    assert "calendar_connections" in tables
    assert tables.count("calendar_detections") == 2
    sb.table.return_value.delete.assert_called()
    sb.table.return_value.update.assert_called_with({"classification": None})


def test_disconnect_revoke_failure_still_deletes(client, caplog):
    from services.token_crypto import encrypt_token

    sb = _disconnect_sb(encrypt_token("rt-1"))
    with (
        patch("routers.calendar._get_supabase", return_value=sb),
        patch("routers.calendar.revoke_token", new=AsyncMock(return_value=False)),
        caplog.at_level(logging.WARNING, logger="routers.calendar"),
    ):
        r = client.delete("/calendar/connection")
    assert r.status_code == 200
    sb.table.return_value.delete.assert_called()
    assert "did not confirm" in caplog.text


def test_disconnect_without_connection_is_noop_success(client):
    sb = _disconnect_sb(None)
    revoke = AsyncMock()
    with (
        patch("routers.calendar._get_supabase", return_value=sb),
        patch("routers.calendar.revoke_token", new=revoke),
    ):
        r = client.delete("/calendar/connection")
    assert r.status_code == 200
    revoke.assert_not_awaited()


# --- sync / detections / confirm / dismiss ----------------------------------

from services import calendar_sync as cs
from services.calendar import CalendarApiError
from tests.calendar_helpers import FakeSupabase


@pytest.fixture(autouse=True)
def _no_real_pipeline():
    with patch("routers.calendar.run_pipeline") as rp:
        yield rp


def test_sync_returns_summary(client):
    result = cs.SyncResult(events_scanned=3, needs_confirmation=1)
    with (
        patch("routers.calendar._get_supabase", return_value=_sb()),
        patch(
            "routers.calendar.sync_user_calendar", new=AsyncMock(return_value=result)
        ),
    ):
        r = client.post("/calendar/sync")
    assert r.status_code == 200
    assert r.json()["needs_confirmation"] == 1


@pytest.mark.parametrize(
    "exc,code",
    [
        (cs.CalendarNotConnectedError(), 409),
        (cs.CalendarReconnectRequired(), 409),
        (google_auth.CalendarUnavailableError("secret-google-body"), 503),
        (CalendarApiError("secret-google-body"), 503),
        (RuntimeError("secret-google-body"), 500),
    ],
)
def test_sync_errors_are_generic_and_logged(client, caplog, exc, code):
    with (
        patch("routers.calendar._get_supabase", return_value=_sb()),
        patch("routers.calendar.sync_user_calendar", new=AsyncMock(side_effect=exc)),
        caplog.at_level(logging.ERROR, logger="routers.calendar"),
    ):
        r = client.post("/calendar/sync")
    assert r.status_code == code
    assert "secret-google-body" not in r.text
    if code >= 500:
        assert "secret-google-body" in caplog.text


def _detection(db, **over):
    row = {
        "id": str(uuid4()),
        "user_id": over.pop("user_id"),
        "google_event_id": "evt1",
        "event_start": "2026-11-18T12:00:00+00:00",
        "status": "needs_confirmation",
        "classification": {
            "event_title": "Interview with Acme",
            "confidence": 0.6,
            "company": "Acme",
            "role": "Engineer",
            "interviewer_names": ["Jane Doe", "Bob"],
            "reasons": ["auto-run off or below confidence threshold"],
        },
    }
    row.update(over)
    db.tables.setdefault("calendar_detections", []).append(row)
    return row


def test_list_detections_only_own_needs_confirmation(client, user_id):
    db = FakeSupabase()
    mine = _detection(db, user_id=user_id)
    _detection(db, user_id="other-user")
    _detection(db, user_id=user_id, status="dismissed")
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.get("/calendar/detections")
    items = r.json()["detections"]
    assert [i["id"] for i in items] == [mine["id"]]
    assert items[0]["company"] == "Acme"
    assert items[0]["interviewer_names"] == ["Jane Doe", "Bob"]


def test_confirm_creates_one_briefing_and_starts_pipeline(
    client, user_id, _no_real_pipeline
):
    db = FakeSupabase()
    d = _detection(db, user_id=user_id)
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/confirm")
        r2 = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert r.status_code == 200 and r2.status_code == 200
    assert r.json()["briefing_id"] == r2.json()["briefing_id"]
    assert len(db.rows("briefings")) == 1
    b = db.rows("briefings")[0]
    assert b["user_id"] == user_id and b["status"] == "pending"
    assert b["company"] == "Acme" and b["interviewer"] == "Jane Doe"
    assert b["interview_date"] == "2026-11-18"
    assert db.rows("calendar_detections")[0]["status"] == "briefing_created"
    _no_real_pipeline.assert_called_once()
    assert _no_real_pipeline.call_args.kwargs["user_id"] == user_id


def test_confirm_with_edits(client, user_id):
    db = FakeSupabase()
    d = _detection(db, user_id=user_id)
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(
            f"/calendar/detections/{d['id']}/confirm",
            json={"company": "Globex", "interviewer": "Hank"},
        )
    assert r.status_code == 200
    b = db.rows("briefings")[0]
    assert b["company"] == "Globex" and b["interviewer"] == "Hank"


@pytest.mark.parametrize(
    "body",
    [
        {"user_id": "evil"},
        {"company": "Acme http://evil.example"},
        {"company": "<b>x</b>"},
    ],
)
def test_confirm_rejects_unknown_or_unsafe_fields(client, user_id, body):
    db = FakeSupabase()
    d = _detection(db, user_id=user_id)
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/confirm", json=body)
    assert r.status_code == 422
    assert db.rows("briefings") == []


def test_confirm_without_company_is_422_and_released(client, user_id):
    db = FakeSupabase()
    d = _detection(db, user_id=user_id)
    d["classification"]["company"] = None
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert r.status_code == 422
    assert db.rows("calendar_detections")[0]["status"] == "needs_confirmation"


def test_confirm_other_users_detection_is_404(client):
    db = FakeSupabase()
    d = _detection(db, user_id="other-user")
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert r.status_code == 404
    assert db.rows("briefings") == []


def test_confirm_malformed_id_is_404(client):
    assert client.post("/calendar/detections/not-a-uuid/confirm").status_code == 404
    assert client.post("/calendar/detections/not-a-uuid/dismiss").status_code == 404


def test_confirm_failure_is_generic_and_releases_detection(client, user_id, caplog):
    db = FakeSupabase()
    d = _detection(db, user_id=user_id)
    with (
        patch("routers.calendar._get_supabase", return_value=db),
        patch(
            "routers.calendar.create_pending_briefing",
            side_effect=RuntimeError("db-secret-123"),
        ),
        caplog.at_level(logging.ERROR, logger="routers.calendar"),
    ):
        r = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert r.status_code == 500
    # The failure is logged by class only (the message can echo the failing row).
    assert "db-secret-123" not in r.text and "db-secret-123" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert db.rows("calendar_detections")[0]["status"] == "needs_confirmation"


def test_dismiss(client, user_id):
    db = FakeSupabase()
    d = _detection(db, user_id=user_id)
    other = _detection(db, user_id="other-user")
    with patch("routers.calendar._get_supabase", return_value=db):
        r = client.post(f"/calendar/detections/{d['id']}/dismiss")
        r_other = client.post(f"/calendar/detections/{other['id']}/dismiss")
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert r_other.status_code == 404
    assert db.rows("briefings") == []
