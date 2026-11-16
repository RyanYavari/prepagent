"""Explicit timeouts and bounded retries on the Google OAuth and Calendar calls."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import httpx
import pytest

from services import calendar as cal
from services import google_auth, net_config

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    google_auth._pending_calendar.clear()
    yield
    google_auth._pending_calendar.clear()


@pytest.fixture
def backoff():
    """The sleep mock used by retries (conftest already stubs the real one)."""
    sleep = AsyncMock()
    with patch("services.net_config.asyncio", SimpleNamespace(sleep=sleep)):
        yield sleep


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload if payload is not None else {}
    return r


def _patched_client(module, **methods):
    """Patch httpx.AsyncClient in `module`; return (patcher, ctor mock, client)."""
    client = MagicMock()
    for name, effect in methods.items():
        mock = AsyncMock()
        if isinstance(effect, (list, BaseException)):
            mock.side_effect = effect
        else:
            mock.return_value = effect
        setattr(client, name, mock)
    p = patch(f"{module}.httpx.AsyncClient")
    ctor = p.start()
    ctor.return_value.__aenter__.return_value = client
    return p, ctor, client


# --- aretry_call ---


async def test_aretry_then_success(backoff):
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("dns")
        return "ok"

    out = await net_config.aretry_call(
        flaky, retries=2, retry_on=(ConnectionError,), label="t"
    )
    assert out == "ok" and len(calls) == 3 and backoff.await_count == 2


async def test_aretry_is_bounded_and_skips_other_errors():
    fn = AsyncMock(side_effect=ConnectionError("dns"))
    with pytest.raises(ConnectionError):
        await net_config.aretry_call(
            fn, retries=2, retry_on=(ConnectionError,), label="t"
        )
    assert fn.await_count == 3

    fn = AsyncMock(side_effect=ValueError("bad"))
    with pytest.raises(ValueError):
        await net_config.aretry_call(
            fn, retries=3, retry_on=(ConnectionError,), label="t"
        )
    assert fn.await_count == 1


async def test_aretry_log_has_class_not_message(caplog):
    fn = AsyncMock(side_effect=[ConnectionError("https://x.example/?code=SECRET"), 1])
    with caplog.at_level("WARNING"):
        await net_config.aretry_call(
            fn, retries=1, retry_on=(ConnectionError,), label="t"
        )
    assert "ConnectionError" in caplog.text and "SECRET" not in caplog.text


def test_google_limits_have_defaults_and_ignore_bad_env(monkeypatch):
    assert net_config.env_float("GOOGLE_TIMEOUT_SECONDS") == 10.0
    assert net_config.env_int("GOOGLE_MAX_RETRIES") == 1
    monkeypatch.setenv("GOOGLE_TIMEOUT_SECONDS", "junk")
    monkeypatch.setenv("GOOGLE_MAX_RETRIES", "-1")
    assert net_config.env_float("GOOGLE_TIMEOUT_SECONDS") == 10.0
    assert net_config.env_int("GOOGLE_MAX_RETRIES") == 1


# --- explicit timeouts ---


async def test_token_refresh_uses_configured_timeout(monkeypatch):
    monkeypatch.setenv("GOOGLE_TIMEOUT_SECONDS", "7")
    p, ctor, _ = _patched_client(
        "services.google_auth", post=_resp(200, {"access_token": "at"})
    )
    try:
        assert await google_auth.refresh_calendar_access_token("rt") == "at"
    finally:
        p.stop()
    assert ctor.call_args.kwargs["timeout"] == 7.0


async def test_signin_userinfo_and_token_exchange_are_bounded():
    _, state = google_auth.build_authorization_url()
    seen = {}

    def fake_fetch_token(self, **kwargs):
        seen.update(kwargs)

    userinfo = _resp(200, {"email": "a@b.com", "name": "A"})
    p, ctor, _ = _patched_client("services.google_auth", get=userinfo)
    try:
        with (
            patch.object(google_auth.Flow, "fetch_token", fake_fetch_token),
            patch.object(
                google_auth.Flow,
                "credentials",
                new_callable=PropertyMock,
                return_value=MagicMock(token="at"),
            ),
        ):
            await google_auth.exchange_code_for_tokens("code", state)
    finally:
        p.stop()
    assert seen["timeout"] == 10.0  # the requests-based code exchange
    assert ctor.call_args.kwargs["timeout"] == 10.0  # the httpx userinfo call


async def test_calendar_events_uses_configured_timeout(monkeypatch):
    monkeypatch.setenv("GOOGLE_TIMEOUT_SECONDS", "6")
    p, ctor, _ = _patched_client("services.calendar", get=_resp(200, {"items": []}))
    try:
        await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
    assert ctor.call_args.kwargs["timeout"] == 6.0


# --- retries ---


async def test_token_refresh_retries_read_timeout_then_succeeds(backoff):
    p, _, client = _patched_client(
        "services.google_auth",
        post=[httpx.ReadTimeout("slow"), _resp(200, {"access_token": "at"})],
    )
    try:
        assert await google_auth.refresh_calendar_access_token("rt") == "at"
    finally:
        p.stop()
    assert client.post.await_count == 2
    backoff.assert_awaited_once()


async def test_token_refresh_retries_are_bounded_then_unavailable(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAX_RETRIES", "2")
    p, _, client = _patched_client(
        "services.google_auth", post=httpx.ConnectError("dns")
    )
    try:
        with pytest.raises(google_auth.CalendarUnavailableError):
            await google_auth.refresh_calendar_access_token("rt")
    finally:
        p.stop()
    assert client.post.await_count == 3  # 1 try + 2 retries


async def test_invalid_grant_is_not_retried():
    p, _, client = _patched_client(
        "services.google_auth", post=_resp(400, {"error": "invalid_grant"})
    )
    try:
        with pytest.raises(google_auth.CalendarAuthError):
            await google_auth.refresh_calendar_access_token("rt")
    finally:
        p.stop()
    assert client.post.await_count == 1


async def test_revoke_retries_then_reports_result():
    p, _, client = _patched_client(
        "services.google_auth", post=[httpx.ConnectError("dns"), _resp(200)]
    )
    try:
        assert await google_auth.revoke_token("tok") is True
    finally:
        p.stop()
    assert client.post.await_count == 2


async def test_revoke_still_best_effort_when_retries_exhausted():
    p, _, _ = _patched_client("services.google_auth", post=httpx.ConnectError("dns"))
    try:
        assert await google_auth.revoke_token("tok") is False
    finally:
        p.stop()


async def test_code_exchange_retries_connect_errors():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    ok = _resp(
        200,
        {"refresh_token": "rt", "scope": google_auth.CALENDAR_SCOPE},
    )
    p, _, client = _patched_client(
        "services.google_auth", post=[httpx.ConnectError("dns"), ok]
    )
    try:
        out = await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()
    assert out["refresh_token"] == "rt"
    assert client.post.await_count == 2


async def test_code_exchange_never_retries_after_read_timeout():
    """The authorization code is single-use: a read timeout may mean Google already
    consumed it, so repeating the request is not safe."""
    _, state = google_auth.build_calendar_authorization_url("user-a")
    p, _, client = _patched_client(
        "services.google_auth", post=httpx.ReadTimeout("slow")
    )
    try:
        with pytest.raises(google_auth.CalendarConnectError):
            await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()
    assert client.post.await_count == 1


async def test_calendar_events_retries_read_timeout_then_succeeds():
    p, _, client = _patched_client(
        "services.calendar",
        get=[httpx.ReadTimeout("slow"), _resp(200, {"items": [{"id": "a"}]})],
    )
    try:
        items, _ = await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
    assert items == [{"id": "a"}] and client.get.await_count == 2


async def test_calendar_events_retry_bounded_then_api_error(caplog):
    p, _, client = _patched_client("services.calendar", get=httpx.ConnectError("dns"))
    try:
        with caplog.at_level("WARNING"), pytest.raises(cal.CalendarApiError):
            await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
    assert client.get.await_count == 2  # default: 1 try + 1 retry
    assert "dns" not in caplog.text  # class name only, never the message


async def test_calendar_http_error_status_is_not_retried():
    p, _, client = _patched_client(
        "services.calendar", get=_resp(403, text="forbidden")
    )
    try:
        with pytest.raises(cal.CalendarApiError):
            await cal.fetch_events("tok", NOW, 14)
    finally:
        p.stop()
    assert client.get.await_count == 1
