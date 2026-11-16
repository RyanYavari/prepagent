"""Tests for the calendar connect flow in services.google_auth."""

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from services import google_auth
from services.google_auth import CALENDAR_SCOPE


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")
    google_auth._pending_calendar.clear()
    yield
    google_auth._pending_calendar.clear()


def _resp(status=200, payload=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    return r


def _http(post=None, exc=None):
    client = MagicMock()
    client.post = AsyncMock(return_value=post, side_effect=exc)
    return client


def _patch_http(client):
    p = patch("services.google_auth.httpx.AsyncClient")
    cls = p.start()
    cls.return_value.__aenter__.return_value = client
    return p


def test_authorization_url_requests_only_calendar_scope():
    url, state = google_auth.build_calendar_authorization_url("user-a")
    q = parse_qs(urlparse(url).query)
    assert q["scope"] == [CALENDAR_SCOPE]
    assert q["include_granted_scopes"] == ["false"]
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert "code_challenge" in q
    assert q["redirect_uri"] == ["http://localhost:3000/calendar/callback"]
    assert state in google_auth._pending_calendar


def test_signin_scopes_unchanged_and_exclude_calendar():
    assert CALENDAR_SCOPE not in google_auth.SCOPES
    assert google_auth.SCOPES == [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]


async def test_state_started_by_other_user_rejected_and_not_consumed():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    with pytest.raises(google_auth.InvalidOAuthStateError):
        await google_auth.exchange_calendar_code("code", state, "user-b")
    # The owner can still complete their own flow.
    assert state in google_auth._pending_calendar


async def test_unknown_state_rejected():
    with pytest.raises(google_auth.InvalidOAuthStateError):
        await google_auth.exchange_calendar_code("code", "nope", "user-a")


async def test_state_is_single_use():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    ok = _resp(
        payload={"refresh_token": "rt", "access_token": "at", "scope": CALENDAR_SCOPE}
    )
    p = _patch_http(_http(post=ok))
    try:
        await google_auth.exchange_calendar_code("code", state, "user-a")
        with pytest.raises(google_auth.InvalidOAuthStateError):
            await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()


async def test_exchange_sends_pkce_verifier_and_returns_refresh_token():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    verifier = google_auth._pending_calendar[state][0]
    client = _http(
        post=_resp(
            payload={
                "refresh_token": "rt",
                "access_token": "at",
                "scope": CALENDAR_SCOPE,
            }
        )
    )
    p = _patch_http(client)
    try:
        out = await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()
    assert out == {"refresh_token": "rt", "scope": CALENDAR_SCOPE}
    assert client.post.call_args.kwargs["data"]["code_verifier"] == verifier


async def test_extra_scope_rejected_and_token_revoked():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    bad = _resp(
        payload={
            "refresh_token": "rt",
            "access_token": "at",
            "scope": f"{CALENDAR_SCOPE} https://www.googleapis.com/auth/gmail.readonly",
        }
    )
    client = _http(post=bad)
    p = _patch_http(client)
    try:
        with pytest.raises(google_auth.CalendarConnectError):
            await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()
    urls = [c.args[0] for c in client.post.call_args_list]
    assert google_auth.GOOGLE_REVOKE_URL in urls


async def test_missing_refresh_token_rejected():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    p = _patch_http(
        _http(post=_resp(payload={"access_token": "at", "scope": CALENDAR_SCOPE}))
    )
    try:
        with pytest.raises(google_auth.CalendarConnectError):
            await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()


async def test_exchange_http_failure_is_connect_error():
    _, state = google_auth.build_calendar_authorization_url("user-a")
    p = _patch_http(_http(exc=httpx.ConnectError("boom")))
    try:
        with pytest.raises(google_auth.CalendarConnectError):
            await google_auth.exchange_calendar_code("code", state, "user-a")
    finally:
        p.stop()


async def test_revoke_token_reports_failure_without_raising():
    p = _patch_http(_http(exc=httpx.ConnectError("boom")))
    try:
        assert await google_auth.revoke_token("rt") is False
    finally:
        p.stop()


# --- refresh ---


async def test_refresh_returns_access_token():
    p = _patch_http(_http(post=_resp(payload={"access_token": "at"})))
    try:
        assert await google_auth.refresh_calendar_access_token("rt") == "at"
    finally:
        p.stop()


async def test_refresh_invalid_grant_is_auth_error():
    p = _patch_http(_http(post=_resp(400, {"error": "invalid_grant"})))
    try:
        with pytest.raises(google_auth.CalendarAuthError):
            await google_auth.refresh_calendar_access_token("rt")
    finally:
        p.stop()


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_refresh_transient_status_is_unavailable(status):
    p = _patch_http(_http(post=_resp(status, {})))
    try:
        with pytest.raises(google_auth.CalendarUnavailableError):
            await google_auth.refresh_calendar_access_token("rt")
    finally:
        p.stop()


async def test_refresh_network_error_is_unavailable():
    p = _patch_http(_http(exc=httpx.ConnectError("boom")))
    try:
        with pytest.raises(google_auth.CalendarUnavailableError):
            await google_auth.refresh_calendar_access_token("rt")
    finally:
        p.stop()
