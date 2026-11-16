"""Shared builders for calendar tests."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from services.calendar import Attendee, NormalizedEvent

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def raw_event(**over) -> dict:
    ev = {
        "id": "evt1",
        "etag": '"e1"',
        "status": "confirmed",
        "summary": "Interview with Acme",
        "description": "Technical interview for Senior Engineer",
        "start": {"dateTime": (NOW + timedelta(days=3)).isoformat()},
        "organizer": {"email": "jane@acme.com", "displayName": "Jane Doe"},
        "attendees": [
            {"email": "me@gmail.com", "self": True, "responseStatus": "accepted"},
            {"email": "jane@acme.com", "displayName": "Jane Doe"},
        ],
    }
    ev.update(over)
    return ev


def norm_event(**over) -> NormalizedEvent:
    base: dict[str, Any] = {
        "id": "evt1",
        "etag": '"e1"',
        "start": "2026-11-18T12:00:00+00:00",
        "title": "Interview with Acme",
        "description": "Technical interview for Senior Engineer",
        "organizer_name": "Jane Doe",
        "organizer_domain": "acme.com",
        "attendees": [Attendee(name="Jane Doe", domain="acme.com")],
        "user_response": "accepted",
    }
    base.update(over)
    return NormalizedEvent(**base)


# --- in-memory Supabase fake ------------------------------------------------

UNIQUE_KEYS = {
    "calendar_detections": ("user_id", "google_event_id"),
    "calendar_connections": ("user_id",),
}


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, name, op, payload=None, **opts):
        self.db, self.name, self.op, self.payload, self.opts = (
            db,
            name,
            op,
            payload,
            opts,
        )
        self.filters: list[tuple[str, str, object]] = []

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self.filters.append(("neq", col, val))
        return self

    def order(self, *a, **k):
        return self

    def range(self, start, end):
        self.opts["range"] = (start, end)
        return self

    def _match(self, row):
        for kind, col, val in self.filters:
            if kind == "eq" and row.get(col) != val:
                return False
            if kind == "neq" and row.get(col) == val:
                return False
        return True

    def execute(self):
        rows = self.db.tables.setdefault(self.name, [])
        if self.op == "select":
            hit = [dict(r) for r in rows if self._match(r)]
            if "range" in self.opts:
                start, end = self.opts["range"]
                hit = hit[start : end + 1]
            return _Result(hit)
        if self.op == "delete":
            gone = [r for r in rows if self._match(r)]
            self.db.tables[self.name] = [r for r in rows if r not in gone]
            return _Result([dict(r) for r in gone])
        if self.op == "update":
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(self.payload)
            return _Result([dict(r) for r in hit])
        if self.op in ("insert", "upsert"):
            keys = UNIQUE_KEYS.get(self.name)
            if self.op == "upsert" and keys:
                for r in rows:
                    if all(r.get(k) == self.payload.get(k) for k in keys):
                        if self.opts.get("ignore_duplicates"):
                            return _Result([])
                        r.update(self.payload)
                        return _Result([dict(r)])
            row = dict(self.payload)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", NOW.isoformat())
            row.setdefault("updated_at", NOW.isoformat())
            rows.append(row)
            return _Result([dict(row)])
        raise AssertionError(self.op)


class _Table:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def select(self, *a, **k):
        return _Query(self.db, self.name, "select")

    def insert(self, row):
        return _Query(self.db, self.name, "insert", row)

    def upsert(self, row, **opts):
        return _Query(self.db, self.name, "upsert", row, **opts)

    def update(self, values):
        return _Query(self.db, self.name, "update", values)

    def delete(self):
        return _Query(self.db, self.name, "delete")


class FakeSupabase:
    """Just enough of the supabase-py query builder for the calendar code."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def table(self, name):
        return _Table(self, name)

    def rows(self, name):
        return self.tables.get(name, [])
