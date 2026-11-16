"""Per-user, active and global briefing caps (specs/deployment.md, Slice 4)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from dependencies.auth import CurrentUser, get_current_user
from main import _startup_sweep as real_startup_sweep  # conftest patches the attribute
from main import app
from models.briefing import BriefingCreate
from services import limits
from services.briefings import create_pending_briefing
from tests.calendar_helpers import FakeSupabase

NOW = datetime.now(UTC)


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for name in (
        "MAX_BRIEFINGS_PER_USER_PER_DAY",
        "MAX_BRIEFINGS_GLOBAL_PER_DAY",
        "MAX_ACTIVE_BRIEFINGS_PER_USER",
        "STALE_RUNNING_MINUTES",
        "BRIEFINGS_ENABLED",
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


def seed(db, user, created_at, status="complete"):
    db.tables.setdefault("briefings", []).append(
        {
            "id": str(uuid4()),
            "user_id": user,
            "company": "Old",
            "interviewer": None,
            "role": None,
            "status": status,
            "created_at": created_at,
        }
    )


def post(client, db, body=None):
    with (
        patch("routers.research._get_supabase", return_value=db),
        patch("routers.research.process_resume_embedding") as embed,
    ):
        resp = client.post(
            "/briefings", json=body or {"company": "Acme", "resume_text": "r"}
        )
    return resp, embed


def assert_blocked(resp, embed, db, pipeline, before):
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    embed.assert_not_called()
    pipeline.assert_not_called()
    assert len(db.rows("briefings")) == before
    assert db.rows("users") == []  # resume not saved either


# --- per-user daily cap -------------------------------------------------------


def test_defaults():
    assert limits.max_briefings_per_user_per_day() == 3
    assert limits.max_briefings_global_per_day() == 20
    assert limits.max_active_briefings_per_user() == 2


def test_under_the_cap_is_allowed(client, user_id, _no_real_pipeline):
    db = FakeSupabase()
    for h in (1, 2):
        seed(db, user_id, ago(hours=h))
    resp, embed = post(client, db)
    assert resp.status_code == 201
    embed.assert_called_once()
    assert len(db.rows("briefings")) == 3


def test_per_user_daily_cap_blocks_before_embedding(client, user_id, _no_real_pipeline):
    db = FakeSupabase()
    for h in (1, 2, 3):
        seed(db, user_id, ago(hours=h))
    resp, embed = post(client, db)
    assert_blocked(resp, embed, db, _no_real_pipeline, before=3)
    assert resp.json() == {"detail": "Daily briefing limit reached"}


def test_retry_after_matches_when_the_oldest_expires(client, user_id):
    db = FakeSupabase()
    seed(db, user_id, ago(hours=23))  # frees up in about one hour
    seed(db, user_id, ago(hours=2))
    seed(db, user_id, ago(hours=1))
    resp, _ = post(client, db)
    assert 3000 <= int(resp.headers["Retry-After"]) <= 3700


def test_rows_older_than_a_day_do_not_count(client, user_id):
    db = FakeSupabase()
    for h in (25, 30, 48):
        seed(db, user_id, ago(hours=h))
    resp, _ = post(client, db)
    assert resp.status_code == 201


def test_failed_briefings_still_count(client, user_id, _no_real_pipeline):
    db = FakeSupabase()
    for h in (1, 2, 3):
        seed(db, user_id, ago(hours=h), status="failed")
    resp, embed = post(client, db)
    assert_blocked(resp, embed, db, _no_real_pipeline, before=3)


def test_other_users_rows_do_not_count_against_me(client, user_id):
    db = FakeSupabase()
    for h in (1, 2, 3, 4):
        seed(db, "someone-else", ago(hours=h))
    resp, _ = post(client, db)
    assert resp.status_code == 201


# --- active cap ---------------------------------------------------------------


def test_active_cap_blocks_and_releases(client, user_id, _no_real_pipeline):
    db = FakeSupabase()
    seed(db, user_id, ago(minutes=1), status="running")
    seed(db, user_id, ago(minutes=2), status="pending")
    resp, embed = post(client, db)
    assert_blocked(resp, embed, db, _no_real_pipeline, before=2)
    assert resp.json() == {"detail": "You already have briefings in progress"}

    db.rows("briefings")[0]["status"] = "complete"
    resp, _ = post(client, db)
    assert resp.status_code == 201


def test_orphaned_old_active_rows_never_lock_a_user_out(client, user_id):
    db = FakeSupabase()
    seed(db, user_id, ago(hours=3), status="pending")  # orphaned by a restart
    seed(db, user_id, ago(hours=3), status="running")
    resp, _ = post(client, db)
    assert resp.status_code == 201


# --- global cap ----------------------------------------------------------------


def test_global_cap_blocks_everyone_with_a_generic_message(
    client, user_id, _no_real_pipeline
):
    db = FakeSupabase()
    for i in range(20):
        seed(db, f"user-{i}", ago(hours=1))
    resp, embed = post(client, db)
    assert_blocked(resp, embed, db, _no_real_pipeline, before=20)
    assert resp.json() == {"detail": "The service is at capacity for today"}
    assert "20" not in resp.text


def test_global_count_ignores_rows_older_than_a_day(client):
    db = FakeSupabase()
    for i in range(30):
        seed(db, f"user-{i}", ago(hours=30))
    resp, _ = post(client, db)
    assert resp.status_code == 201


# --- configuration ---------------------------------------------------------------


def test_env_overrides(monkeypatch, client, user_id):
    monkeypatch.setenv("MAX_BRIEFINGS_PER_USER_PER_DAY", "1")
    db = FakeSupabase()
    seed(db, user_id, ago(hours=1))
    assert post(client, db)[0].status_code == 429
    monkeypatch.setenv("MAX_BRIEFINGS_PER_USER_PER_DAY", "10")
    assert post(client, db)[0].status_code == 201


@pytest.mark.parametrize("raw", ["", "abc", "-5", "1.5", "99999999"])
def test_bad_values_fall_back_to_defaults(monkeypatch, raw):
    monkeypatch.setenv("MAX_BRIEFINGS_PER_USER_PER_DAY", raw)
    monkeypatch.setenv("MAX_BRIEFINGS_GLOBAL_PER_DAY", raw)
    monkeypatch.setenv("MAX_ACTIVE_BRIEFINGS_PER_USER", raw)
    assert limits.max_briefings_per_user_per_day() == 3
    assert limits.max_briefings_global_per_day() == 20
    assert limits.max_active_briefings_per_user() == 2


def test_zero_is_a_valid_cap_that_blocks_everything(monkeypatch, client):
    monkeypatch.setenv("MAX_BRIEFINGS_PER_USER_PER_DAY", "0")
    assert post(client, FakeSupabase())[0].status_code == 429


def test_check_failure_fails_closed(client, _no_real_pipeline):
    broken = MagicMock()
    broken.table.side_effect = RuntimeError("db down secret-detail")
    with (
        patch("routers.research._get_supabase", return_value=broken),
        patch("routers.research.process_resume_embedding") as embed,
    ):
        resp = client.post("/briefings", json={"company": "Acme", "resume_text": "r"})
    assert resp.status_code == 500
    assert "secret-detail" not in resp.text
    embed.assert_not_called()
    _no_real_pipeline.assert_not_called()


def test_each_check_runs_once_for_a_manual_briefing(client):
    db = FakeSupabase()
    with patch(
        "routers.research.check_briefing_allowed", wraps=limits.check_briefing_allowed
    ) as spy:
        post(client, db)
    assert spy.call_count == 1


# --- shared creation helper (calendar path) ---------------------------------------


def test_create_pending_briefing_enforces_caps_for_every_caller(user_id):
    db = FakeSupabase()
    for h in (1, 2, 3):
        seed(db, user_id, ago(hours=h))
    start = MagicMock()
    with pytest.raises(limits.BriefingLimitError):
        create_pending_briefing(db, user_id, BriefingCreate(company="Acme"), start)
    start.assert_not_called()
    assert len(db.rows("briefings")) == 3


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


def test_capped_calendar_confirm_leaves_detection_unconfirmed(
    client, user_id, _no_real_pipeline
):
    db = FakeSupabase()
    for h in (1, 2, 3):
        seed(db, user_id, ago(hours=h))
    d = _detection(db, user_id)
    with patch("routers.calendar._get_supabase", return_value=db):
        resp = client.post(f"/calendar/detections/{d['id']}/confirm")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    assert db.rows("calendar_detections")[0]["status"] == "needs_confirmation"
    assert len(db.rows("briefings")) == 3
    _no_real_pipeline.assert_not_called()


# --- stale pending sweep (Q10) -----------------------------------------------------


def test_sweep_stale_pending_fails_only_old_pending_rows(user_id):
    from services.briefings import sweep_stale_pending

    db = FakeSupabase()
    seed(db, user_id, ago(hours=2), status="pending")
    seed(db, user_id, ago(minutes=1), status="pending")
    seed(db, user_id, ago(hours=2), status="running")
    seed(db, user_id, ago(hours=2), status="complete")
    assert sweep_stale_pending(db) == 1
    statuses = [r["status"] for r in db.rows("briefings")]
    assert statuses == ["failed", "pending", "running", "complete"]


def test_startup_sweep_covers_pending_and_running():
    with (
        patch("services.briefings.sweep_stale_running") as running,
        patch("services.briefings.sweep_stale_pending") as pending,
        patch("services.supabase_client.get_service_client", return_value=object()),
    ):
        real_startup_sweep()
    running.assert_called_once()
    pending.assert_called_once()


# --- concurrency: check and insert must be atomic (reviewer finding) ---------------


def test_parallel_creates_cannot_overshoot_the_cap(monkeypatch, client, user_id):
    import time
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("MAX_ACTIVE_BRIEFINGS_PER_USER", "100")
    db = FakeSupabase()

    def slow_embed(*_a, **_k):
        time.sleep(0.05)  # a real embedding call takes seconds

    def one(_):
        return TestClient(app).post(
            "/briefings", json={"company": "Acme", "resume_text": "r"}
        )

    with (
        patch("routers.research._get_supabase", return_value=db),
        patch("routers.research.process_resume_embedding", side_effect=slow_embed),
        ThreadPoolExecutor(max_workers=12) as pool,
    ):
        codes = sorted(r.status_code for r in pool.map(one, range(12)))
    assert codes.count(201) == 3 and codes.count(429) == 9
    assert len(db.rows("briefings")) == 3


def test_parallel_confirms_share_the_same_lock(monkeypatch, user_id):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("MAX_ACTIVE_BRIEFINGS_PER_USER", "100")
    db = FakeSupabase()
    start = MagicMock()

    def one(i):
        try:
            create_pending_briefing(db, user_id, BriefingCreate(company="A"), start)
            return "ok"
        except limits.BriefingLimitError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(one, range(10)))
    assert results.count("ok") == 3
    assert len(db.rows("briefings")) == 3
