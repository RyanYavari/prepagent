"""Tests for the optional calendar polling loop."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services import calendar_poller as poller


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CALENDAR_POLL_INTERVAL_MINUTES", raising=False)
    assert poller.poll_interval_minutes() == 0
    monkeypatch.setenv("CALENDAR_POLL_INTERVAL_MINUTES", "junk")
    assert poller.poll_interval_minutes() == 0
    monkeypatch.setenv("CALENDAR_POLL_INTERVAL_MINUTES", "15")
    assert poller.poll_interval_minutes() == 15


def test_app_does_not_start_poller_when_disabled(monkeypatch):
    monkeypatch.delenv("CALENDAR_POLL_INTERVAL_MINUTES", raising=False)
    from main import app

    with patch("services.calendar_poller.run_poller") as run, TestClient(app):
        pass
    run.assert_not_called()


async def test_one_users_failure_does_not_stop_others():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"user_id": "u1"},
        {"user_id": "u2"},
        {"user_id": "u3"},
    ]
    calls = []

    async def fake_sync(supabase, user_id, start):
        calls.append(user_id)
        if user_id == "u2":
            raise RuntimeError("boom")

    with patch("services.calendar_poller.sync_user_calendar", fake_sync):
        await poller.poll_once(sb)
    assert calls == ["u1", "u2", "u3"]


async def test_run_poller_survives_a_failed_cycle():
    attempts = {"n": 0}

    def get_sb():
        attempts["n"] += 1
        raise RuntimeError("db down")

    task = asyncio.create_task(poller.run_poller(get_sb, 0.0001))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert attempts["n"] >= 2


async def test_start_pipeline_runs_off_loop():
    with patch("agents.pipeline.run_pipeline", MagicMock()) as rp:
        poller._start_pipeline(briefing_id="b", user_id="u", company="Acme")
        await asyncio.gather(*list(poller._background))
    rp.assert_called_once_with(briefing_id="b", user_id="u", company="Acme")
