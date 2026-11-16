"""Tests for the briefing chunk writer (specs/briefing-chunk-writer.md)."""

from unittest.mock import MagicMock, patch

import pytest

from services import briefing_chunks
from services.briefing_chunks import render_sections, write_briefing_chunks

FULL = {
    "company_overview": {
        "summary": "Payments company [Source: https://stripe.com]",
        "recent_news": ["Raised funds"],
        "tech_stack": ["Ruby"],
        "culture_notes": "Rigorous",
        "sources": ["https://stripe.com"],
    },
    "interviewer_profile": {"summary": "Jane leads infra", "background": "Ex-AWS"},
    "role_insights": {"key_requirements": ["Distributed systems"]},
    "talking_points": {
        "talking_points": ["Scaled queues [Resume: Experience]"],
        "suggested_questions": ["How is oncall run?"],
    },
    "warnings": ["Limited public info SECRET-WARNING"],
}


def test_render_sections_full():
    out = dict(render_sections(FULL))
    assert list(out) == [
        "company_overview",
        "interviewer_profile",
        "role_insights",
        "talking_points",
    ]
    assert "Payments company [Source: https://stripe.com]" in out["company_overview"]
    assert "Ruby" in out["company_overview"]
    assert "How is oncall run?" in out["talking_points"]


def test_render_skips_empty_sections_scenario_3():
    content = {**FULL, "interviewer_profile": {}}
    names = [n for n, _ in render_sections(content)]
    assert "interviewer_profile" not in names
    assert len(names) == 3


def test_render_all_empty_scenario_4():
    assert render_sections({"company_overview": {}, "warnings": ["w"]}) == []
    assert render_sections({}) == []


def test_warnings_not_embedded_scenario_9():
    assert all("SECRET-WARNING" not in c for _, c in render_sections(FULL))


# --- writer (scenarios 1, 2, 4, 8, 9) ---


class FakeTable:
    def __init__(self, store):
        self.store = store
        self._op = None
        self._filters = {}
        self._rows = None

    def delete(self):
        self._op = "delete"
        return self

    def insert(self, rows):
        self._op = "insert"
        self._rows = rows
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        if self._op == "delete":
            self.store[:] = [
                r
                for r in self.store
                if not all(r.get(k) == v for k, v in self._filters.items())
            ]
            self.store.deletes.append(dict(self._filters))
        elif self._op == "insert":
            self.store.extend(self._rows)


class FakeStore(list):
    deletes: list

    def __init__(self, *a):
        super().__init__(*a)
        self.deletes = []


class FakeSb:
    def __init__(self, store):
        self.store = store
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return FakeTable(self.store)


@pytest.fixture
def sb():
    store = FakeStore()
    fake = FakeSb(store)
    with (
        patch.object(briefing_chunks, "_get_supabase", return_value=fake),
        patch.object(briefing_chunks, "embed_text", return_value=[0.1] * 1536) as emb,
    ):
        fake.embed = emb
        yield fake


def test_write_happy_path_scenario_1(sb):
    n = write_briefing_chunks("u-1", "b-1", "Stripe", "Backend", FULL)
    assert n == 4
    rows = sb.store
    assert {r["section"] for r in rows} == {
        "company_overview",
        "interviewer_profile",
        "role_insights",
        "talking_points",
    }
    for r in rows:
        assert r["doc_type"] == "briefing"
        assert r["user_id"] == "u-1"
        assert r["briefing_id"] == "b-1"
        assert r["company"] == "Stripe"
        assert r["role"] == "Backend"
        assert len(r["embedding"]) == 1536
    assert set(sb.tables) == {"resume_embeddings"}


def test_write_none_role_is_null_scenario_9(sb):
    write_briefing_chunks("u-1", "b-1", "Stripe", None, FULL)
    assert all(r["role"] is None for r in sb.store)


def test_write_idempotent_scenario_8(sb):
    write_briefing_chunks("u-1", "b-1", "Stripe", None, FULL)
    write_briefing_chunks("u-1", "b-1", "Stripe", None, FULL)
    assert len(sb.store) == 4
    assert sb.store.deletes[0] == {
        "user_id": "u-1",
        "briefing_id": "b-1",
        "doc_type": "briefing",
    }


def test_write_does_not_touch_other_briefings(sb):
    sb.store.append({"user_id": "u-1", "briefing_id": "b-0", "doc_type": "briefing"})
    sb.store.append({"user_id": "u-1", "briefing_id": None, "doc_type": "resume"})
    write_briefing_chunks("u-1", "b-1", "Stripe", None, FULL)
    assert len(sb.store) == 6


def test_write_nothing_to_embed_scenario_4(sb):
    assert write_briefing_chunks("u-1", "b-1", "Stripe", None, {}) == 0
    sb.embed.assert_not_called()
    assert sb.store == []


def test_embedding_failure_propagates_without_partial_insert(sb):
    sb.embed.side_effect = RuntimeError("openai down")
    with pytest.raises(RuntimeError):
        write_briefing_chunks("u-1", "b-1", "Stripe", None, FULL)
    assert sb.store == []


def test_retrieval_round_trip_scenario_2(sb):
    """Rows written by the writer are readable by retrieve_user_context."""
    write_briefing_chunks("u-1", "b-1", "Stripe", "Backend", FULL)
    rows = [{**r, "created_at": "2026-11-15"} for r in sb.store]
    from services import retrieval

    class Q:
        def __init__(self):
            self.f = {}

        def select(self, _):
            return self

        def eq(self, k, v):
            self.f[k] = v
            return self

        def order(self, *a, **k):
            return self

        def execute(self):
            return MagicMock(
                data=[r for r in rows if all(r.get(k) == v for k, v in self.f.items())]
            )

    client = MagicMock()
    client.table.side_effect = lambda _: Q()
    with patch.object(retrieval, "create_client", return_value=client):
        got = retrieval.retrieve_user_context("u-1", "stripe")
        other = retrieval.retrieve_user_context("u-1", "Acme")
        other_user = retrieval.retrieve_user_context("u-2", "Stripe")
    assert len(got.briefing_chunks) == 4
    assert other.briefing_chunks == []
    assert other_user.briefing_chunks == []
