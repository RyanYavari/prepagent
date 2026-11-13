"""Tests for the rag_retrieval node (specs/rag-retrieval.md scenarios 4, 5, 6)."""

from unittest.mock import patch
from uuid import uuid4

import pytest

from agents.rag import NO_RESUME_WARNING, rag_retrieval_node
from models.retrieval import RetrievalResult, RetrievedChunk


def _chunk(doc_type="resume", content="c"):
    return RetrievedChunk(doc_type=doc_type, section="experience", content=content)


def _run(state, result):
    with patch("agents.rag.retrieve_user_context", return_value=result) as m:
        out = rag_retrieval_node(state)
    return out, m


def test_returns_retrieved_context_without_warning():
    uid = str(uuid4())
    result = RetrievalResult(
        resume_chunks=[_chunk(content="r1")],
        briefing_chunks=[_chunk("briefing", "b1")],
    )
    out, m = _run({"user_id": uid, "company": "Stripe"}, result)

    m.assert_called_once_with(uid, "Stripe")
    assert out["retrieved_context"]["resume_chunks"][0]["content"] == "r1"
    assert out["retrieved_context"]["briefing_chunks"][0]["content"] == "b1"
    assert out["warnings"] == []


def test_no_resume_adds_warning_and_does_not_raise():
    out, _ = _run({"user_id": "u", "company": "Stripe"}, RetrievalResult())
    assert out["retrieved_context"]["resume_chunks"] == []
    assert out["warnings"] == [NO_RESUME_WARNING]


def test_no_prior_briefings_is_not_a_warning():
    result = RetrievalResult(resume_chunks=[_chunk()])
    out, _ = _run({"user_id": "u", "company": "Stripe"}, result)
    assert out["retrieved_context"]["briefing_chunks"] == []
    assert out["warnings"] == []


def test_preserves_existing_warnings():
    state = {"user_id": "u", "company": "Stripe", "warnings": ["earlier"]}
    out, _ = _run(state, RetrievalResult())
    assert out["warnings"] == ["earlier", NO_RESUME_WARNING]


@pytest.mark.parametrize(
    "state",
    [
        {"company": "Stripe"},
        {"user_id": "", "company": "Stripe"},
        {"user_id": "u"},
        {"user_id": "u", "company": "   "},
    ],
)
def test_missing_user_or_company_raises_without_querying(state):
    with (
        patch("agents.rag.retrieve_user_context") as m,
        pytest.raises(ValueError),
    ):
        rag_retrieval_node(state)
    m.assert_not_called()


def test_db_error_propagates():
    with (
        patch("agents.rag.retrieve_user_context", side_effect=RuntimeError("down")),
        pytest.raises(RuntimeError, match="down"),
    ):
        rag_retrieval_node({"user_id": "u", "company": "Stripe"})
