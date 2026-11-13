"""Tests for RAG retrieval service (specs/rag-retrieval.md scenarios 1, 2, 3, 7, 8)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from models.retrieval import RetrievalResult
from services.retrieval import retrieve_user_context


class FakeQuery:
    """Records the query chain and returns rows filtered like PostgREST would."""

    def __init__(self, rows):
        self._rows = rows
        self.selected = None
        self.eq_filters: dict[str, str] = {}
        self.order_args = None

    def select(self, cols):
        self.selected = cols
        return self

    def eq(self, col, val):
        self.eq_filters[col] = val
        return self

    def order(self, col, desc=False):
        self.order_args = (col, desc)
        return self

    def execute(self):
        rows = [
            r
            for r in self._rows
            if all(r.get(k) == v for k, v in self.eq_filters.items())
        ]

        class Result:
            data = rows

        return Result()


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.queries: list[FakeQuery] = []

    def table(self, name):
        assert name == "resume_embeddings"
        q = FakeQuery(self.rows)
        self.queries.append(q)
        return q


def _row(user_id, doc_type, content, section="experience", company=None):
    return {
        "user_id": str(user_id),
        "doc_type": doc_type,
        "section": section,
        "content": content,
        "company": company,
        "role": None,
        "created_at": "2026-01-01T00:00:00Z",
        "embedding": [0.1] * 3,  # must never be returned
    }


def _run(rows, user_id, company):
    fake = FakeSupabase(rows)
    with patch("services.retrieval.create_client", return_value=fake):
        result = retrieve_user_context(user_id, company)
    return result, fake


class TestRetrieveUserContext:
    def test_returns_all_resume_and_only_same_company_briefings(self):
        uid = uuid4()
        rows = [
            _row(uid, "resume", "r1"),
            _row(uid, "resume", "r2", "education"),
            _row(uid, "resume", "r3", "skills"),
            _row(uid, "briefing", "stripe-1", "company_overview", "Stripe"),
            _row(uid, "briefing", "acme-1", "company_overview", "Acme"),
        ]
        result, _ = _run(rows, uid, "Stripe")

        assert isinstance(result, RetrievalResult)
        assert [c.content for c in result.resume_chunks] == ["r1", "r2", "r3"]
        assert [c.content for c in result.briefing_chunks] == ["stripe-1"]

    def test_filters_every_query_by_user_id(self):
        uid, other = uuid4(), uuid4()
        rows = [
            _row(uid, "resume", "mine"),
            _row(other, "resume", "theirs"),
            _row(other, "briefing", "theirs-b", "company_overview", "Stripe"),
        ]
        result, fake = _run(rows, uid, "Stripe")

        assert len(fake.queries) == 2
        assert all(q.eq_filters["user_id"] == str(uid) for q in fake.queries)
        assert [c.content for c in result.resume_chunks] == ["mine"]
        assert result.briefing_chunks == []

    @pytest.mark.parametrize("target", ["stripe", " STRIPE ", "Stripe"])
    def test_company_match_is_case_and_whitespace_insensitive(self, target):
        uid = uuid4()
        rows = [_row(uid, "briefing", "b", "company_overview", "Stripe")]
        result, _ = _run(rows, uid, target)
        assert len(result.briefing_chunks) == 1

    def test_company_wildcards_are_escaped(self):
        uid = uuid4()
        rows = [
            _row(uid, "briefing", "other", "company_overview", "100XCo"),
            _row(uid, "briefing", "literal", "company_overview", "100%_Co"),
            _row(uid, "briefing", "star", "company_overview", "A*B"),
            _row(uid, "briefing", "star-other", "company_overview", "AxxB"),
        ]
        result, fake = _run(rows, uid, "100%_Co")
        star, _ = _run(rows, uid, "A*B")
        assert [c.content for c in star.briefing_chunks] == ["star"]

        assert [c.content for c in result.briefing_chunks] == ["literal"]
        assert fake.queries[1].order_args is not None
        assert [c.content for c in result.briefing_chunks] == ["literal"]

    def test_briefings_ordered_newest_first(self):
        uid = uuid4()
        _, fake = _run([], uid, "Stripe")
        assert fake.queries[1].order_args == ("created_at", True)

    def test_never_selects_or_returns_embedding(self):
        uid = uuid4()
        rows = [
            _row(uid, "resume", "r"),
            _row(uid, "briefing", "b", "company_overview", "Stripe"),
        ]
        result, fake = _run(rows, uid, "Stripe")

        assert all("embedding" not in q.selected for q in fake.queries)
        for chunk in result.resume_chunks + result.briefing_chunks:
            assert "embedding" not in chunk.model_dump()

    def test_database_error_propagates(self):
        class Boom:
            def table(self, name):
                raise RuntimeError("supabase down")

        with (
            patch("services.retrieval.create_client", return_value=Boom()),
            pytest.raises(RuntimeError, match="supabase down"),
        ):
            retrieve_user_context(uuid4(), "Stripe")
