"""Per-IP limits on unauthenticated endpoints and PKCE store caps (Slice 5)."""

import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services import google_auth, rate_limit


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    c = Clock()
    with patch("services.rate_limit.time") as t:  # the module's own reference only
        t.monotonic = c
        yield c


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("RATE_LIMIT_AUTH_PER_MINUTE", "RATE_LIMIT_GLOBAL_PER_MINUTE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    google_auth._pending_verifiers.clear()
    google_auth._pending_calendar.clear()
    yield
    google_auth._pending_verifiers.clear()
    google_auth._pending_calendar.clear()


# --- the limiter itself ---------------------------------------------------------


def test_window_allows_up_to_limit_then_blocks_with_retry_after(clock):
    lim = rate_limit.SlidingWindowLimiter(limit=3, window=60)
    assert [lim.check("ip")[0] for _ in range(3)] == [True, True, True]
    ok, retry = lim.check("ip")
    assert not ok and 1 <= retry <= 60
    clock.now += 61
    assert lim.check("ip")[0]


def test_retry_after_is_when_the_oldest_hit_expires(clock):
    lim = rate_limit.SlidingWindowLimiter(limit=2, window=60)
    lim.check("ip")
    clock.now += 10
    lim.check("ip")
    ok, retry = lim.check("ip")
    assert not ok and retry == 50


def test_keys_are_independent(clock):
    lim = rate_limit.SlidingWindowLimiter(limit=1, window=60)
    assert lim.check("a")[0] and lim.check("b")[0]
    assert not lim.check("a")[0]


def test_tracked_keys_are_bounded(clock):
    lim = rate_limit.SlidingWindowLimiter(limit=5, window=60, max_keys=100)
    for i in range(1000):
        lim.check(f"ip-{i}")
    assert lim.tracked_keys() <= 100


def test_thread_safe_under_concurrency(clock):
    lim = rate_limit.SlidingWindowLimiter(limit=50, window=60)
    allowed = []

    def hit():
        for _ in range(20):
            allowed.append(lim.check("ip")[0])

    threads = [threading.Thread(target=hit) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(allowed) == 50


# --- middleware -------------------------------------------------------------------


def test_auth_endpoints_are_limited_per_ip(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "3")
    client = TestClient(app)
    codes = [client.get("/auth/google").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    blocked = client.get("/auth/google")
    assert blocked.json() == {"detail": "Too many requests"}
    assert int(blocked.headers["Retry-After"]) >= 1


def test_overall_limit_applies_to_other_endpoints(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_PER_MINUTE", "4")
    client = TestClient(app)
    codes = [client.get("/briefings").status_code for _ in range(6)]
    assert 429 in codes and codes[:4].count(429) == 0


def test_health_is_never_limited(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_PER_MINUTE", "1")
    client = TestClient(app)
    assert all(client.get("/health").status_code == 200 for _ in range(10))


def test_spoofed_forwarded_for_header_does_not_change_the_bucket(monkeypatch):
    """The app trusts only the peer address uvicorn resolves (--proxy-headers)."""
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "2")
    client = TestClient(app)
    codes = [
        client.get(
            "/auth/google", headers={"X-Forwarded-For": f"9.9.9.{i}"}
        ).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 429, 429]


def test_different_peers_have_separate_buckets(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "1")
    a = TestClient(app, client=("1.1.1.1", 1000))
    b = TestClient(app, client=("2.2.2.2", 1000))
    assert a.get("/auth/google").status_code == 200
    assert a.get("/auth/google").status_code == 429
    assert b.get("/auth/google").status_code == 200


def test_blocked_response_still_carries_cors_headers(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "1")
    client = TestClient(app)
    origin = "http://localhost:3000"
    client.get("/auth/google", headers={"Origin": origin})
    resp = client.get("/auth/google", headers={"Origin": origin})
    assert resp.status_code == 429
    assert resp.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("raw", ["", "abc", "-1", "0", "999999"])
def test_bad_limit_values_fall_back_to_defaults(monkeypatch, raw):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", raw)
    monkeypatch.setenv("RATE_LIMIT_GLOBAL_PER_MINUTE", raw)
    assert rate_limit.auth_limit_per_minute() == 20
    assert rate_limit.global_limit_per_minute() == 120


# --- PKCE store caps ----------------------------------------------------------------


def test_signin_verifier_store_is_capped_oldest_evicted(monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_PENDING_STATES", 5)
    for i in range(12):
        google_auth._store_code_verifier(f"s{i}", f"v{i}")
    assert len(google_auth._pending_verifiers) == 5
    assert set(google_auth._pending_verifiers) == {f"s{i}" for i in range(7, 12)}
    assert google_auth.pop_code_verifier("s11") == "v11"
    with pytest.raises(google_auth.InvalidOAuthStateError):
        google_auth.pop_code_verifier("s0")


def test_calendar_store_is_capped_and_keeps_newest(monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_PENDING_STATES", 4)
    states = [google_auth.build_calendar_authorization_url("u")[1] for _ in range(9)]
    assert len(google_auth._pending_calendar) == 4
    assert set(google_auth._pending_calendar) == set(states[-4:])


def test_store_cap_holds_under_concurrency(monkeypatch):
    monkeypatch.setattr(google_auth, "MAX_PENDING_STATES", 50)
    errors = []

    def flood(n):
        try:
            for i in range(100):
                google_auth._store_code_verifier(f"{n}-{i}", "v")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=flood, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(google_auth._pending_verifiers) <= 50


def test_default_cap_is_generous_for_real_users():
    assert google_auth.MAX_PENDING_STATES >= 1000


def test_ipv6_clients_share_a_bucket_per_64():
    a = rate_limit.bucket_key("2001:db8:1:2::1")
    b = rate_limit.bucket_key("2001:db8:1:2:ffff:ffff:ffff:ffff")
    c = rate_limit.bucket_key("2001:db8:1:3::1")
    assert a == b and a != c
    assert rate_limit.bucket_key("203.0.113.9") == "203.0.113.9"
    assert rate_limit.bucket_key("::ffff:203.0.113.9") == "203.0.113.9"
    assert rate_limit.bucket_key(None) == "unknown"
    assert rate_limit.bucket_key("not-an-ip") == "not-an-ip"


def test_one_ipv6_64_cannot_dodge_the_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "2")
    codes = [
        TestClient(app, client=(f"2001:db8:1:2::{i:x}", 1000))
        .get("/auth/google")
        .status_code
        for i in range(1, 5)
    ]
    assert codes == [200, 200, 429, 429]
