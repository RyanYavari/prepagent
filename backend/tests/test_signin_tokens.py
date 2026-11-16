"""Sign-in must not persist or log Google tokens (specs/signin-token-removal.md)."""

import logging
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from main import app
from services import google_auth
from tests.calendar_helpers import FakeSupabase

AT = "ya29.SENTINEL-ACCESS-TOKEN"
RT = "1//SENTINEL-REFRESH-TOKEN"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    google_auth._pending_verifiers.clear()
    yield
    google_auth._pending_verifiers.clear()


def _callback(db, exchange=None):
    exchange = exchange or AsyncMock(return_value={"email": "a@b.com", "name": "A"})
    with (
        patch("routers.auth._get_supabase", return_value=db),
        patch("routers.auth.exchange_code_for_tokens", new=exchange),
    ):
        return TestClient(app).get("/auth/callback", params={"code": "c", "state": "s"})


def _no_token_values(db):
    blob = repr(db.tables)
    assert AT not in blob and RT not in blob


def test_new_user_insert_contains_only_email():
    db = FakeSupabase()
    resp = _callback(db)
    assert resp.status_code == 200
    assert db.rows("users")[0].keys() >= {"email"}
    assert not any("token" in k for k in db.rows("users")[0])


def test_existing_user_gets_no_token_update():
    db = FakeSupabase()
    db.tables["users"] = [{"id": "u1", "email": "a@b.com"}]
    resp = _callback(db)
    assert resp.status_code == 200
    assert not any("token" in k for k in db.rows("users")[0])
    assert resp.json()["token"]


def test_even_if_exchange_returned_tokens_they_are_not_stored():
    """Defence in depth: the router never copies token fields into the DB."""
    db = FakeSupabase()
    exchange = AsyncMock(
        return_value={
            "email": "a@b.com",
            "name": "A",
            "access_token": AT,
            "refresh_token": RT,
        }
    )
    assert _callback(db, exchange).status_code == 200
    _no_token_values(db)


def _real_exchange_patches(db, userinfo_ok=True):
    fake_credentials = MagicMock(token=AT, refresh_token=RT)
    userinfo = MagicMock()
    userinfo.json.return_value = {"email": "a@b.com", "name": "A"}
    http = MagicMock()
    http.get = AsyncMock(return_value=userinfo)
    return fake_credentials, http


@pytest.mark.parametrize("failure", [None, "db", "exchange"])
def test_tokens_never_in_response_or_logs(caplog, failure):
    caplog.set_level(logging.DEBUG)
    _, state = google_auth.build_authorization_url()
    db = FakeSupabase()
    creds, http = _real_exchange_patches(db)

    def fetch_token(self, **kwargs):
        if failure == "exchange":
            raise RuntimeError("boom")

    patches = [
        patch.object(google_auth.Flow, "fetch_token", fetch_token),
        patch.object(
            google_auth.Flow,
            "credentials",
            new_callable=PropertyMock,
            return_value=creds,
        ),
        patch("services.google_auth.httpx.AsyncClient"),
    ]
    if failure == "db":
        broken = MagicMock()
        broken.table.side_effect = RuntimeError("db down")
        patches.append(patch("routers.auth._get_supabase", return_value=broken))
    else:
        patches.append(patch("routers.auth._get_supabase", return_value=db))

    with (
        patches[0],
        patches[1],
        patches[2] as client_cls,
        patches[3],
    ):
        client_cls.return_value.__aenter__.return_value = http
        resp = TestClient(app).get(
            "/auth/callback", params={"code": "c", "state": state}
        )

    assert resp.status_code == (
        200 if failure is None else {"db": 500}.get(failure, 400)
    )
    assert AT not in resp.text and RT not in resp.text
    assert AT not in caplog.text and RT not in caplog.text
    _no_token_values(db)


def test_authorization_url_requests_no_refresh_token():
    url, _ = google_auth.build_authorization_url()
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["online"]
    assert "prompt" not in q
    assert q["include_granted_scopes"] == ["false"]
    assert set(q["scope"][0].split()) == set(google_auth.SCOPES)


async def test_exchange_returns_only_identity():
    _, state = google_auth.build_authorization_url()
    creds, http = _real_exchange_patches(FakeSupabase())
    with (
        patch.object(google_auth.Flow, "fetch_token", lambda self, **k: None),
        patch.object(
            google_auth.Flow,
            "credentials",
            new_callable=PropertyMock,
            return_value=creds,
        ),
        patch("services.google_auth.httpx.AsyncClient") as client_cls,
    ):
        client_cls.return_value.__aenter__.return_value = http
        result = await google_auth.exchange_code_for_tokens("code", state)
    assert set(result) == {"email", "name"}


def test_unused_signin_refresh_helper_removed():
    assert not hasattr(google_auth, "refresh_access_token")
