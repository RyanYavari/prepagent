"""Tests for interviewer_research_node (specs/interviewer-research.md)."""

from unittest.mock import MagicMock, patch

import pytest

from agents.interviewer import (
    interviewer_research_node,
    low_result_warning,
    wrong_person_warning,
)
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


def test_two_relevant_adds_low_result_warning():  # scenario 4
    out, _, summarize = _run(_state(), [_hits("a", "b")])
    assert summarize.call_count == 1
    assert low_result_warning(NAME, 2) in out["warnings"]
    assert "Limited public information available for Jane Doe" in out["warnings"][0]
    assert "based on 2 sources" in out["warnings"][0]


def test_three_relevant_has_no_low_result_warning():  # scenario 4
    out, _, _ = _run(_state(), [_hits("a", "b", "c")])
    assert out["warnings"] == []


def test_zero_relevant_adds_low_result_warning_n0():  # scenario 5
    out, _, _ = _run(_state(), [[], [], []])
    assert out["warnings"] == [low_result_warning(NAME, 0)]


def test_wrong_person_warning_when_no_company_mention():  # scenario 7
    out, _, summarize = _run(_state(), [_hits("a", "b", "c", company=None)])
    assert summarize.call_count == 1
    assert out["warnings"] == [wrong_person_warning(NAME, COMPANY)]


def test_no_wrong_person_warning_when_one_result_mentions_company():  # scenario 7
    results = _hits("a", "b", company=None) + _hits("c")
    out, _, _ = _run(_state(), [results])
    assert out["warnings"] == []


def test_company_mention_is_case_insensitive():  # scenario 7
    results = [
        SearchResult(title="t", url=f"https://{k}.com", content=f"{NAME} at STRIPE")
        for k in "abc"
    ]
    out, _, _ = _run(_state(), [results])
    assert out["warnings"] == []


def test_low_result_and_wrong_person_warnings_both_added():  # scenarios 4+7
    out, _, _ = _run(_state(), [_hits("a", company=None), _hits("b", company=None)])
    assert out["warnings"] == [
        low_result_warning(NAME, 2),
        wrong_person_warning(NAME, COMPANY),
    ]


def test_zero_relevant_has_no_wrong_person_warning():  # scenario 5/7
    out, _, _ = _run(_state(), [[], [], []])
    assert wrong_person_warning(NAME, COMPANY) not in out["warnings"]


# --- Slice 3: LLM summarization (scenarios 1, 11, 13) ---


def _run_with_llm(state, search_results, llm_profile=None, llm_error=None):
    llm = MagicMock()
    structured = llm.with_structured_output.return_value
    if llm_error:
        structured.invoke.side_effect = llm_error
    else:
        structured.invoke.return_value = llm_profile
    with (
        patch("agents.interviewer.search_web", return_value=search_results),
        patch("agents.llm.ChatAnthropic", return_value=llm) as ctor,
    ):
        out = interviewer_research_node(state)
    return out, llm, structured, ctor


def test_summary_sources_are_result_urls():  # scenario 1
    results = _hits("a", "b", "c", "d")
    profile = InterviewerProfile(summary="Staff engineer", sources=[])
    out, llm, structured, _ = _run_with_llm(_state(), results, profile)

    llm.with_structured_output.assert_called_once_with(
        InterviewerProfile, method="json_schema"
    )
    structured.invoke.assert_called_once()
    assert out["interviewer_research"]["summary"] == "Staff engineer"
    assert out["interviewer_research"]["sources"] == [r.url for r in results]
    assert out["warnings"] == []


def test_prompt_contains_results_and_grounding_rules():
    results = _hits("a", "b", "c")
    _, _, structured, _ = _run_with_llm(
        _state(role="SWE"), results, InterviewerProfile()
    )
    messages = structured.invoke.call_args.args[0]
    text = " ".join(str(m[1] if isinstance(m, tuple) else m.content) for m in messages)
    assert NAME in text and COMPANY in text
    assert "https://a.com" in text and f"{NAME} works at {COMPANY}" in text
    assert "do not include" in text.lower()
    assert "different people" in text.lower()


def test_fabricated_sources_are_dropped():  # scenario 11
    results = _hits("a", "b", "c")
    profile = InterviewerProfile(summary="s", sources=["https://made-up.com"])
    out, _, _, _ = _run_with_llm(_state(), results, profile)
    assert out["interviewer_research"]["sources"] == [r.url for r in results]


def test_llm_returning_dict_is_validated():
    out, _, _, _ = _run_with_llm(_state(), _hits("a", "b", "c"), {"summary": "d"})
    assert out["interviewer_research"]["summary"] == "d"


def test_llm_failure_propagates():  # scenario 13
    with pytest.raises(RuntimeError, match="llm down"):
        _run_with_llm(
            _state(), _hits("a", "b", "c"), llm_error=RuntimeError("llm down")
        )


def test_search_failure_propagates():  # scenario 13
    with (
        patch("agents.interviewer.search_web", side_effect=RuntimeError("tavily")),
        pytest.raises(RuntimeError, match="tavily"),
    ):
        interviewer_research_node(_state())
