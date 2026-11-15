"""Tests for interviewer_research_node (specs/interviewer-research.md)."""

from unittest.mock import MagicMock, patch

import pytest

from agents.interviewer import interviewer_research_node
from models.briefing import InterviewerProfile
from models.research import SearchResult

NAME = "Jane Doe"
COMPANY = "Stripe"


def _hit(key, name=NAME, company=COMPANY):
    return SearchResult(
        title=f"{name} - {key}",
        url=f"https://{key}.com",
        content=f"{name} works at {company}" if company else f"{name} blog",
    )


def _hits(*keys, **kw):
    return [_hit(k, **kw) for k in keys]


def _run(state, search_side_effect, summary=None):
    summarize = MagicMock(return_value=summary or InterviewerProfile(summary="s"))
    search = MagicMock(side_effect=search_side_effect)
    with (
        patch("agents.interviewer.search_web", search),
        patch("agents.interviewer._summarize", summarize),
    ):
        out = interviewer_research_node(state)
    return out, search, summarize


def _state(**extra):
    return {"interviewer": NAME, "company": COMPANY, **extra}


def test_enough_results_first_try():  # scenario 1 (search half)
    out, search, summarize = _run(_state(), [_hits("a", "b", "c", "d")])
    assert search.call_count == 1
    assert summarize.call_count == 1
    assert out["warnings"] == []


def test_retries_when_fewer_than_two_relevant():  # scenario 2
    _, search, summarize = _run(
        _state(role="Backend Engineer"), [_hits("a"), _hits("b", "c")]
    )
    assert search.call_count == 2
    passed = summarize.call_args.args[3]
    assert [r.url for r in passed] == [f"https://{k}.com" for k in "abc"]
    assert "Backend Engineer" in search.call_args_list[1].args[0]


def test_retry_capped_at_three_attempts():  # scenario 3
    _, search, _ = _run(_state(), [[], _hits("a"), _hits("a")])
    assert search.call_count == 3


def test_zero_relevant_skips_llm_and_returns_empty():  # scenario 5
    out, _, summarize = _run(_state(), [[], [], []])
    assert summarize.call_count == 0
    assert out["interviewer_research"] == InterviewerProfile().model_dump()


def test_only_irrelevant_results_treated_as_zero():  # scenario 5
    other = _hits("x", "y", name="John Smith")
    _, _, summarize = _run(_state(), [other, other, other])
    assert summarize.call_count == 0


def test_irrelevant_results_filtered_out():  # scenario 6
    mixed = _hits("a", "b", "c") + _hits("x", "y", name="John Smith")
    _, search, summarize = _run(_state(), [mixed])
    assert search.call_count == 1
    passed = summarize.call_args.args[3]
    assert [r.url for r in passed] == [f"https://{k}.com" for k in "abc"]


def test_name_match_is_case_insensitive():  # scenario 6
    lower = [
        SearchResult(title="t", url="https://a.com", content="jane doe at stripe"),
        SearchResult(title="t", url="https://b.com", content="JANE DOE of STRIPE"),
    ]
    _, _, summarize = _run(_state(), [lower])
    assert len(summarize.call_args.args[3]) == 2


@pytest.mark.parametrize("interviewer", [None, "", "   "])
def test_no_interviewer_skips_everything(interviewer):  # scenario 8
    out, search, summarize = _run(
        {"interviewer": interviewer, "company": COMPANY, "warnings": ["w"]}, []
    )
    assert search.call_count == 0
    assert summarize.call_count == 0
    assert out["interviewer_research"] == InterviewerProfile().model_dump()
    assert out["warnings"] == ["w"]


def test_interviewer_key_absent_skips():  # scenario 8
    out, search, _ = _run({"company": COMPANY}, [])
    assert search.call_count == 0
    assert out["warnings"] == []


@pytest.mark.parametrize("company", [None, "", "  "])
def test_missing_company_raises_before_network(company):  # scenario 9
    search = MagicMock()
    with patch("agents.interviewer.search_web", search), pytest.raises(ValueError):
        interviewer_research_node({"interviewer": NAME, "company": company})
    search.assert_not_called()


def test_duplicate_urls_counted_once():  # scenario 10
    _, search, summarize = _run(_state(), [_hits("a"), _hits("a", "b")])
    assert search.call_count == 2
    passed = summarize.call_args.args[3]
    assert [r.url for r in passed] == ["https://a.com", "https://b.com"]


def test_duplicate_does_not_satisfy_retry_threshold():  # scenario 10
    _, search, _ = _run(_state(), [_hits("a"), _hits("a"), _hits("a")])
    assert search.call_count == 3


def test_query_without_role_has_no_stray_text():  # scenario 12
    _, search, _ = _run(_state(), [[], [], []])
    for call in search.call_args_list:
        q = call.args[0]
        assert "None" not in q
        assert "  " not in q
        assert NAME in q and COMPANY in q


def test_existing_warnings_preserved():  # scenario 14
    out, _, _ = _run(_state(warnings=["earlier"]), [_hits("a", "b", "c")])
    assert out["warnings"][0] == "earlier"
