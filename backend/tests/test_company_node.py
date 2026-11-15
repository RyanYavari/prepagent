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


# --- Slice 3: LLM summarization (scenarios 1, 7, 10) ---


def _run_with_llm(state, search_results, llm_overview=None, llm_error=None):
    llm = MagicMock()
    structured = llm.with_structured_output.return_value
    if llm_error:
        structured.invoke.side_effect = llm_error
    else:
        structured.invoke.return_value = llm_overview
    with (
        patch("agents.company.search_web", return_value=search_results),
        patch("agents.company.ChatAnthropic", return_value=llm) as ctor,
    ):
        out = company_research_node(state)
    return out, llm, structured, ctor


def test_summary_sources_are_result_urls():  # scenario 1
    results = _results("a", "b", "c", "d", "e")
    overview = CompanyOverview(summary="Payments company", sources=[])
    out, llm, structured, _ = _run_with_llm({"company": "Stripe"}, results, overview)

    llm.with_structured_output.assert_called_once_with(CompanyOverview)
    structured.invoke.assert_called_once()
    assert out["company_research"]["summary"] == "Payments company"
    assert out["company_research"]["sources"] == [r.url for r in results]
    assert out["warnings"] == []


def test_prompt_contains_results_and_grounding_rule():
    results = _results("a", "b", "c")
    _, _, structured, _ = _run_with_llm(
        {"company": "Stripe", "role": "SWE"}, results, CompanyOverview()
    )
    messages = structured.invoke.call_args.args[0]
    text = " ".join(str(m[1] if isinstance(m, tuple) else m.content) for m in messages)
    assert "Stripe" in text
    assert "https://a.com" in text and "about b" in text
    assert "do not include" in text.lower()


def test_fabricated_sources_are_dropped():  # scenario 7
    results = _results("a", "b", "c")
    overview = CompanyOverview(summary="s", sources=["https://made-up.com"])
    out, _, _, _ = _run_with_llm({"company": "Stripe"}, results, overview)
    assert out["company_research"]["sources"] == [r.url for r in results]
    assert "https://made-up.com" not in out["company_research"]["sources"]


def test_llm_failure_propagates():  # scenario 10
    with pytest.raises(RuntimeError, match="llm down"):
        _run_with_llm(
            {"company": "Stripe"},
            _results("a", "b", "c"),
            llm_error=RuntimeError("llm down"),
        )
