"""One-off revoke-then-scrub script (specs/signin-token-removal.md)."""

import logging
from unittest.mock import AsyncMock

from scripts.revoke_stored_tokens import BATCH_SIZE, run
from tests.calendar_helpers import FakeSupabase

RT1, RT2, AT1 = "1//SENTINEL-RT-1", "1//SENTINEL-RT-2", "ya29.SENTINEL-AT-1"


def _db(*rows):
    db = FakeSupabase()
    db.tables["users"] = [dict(r) for r in rows]
    return db


def _tokens_left(db):
    return [
        r
        for r in db.rows("users")
        if r.get("google_access_token") or r.get("google_refresh_token")
    ]


async def test_revokes_each_refresh_token_and_scrubs_all_rows():
    db = _db(
        {
            "id": "1",
            "email": "a",
            "google_access_token": AT1,
            "google_refresh_token": RT1,
        },
        {
            "id": "2",
            "email": "b",
            "google_access_token": None,
            "google_refresh_token": RT2,
        },
    )
    revoke = AsyncMock(return_value=True)
    summary = await run(db, revoke=revoke)
    assert sorted(c.args[0] for c in revoke.await_args_list) == [RT1, RT2]
    assert _tokens_left(db) == []
    assert summary == {"scanned": 2, "revoked": 2, "unconfirmed": 0, "scrubbed": 2}


async def test_revoke_failure_still_scrubs_and_does_not_raise():
    db = _db({"id": "1", "email": "a", "google_refresh_token": RT1})
    summary = await run(db, revoke=AsyncMock(return_value=False))
    assert _tokens_left(db) == []
    assert summary["unconfirmed"] == 1 and summary["revoked"] == 0


async def test_revoke_exception_still_scrubs():
    db = _db({"id": "1", "email": "a", "google_refresh_token": RT1})
    summary = await run(db, revoke=AsyncMock(side_effect=RuntimeError("net")))
    assert _tokens_left(db) == []
    assert summary["unconfirmed"] == 1


async def test_access_token_only_row_revokes_access_token():
    db = _db({"id": "1", "email": "a", "google_access_token": AT1})
    revoke = AsyncMock(return_value=True)
    await run(db, revoke=revoke)
    revoke.assert_awaited_once_with(AT1)
    assert _tokens_left(db) == []


async def test_null_rows_make_no_calls_and_are_untouched():
    db = _db({"id": "1", "email": "a", "google_refresh_token": None})
    revoke = AsyncMock()
    summary = await run(db, revoke=revoke)
    revoke.assert_not_awaited()
    assert summary["scrubbed"] == 0 and summary["scanned"] == 1


async def test_processes_more_rows_than_one_batch():
    n = BATCH_SIZE + 5
    db = _db(
        *(
            {"id": str(i), "email": str(i), "google_refresh_token": f"rt{i}"}
            for i in range(n)
        )
    )
    summary = await run(db, revoke=AsyncMock(return_value=True))
    assert summary["scrubbed"] == n and _tokens_left(db) == []


async def test_no_token_in_logs_or_output(caplog, capsys):
    caplog.set_level(logging.DEBUG)
    db = _db(
        {
            "id": "1",
            "email": "a",
            "google_access_token": AT1,
            "google_refresh_token": RT1,
        }
    )
    await run(db, revoke=AsyncMock(side_effect=RuntimeError(f"failed {RT1}")))
    out = capsys.readouterr()
    for text in (caplog.text, out.out, out.err):
        assert RT1 not in text and AT1 not in text
