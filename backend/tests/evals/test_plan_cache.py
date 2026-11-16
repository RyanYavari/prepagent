import pytest

from evals.briefing_cache import BriefingCache, BriefingCacheMiss, case_hash
from evals.collect import CollectedCase
from evals.dataset import GoldenCase
from evals.plan import judge_calls, make_plan, pipeline_calls
from evals.samples import DEFAULT_METRICS, parse_metrics
from tests.evals.test_samples import collected


def case(**kw) -> GoldenCase:
    base = {
        "id": "c1",
        "company": "Acme",
        "role": "Eng",
        "resume_text": "Summary\nA\n\nExperience\nB\n\nSkills\nC",
        "reference": ["x"],
    }
    return GoldenCase.model_validate({**base, **kw})


def test_default_metrics_exclude_recall_and_diagnostic():
    assert "context_recall" not in DEFAULT_METRICS
    assert "faithfulness_synthesis_with_prior" not in DEFAULT_METRICS
    assert "context_precision" in DEFAULT_METRICS


def test_parse_metrics():
    assert parse_metrics(None) == DEFAULT_METRICS
    assert parse_metrics("context_recall, answer_relevancy") == (
        "context_recall",
        "answer_relevancy",
    )
    assert parse_metrics("faithfulness,faithfulness_company")[:3] == (
        "faithfulness_company",
        "faithfulness_interviewer",
        "faithfulness_synthesis",
    )
    with pytest.raises(ValueError):
        parse_metrics("nope")
    with pytest.raises(ValueError):
        parse_metrics(" , ")


def test_call_counts_follow_case_shape():
    plain = case()
    with_interviewer = case(interviewer="Pat Q", interviewer_kind="fictional")
    assert pipeline_calls(plain) == 2 and pipeline_calls(with_interviewer) == 3
    m = (
        "faithfulness_interviewer",
        "context_precision",
        "context_recall",
        "answer_relevancy",
    )
    assert judge_calls(plain, m) == 0 + 3 + 1 + 3  # 3 resume chunks
    assert judge_calls(with_interviewer, m) == 2 + 3 + 1 + 3
    assert judge_calls(case(resume_text=None), m) == 3  # relevancy only


def test_prior_diagnostic_costs_only_with_same_company_prior():
    prior = [{"company": "acme", "section": "s", "content": "c"}]
    m = ("faithfulness_synthesis_with_prior",)
    assert judge_calls(case(prior_briefings=prior), m) == 2
    assert judge_calls(case(), m) == 0


def test_plan_per_model_and_rescore():
    cases = [case(), case(id="c2")]
    p = make_plan(
        cases,
        ("faithfulness_company",),
        rescore=False,
        agent_model="a",
        judge_model="j",
    )
    assert p.agent_calls == 4 and p.judge_calls == 4
    assert p.per_model == {"a": 4, "j": 4}
    r = make_plan(
        cases, ("faithfulness_company",), rescore=True, agent_model="a", judge_model="j"
    )
    assert r.agent_calls == 0 and r.tavily_calls == 0 and r.per_model == {"j": 4}
    same = make_plan(
        cases,
        ("faithfulness_company",),
        rescore=False,
        agent_model="m",
        judge_model="m",
    )
    assert same.per_model == {"m": 8}


def test_cost_unknown_model_is_none_not_a_guess():
    p = make_plan(
        [case()],
        ("faithfulness_company",),
        rescore=True,
        agent_model="a",
        judge_model="mystery-model",
    )
    assert p.cost is None


def test_cheaper_metric_set_is_cheaper():
    cases = [case(), case(id="c2")]
    full = make_plan(
        cases,
        DEFAULT_METRICS,
        rescore=True,
        agent_model="a",
        judge_model="claude-sonnet-5-5",
    )
    small = make_plan(
        cases,
        ("faithfulness_synthesis",),
        rescore=True,
        agent_model="a",
        judge_model="claude-sonnet-5-5",
    )
    assert small.judge_calls < full.judge_calls and small.cost < full.cost


def test_briefing_cache_roundtrip(tmp_path):
    cache = BriefingCache(tmp_path)
    col = collected(interviewer="Pat Q", prior=True)
    assert cache.save(col, agent_model="m", prompt_hashes={"company": "h"})
    loaded, meta = cache.load(col.case)
    assert loaded.sections == col.sections
    assert [r.url for r in loaded.web_company] == [r.url for r in col.web_company]
    assert [c.content for c in loaded.resume_chunks] == [
        c.content for c in col.resume_chunks
    ]
    assert len(loaded.prior_chunks) == 1 and loaded.error is None
    assert meta["agent_model"] == "m" and meta["prompt_hashes"] == {"company": "h"}


def test_errored_case_is_not_cached(tmp_path):
    cache = BriefingCache(tmp_path)
    bad = CollectedCase(case=case(), error="RuntimeError")
    assert cache.save(bad, agent_model="m", prompt_hashes={}) is False
    with pytest.raises(BriefingCacheMiss, match="without --rescore"):
        cache.load(bad.case)


def test_stale_cache_when_case_changes(tmp_path):
    cache = BriefingCache(tmp_path)
    col = collected()
    cache.save(col, agent_model="m", prompt_hashes={})
    changed = col.case.model_copy(update={"company": "Other"})
    assert case_hash(changed) != case_hash(col.case)
    with pytest.raises(BriefingCacheMiss, match="stale"):
        cache.load(changed)


def test_corrupt_cache_entry_is_a_miss_without_content(tmp_path):
    cache = BriefingCache(tmp_path)
    col = collected()
    cache.save(col, agent_model="m", prompt_hashes={})
    (tmp_path / "c.json").write_text("{not json")
    with pytest.raises(BriefingCacheMiss, match="unreadable"):
        cache.load(col.case)
