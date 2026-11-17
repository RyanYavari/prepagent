"""FakeSupabase must stamp rows with the real clock.

It used to stamp every row with a fixed date (2026-11-15). Once that date was more
than 24 h in the past, rows it inserted fell outside the rolling 24 h cap window, so
the briefing cap tests that insert and then count started failing.
"""

from datetime import UTC, datetime, timedelta

from tests.calendar_helpers import FakeSupabase


def test_inserted_rows_are_stamped_with_the_current_time():
    db = FakeSupabase()
    before = datetime.now(UTC)
    db.table("briefings").insert({"user_id": "u", "company": "A"}).execute()
    after = datetime.now(UTC)

    stamp = datetime.fromisoformat(db.rows("briefings")[0]["created_at"])
    assert before - timedelta(seconds=1) <= stamp <= after + timedelta(seconds=1)
