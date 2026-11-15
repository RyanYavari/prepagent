"""Tests for the Google OAuth PKCE round trip (auth URL -> callback)."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from main import app
from services import google_auth


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    google_auth._pending_verifiers.clear()
    yield
    google_auth._pending_verifiers.clear()


def _challenge_for(verifier: str) -> str:
    import hashlib
    from base64 import urlsafe_b64encode

    digest = hashlib.sha256(verifier.encode()).digest()
    return urlsafe_b64encode(digest).decode().rstrip("=")


async def test_callback_flow_reuses_verifier_from_auth_url():
    """Regression: token exchange must send the verifier matching the challenge."""
    url, state = google_auth.build_authorization_url()
    challenge = parse_qs(urlparse(url).query)["code_challenge"][0]

    captured = {}

    def fake_fetch_token(self, **kwargs):
        captured["code_verifier"] = self.code_verifier

    fake_credentials = MagicMock(token="at", refresh_token="rt")
    userinfo = MagicMock()
    userinfo.json.return_value = {"email": "a@b.com", "name": "A"}
    http = MagicMock()
    http.get = AsyncMock(return_value=userinfo)

    with (
        patch.object(google_auth.Flow, "fetch_token", fake_fetch_token),
        patch.object(
            google_auth.Flow,
            "credentials",
            new_callable=PropertyMock,
            return_value=fake_credentials,
        ),
        patch("services.google_auth.httpx.AsyncClient") as client_cls,
    ):
        client_cls.return_value.__aenter__.return_value = http
        result = await google_auth.exchange_code_for_tokens("code", state)

    assert captured["code_verifier"]
    assert _challenge_for(captured["code_verifier"]) == challenge
    assert result["email"] == "a@b.com"


def test_verifier_not_in_authorization_url():
    url, state = google_auth.build_authorization_url()
    verifier = google_auth._pending_verifiers[state][0]
    assert verifier not in url


async def test_unknown_state_rejected():
    with pytest.raises(google_auth.InvalidOAuthStateError):
        await google_auth.exchange_code_for_tokens("code", "never-issued")


async def test_state_is_single_use():
    _, state = google_auth.build_authorization_url()
    assert google_auth.pop_code_verifier(state)
    with pytest.raises(google_auth.InvalidOAuthStateError):
        google_auth.pop_code_verifier(state)


async def test_expired_state_rejected():
    _, state = google_auth.build_authorization_url()
    verifier, _expires = google_auth._pending_verifiers[state]
    google_auth._pending_verifiers[state] = (verifier, 0.0)
    with pytest.raises(google_auth.InvalidOAuthStateError):
        google_auth.pop_code_verifier(state)


def test_callback_endpoint_rejects_unknown_state():
    client = TestClient(app)
    resp = client.get("/auth/callback", params={"code": "c", "state": "bogus"})
    assert resp.status_code == 400
    assert "state" in resp.json()["detail"].lower()


def test_callback_endpoint_requires_state():
    client = TestClient(app)
    resp = client.get("/auth/callback", params={"code": "c"})
    assert resp.status_code == 422
