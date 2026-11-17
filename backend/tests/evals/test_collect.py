from unittest.mock import MagicMock, patch

import pytest

from evals.budget import BudgetExceeded, CallBudget
from evals.collect import (
    collect_case,
    make_retrieval,
    make_search,
    seams,
)
from evals.dataset import GoldenCase
from evals.webcache import WebCache, WebCacheMiss
from models.research import SearchResult

RESUME = "Summary\nBackend dev.\n\nExperience\nBuilt things at Halcyon.\n\nSkills\nGo"


def make_case(**kw) -> GoldenCase:
    base = {
        "id": "c1",
        "company": "Acme",
        "role": "Engineer",
        "resume_text": RESUME,
        "reference": ["x"],
        "prior_briefings": [
            {"company": "acme", "section": "talking_points", "content": "old"},
            {"company": "Other", "section": "talking_points", "content": "nope"},
        ],
    }
    return GoldenCase.model_validate({**base, **kw})


def sr(url: str) -> SearchResult:
    return SearchResult(title=url, url=url, content=f"content {url}")


def test_retrieval_is_in_memory_and_company_scoped():
    result = make_retrieval(make_case())("u", "Acme")
    assert [c.section for c in result.resume_chunks] == [
        "summary",
        "experience",
        "skills",
    ]
    assert [c.content for c in result.briefing_chunks] == ["old"]
    assert all(c.doc_type == "resume" for c in result.resume_chunks)


def test_retrieval_no_resume():
    result = make_retrieval(make_case(resume_text=None))("u", "Acme")
    assert result.resume_chunks == []


def test_search_records_and_counts():
    seen: dict = {}
    budget = CallBudget(10)
    search = make_search(
        seen, WebCache("off"), budget, lambda q, n=5: [sr("a"), sr("b")]
    )
    assert len(search("q")) == 2
    assert set(seen) == {"a", "b"}
    assert budget.snapshot()["tavily"] == 1


def test_search_cache_record_then_replay(tmp_path):
    seen: dict = {}
    calls = []

    def live(q, n=5):
        calls.append(q)
        return [sr("a")]

    rec = make_search(seen, WebCache("record", tmp_path), CallBudget(10), live)
    rec("q")
    budget = CallBudget(10)
    replay = make_search({}, WebCache("replay", tmp_path), budget, live)
    assert [r.url for r in replay("q")] == ["a"]
    assert calls == ["q"] and budget.snapshot()["web_cache_hits"] == 1
    with pytest.raises(WebCacheMiss):
        replay("never recorded")


def test_seams_patch_graph_modules_and_count_llm_calls():
    from agents import company, rag

    budget = CallBudget(2)
    fake_llm = MagicMock()
    with (
        patch.object(company, "structured_llm", return_value=fake_llm),
        seams(make_case(), budget, WebCache("off"), {}, {}, lambda q, n=5: [sr("a")]),
    ):
        assert rag.retrieve_user_context("u", "Acme").briefing_chunks
        company.structured_llm(object).invoke("x")
        company.structured_llm(object).invoke("y")
        with pytest.raises(BudgetExceeded):
            company.structured_llm(object).invoke("z")
        assert fake_llm.invoke.call_count == 2  # the third was refused before the call
        company.search_web("q")
    assert budget.pipeline == 2 and budget.tavily == 1


def final_state(**kw):
    state = {
        "briefing_content": {
            "company_overview": {"summary": "S", "sources": ["a", "b"]},
            "talking_points": {"talking_points": ["t [Resume: Experience]"]},
        },
        "warnings": ["w"],
        "company_research": {"sources": ["a", "b"]},
        "interviewer_research": {"sources": []},
        "retrieved_context": {
            "resume_chunks": [
                {"doc_type": "resume", "section": "skills", "content": "Go"}
            ],
            "briefing_chunks": [],
        },
    }
    state.update(kw)
    return state


def test_collect_case_captures_contexts_without_supabase():
    graph = MagicMock()

    def invoke(state, config=None):
        from agents import company

        company.search_web("q")  # recorded through the seam
        return final_state()

    graph.invoke.side_effect = invoke
    with patch("services.supabase_client.create_client") as sb:
        out = collect_case(
            make_case(),
            CallBudget(5),
            graph=graph,
            search=lambda q, n=5: [sr("a"), sr("b"), sr("z")],
        )
    sb.assert_not_called()
    assert out.error is None
    assert [r.url for r in out.web_company] == ["a", "b"]  # only what the node used
    assert out.web_interviewer == []
    assert out.pipeline_warnings == ["w"]
    assert out.sections.talking_points.talking_points == ["t [Resume: Experience]"]
    assert len(out.resume_chunks) == 1


def test_collect_case_records_error_class_only():
    graph = MagicMock()
    graph.invoke.side_effect = RuntimeError("secret detail sk-123")
    out = collect_case(make_case(), CallBudget(5), graph=graph)
    assert out.error == "RuntimeError" and out.sections is None


def test_collect_case_propagates_budget_exceeded():
    graph = MagicMock()
    graph.invoke.side_effect = BudgetExceeded("cap")
    with pytest.raises(BudgetExceeded):
        collect_case(make_case(), CallBudget(5), graph=graph)
