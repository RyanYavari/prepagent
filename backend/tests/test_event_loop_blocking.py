"""Blocking handlers must not stall the single worker's event loop (Slice 2)."""

import asyncio
import inspect
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from dependencies.auth import CurrentUser, get_current_user
from main import app
from routers import calendar as calendar_router
from routers import research as research_router

SLOW_SECONDS = 0.6


@pytest.fixture
def authed():
    async def _user():
        return CurrentUser(user_id=str(uuid4()), email="t@example.com")

    app.dependency_overrides[get_current_user] = _user
    yield
    app.dependency_overrides.clear()


async def test_slow_embedding_does_not_delay_health(authed):
    def slow_embed(*_a, **_k):
        time.sleep(SLOW_SECONDS)  # a blocking OpenAI call

    briefing = {
        "id": str(uuid4()),
        "user_id": "u",
        "company": "Acme",
        "interviewer": None,
        "role": None,
        "interview_date": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    with (
        patch("routers.research._get_supabase", return_value=MagicMock()),
        patch("routers.research.process_resume_embedding", side_effect=slow_embed),
        patch("routers.research.create_pending_briefing", return_value=briefing),
        patch("routers.research.run_pipeline"),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            start = time.monotonic()

            async def create():
                resp = await client.post(
                    "/briefings", json={"company": "Acme", "resume_text": "x"}
                )
                return resp.status_code, time.monotonic() - start

            async def health():
                await asyncio.sleep(0.1)  # let the slow request start first
                resp = await client.get("/health")
                return resp.status_code, time.monotonic() - start

            (
                (create_status, create_done),
                (health_status, health_done),
            ) = await asyncio.gather(create(), health())

    assert create_status == 201
    assert health_status == 200
    assert health_done < SLOW_SECONDS, "health was blocked by the slow embedding call"
    assert create_done >= SLOW_SECONDS


@pytest.mark.parametrize(
    "func",
    [
        research_router.create_briefing,
        research_router.list_briefings,
        research_router.get_briefing,
        calendar_router.calendar_status,
        calendar_router.list_detections,
        calendar_router.confirm_detection,
        calendar_router.dismiss_detection,
    ],
)
def test_blocking_handlers_are_sync(func):
    assert not inspect.iscoroutinefunction(func)


@pytest.mark.parametrize(
    "func",
    [
        calendar_router.calendar_callback,
        calendar_router.disconnect_calendar,
        calendar_router.sync_calendar,
    ],
)
def test_handlers_that_await_google_stay_async(func):
    assert inspect.iscoroutinefunction(func)


async def test_slow_user_lookup_in_signin_does_not_delay_health():
    from unittest.mock import AsyncMock

    def slow_db():
        time.sleep(SLOW_SECONDS)
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "u-1", "email": "a@b.com"}
        ]
        return sb

    with (
        patch("routers.auth._get_supabase", side_effect=slow_db),
        patch(
            "routers.auth.exchange_code_for_tokens",
            new=AsyncMock(return_value={"email": "a@b.com", "name": "A"}),
        ),
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            start = time.monotonic()

            async def signin():
                r = await client.get(
                    "/auth/callback", params={"code": "c", "state": "s"}
                )
                return r.status_code

            async def health():
                await asyncio.sleep(0.1)
                r = await client.get("/health")
                return r.status_code, time.monotonic() - start

            status, (health_status, health_done) = await asyncio.gather(
                signin(), health()
            )
    assert status == 200 and health_status == 200
    assert health_done < SLOW_SECONDS
