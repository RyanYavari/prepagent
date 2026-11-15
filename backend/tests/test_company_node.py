"""Tests for company_research_node (specs/company-intelligence.md)."""

from unittest.mock import MagicMock, patch

import pytest

from agents.company import company_research_node, low_result_warning
from models.briefing import CompanyOverview
from models.research import SearchResult


def _results(*names):
    return [
        SearchResult(title=n, url=f"https://{n}.com", content=f"about {n}")
        for n in names
    ]


def _run(state, search_side_effect, summary=None):
    summarize = MagicMock(return_value=summary or CompanyOverview(summary="s"))
    search = MagicMock(side_effect=search_side_effect)
    with (
        patch("agents.company.search_web", search),
        patch("agents.company._summarize", summarize),
    ):
        out = company_research_node(state)
    return out, search, summarize


def test_enough_results_first_try_no_retry_no_warning():  # scenario 1 (search half)
    out, search, summarize = _run(
        {"company": "Stripe"}, [_results("a", "b", "c", "d", "e")]
    )
    assert search.call_count == 1
    assert summarize.call_count == 1
    assert out["warnings"] == []


def test_retries_when_fewer_than_two_results():  # scenario 2
    out, search, summarize = _run(
        {"company": "Stripe", "role": "Backend Engineer"},
        [_results("a"), _results("b", "c", "d")],
    )
    assert search.call_count == 2
    passed = summarize.call_args.args[2]
    assert [r.url for r in passed] == [f"https://{n}.com" for n in "abcd"]
    assert out["warnings"] == []
    assert "Backend Engineer" in search.call_args_list[1].args[0]


def test_retry_capped_at_three_attempts():  # scenario 3
    _, search, _ = _run({"company": "Stripe"}, [[], _results("a"), _results("a")])
    assert search.call_count == 3


def test_two_results_adds_low_result_warning():  # scenario 4
    out, _, summarize = _run({"company": "Stripe"}, [_results("a", "b")])
    assert summarize.call_count == 1
    assert out["warnings"] == [low_result_warning("Stripe", 2)]
    assert (
        low_result_warning("Stripe", 2)
        == "Limited public information available for Stripe. "
        "The following profile is based on 2 sources and may be incomplete."
    )


def test_three_results_no_warning():  # scenario 4
    out, _, _ = _run({"company": "Stripe"}, [_results("a", "b", "c")])
    assert out["warnings"] == []


def test_zero_results_skips_llm_and_warns():  # scenario 5
    out, search, summarize = _run({"company": "Stripe"}, [[], [], []])
    assert search.call_count == 3
    summarize.assert_not_called()
    assert out["company_research"] == CompanyOverview().model_dump()
    assert out["warnings"] == [low_result_warning("Stripe", 0)]


def test_duplicate_urls_counted_once():  # scenario 6
    out, _, summarize = _run(
        {"company": "Stripe"}, [_results("a"), _results("a", "b", "c")]
    )
    assert [r.url for r in summarize.call_args.args[2]] == [
        "https://a.com",
        "https://b.com",
        "https://c.com",
    ]
    assert out["warnings"] == []
    # duplicates alone must not satisfy the >=2 threshold
    _, search2, _ = _run(
        {"company": "Stripe"}, [_results("a"), _results("a"), _results("a")]
    )
    assert search2.call_count == 3


def test_retry_query_without_role_is_clean():  # scenario 8
    _, search, _ = _run({"company": "Stripe"}, [[], _results("a", "b", "c")])
    q = search.call_args_list[1].args[0]
    assert "None" not in q
    assert "  " not in q
    assert q.startswith("Stripe ")


@pytest.mark.parametrize("state", [{}, {"company": ""}, {"company": "   "}])
def test_missing_company_raises_before_network(state):  # scenario 9
    search = MagicMock()
    with patch("agents.company.search_web", search), pytest.raises(ValueError):
        company_research_node(state)
    search.assert_not_called()


def test_existing_warnings_preserved():  # scenario 11
    out, _, _ = _run(
        {"company": "Stripe", "warnings": ["earlier"]}, [_results("a")] * 3
    )
    assert out["warnings"][0] == "earlier"
    assert out["warnings"][1] == low_result_warning("Stripe", 1)
