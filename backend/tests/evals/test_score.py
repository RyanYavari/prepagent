import logging

import pytest

from evals.budget import BudgetExceeded, CallBudget
from evals.score import (
    EXTRACT_FACTS_PROMPT,
    FactList,
    aggregate,
    extract_facts,
    make_judge,
    resolve_judge_model,
    score_case,
    threshold_for,
)
from tests.evals.test_samples import collected


def fake_scorer(values=None, fail=()):
    values = values or {}

    async def scorer(sample):
        if sample.metric in fail:
            raise RuntimeError("secret detail sk-ant-abc123")
        return values.get(sample.metric, 0.9)

    return scorer


def test_score_case_maps_metrics_and_means_faithfulness():
    out = score_case(
        collected(interviewer="Pat Q"),
        fake_scorer(
            {
                "faithfulness_company": 1.0,
                "faithfulness_interviewer": 0.5,
                "faithfulness_synthesis": 0.6,
            }
        ),
    )
    assert out.scores["faithfulness"] == pytest.approx(0.7, abs=1e-3)
    assert out.scores["answer_relevancy"] == 0.9
    assert out.errors == {}


def test_skipped_metrics_are_null_not_zero():
    out = score_case(collected(resume=False), fake_scorer())
    assert out.scores["context_precision"] is None
    assert out.scores["faithfulness_interviewer"] is None


def test_scorer_error_is_null_with_class_only_and_others_survive(caplog):
    with caplog.at_level(logging.DEBUG):
        out = score_case(collected(), fake_scorer(fail={"context_recall"}))
    assert out.scores["context_recall"] is None
    assert out.errors == {"context_recall": "RuntimeError"}
    assert out.scores["answer_relevancy"] == 0.9
    assert "sk-ant" not in caplog.text and "secret" not in caplog.text


def test_nan_score_is_null():
    out = score_case(collected(), fake_scorer({"answer_relevancy": float("nan")}))
    assert out.scores["answer_relevancy"] is None
    assert out.errors["answer_relevancy"] == "NaN"


def test_budget_exceeded_propagates():
    async def scorer(sample):
        raise BudgetExceeded("cap")

    with pytest.raises(BudgetExceeded):
        score_case(collected(), scorer)


def test_prior_diagnostic_delta():
    out = score_case(
        collected(prior=True),
        fake_scorer(
            {"faithfulness_synthesis": 0.6, "faithfulness_synthesis_with_prior": 0.9}
        ),
    )
    assert out.diagnostics["prior_briefing_chunk_count"] == 1
    assert out.diagnostics["prior_faithfulness_delta"] == pytest.approx(0.3, abs=1e-3)
    assert "faithfulness_synthesis_with_prior" not in out.scores


def test_aggregate_ignores_nulls_and_flags_below_threshold():
    rows = [
        {"faithfulness": 0.9, "answer_relevancy": 0.7, "context_precision": None},
        {"faithfulness": 0.8, "answer_relevancy": None, "context_precision": None},
    ]
    s = aggregate(rows)
    assert s["faithfulness"]["mean"] == 0.85
    assert s["faithfulness"]["below_threshold_count"] == 1  # 0.8 < 0.85
    assert (
        s["answer_relevancy"]["n"] == 1
        and s["answer_relevancy"]["below_threshold_count"] == 1
    )
    assert s["context_precision"]["mean"] is None and s["context_precision"]["n"] == 0


def test_thresholds():
    assert threshold_for("faithfulness_company") == 0.85
    assert threshold_for("context_recall") == 0.75


def test_judge_model_env_and_self_grading(monkeypatch):
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    # default is the cheaper Sonnet-class model; it equals the default agent model,
    # so a default run is flagged self-grading
    assert resolve_judge_model("claude-sonnet-5-5") == ("claude-sonnet-5-5", True)
    assert resolve_judge_model("some-other-agent") == ("claude-sonnet-5-5", False)
    monkeypatch.setenv("JUDGE_MODEL", "claude-opus-5-5")
    assert resolve_judge_model("claude-sonnet-5-5") == ("claude-opus-5-5", False)


def test_unselected_metrics_make_no_scorer_calls():
    seen = []

    async def scorer(sample):
        seen.append(sample.metric)
        return 0.9

    out = score_case(collected(), scorer, ["faithfulness_company"])
    assert seen == ["faithfulness_company"]
    assert out.scores["answer_relevancy"] is None
    assert out.scores["faithfulness"] == 0.9


def test_answer_relevancy_embeddings_are_lazy(monkeypatch):
    import asyncio

    from evals import score as score_mod
    from evals.samples import Sample

    built = []
    monkeypatch.setattr(score_mod, "make_judge", lambda m, b: object())
    monkeypatch.setattr(
        score_mod, "make_embeddings", lambda m: built.append(m) or object()
    )
    import ragas.metrics.collections as coll

    class FakeFaith:
        def __init__(self, llm):
            pass

        async def ascore(self, **k):
            return type("R", (), {"value": 1.0})()

    monkeypatch.setattr(coll, "Faithfulness", FakeFaith)
    monkeypatch.setattr(coll, "AnswerRelevancy", lambda **k: None)
    monkeypatch.setattr(coll, "ContextPrecisionWithReference", lambda **k: None)
    monkeypatch.setattr(coll, "ContextRecall", lambda **k: None)
    scorer = score_mod.make_ragas_scorer("j", "e", CallBudget(5))
    asyncio.run(scorer(Sample("faithfulness_company", "q", "r", ["c"])))
    assert built == []  # no OpenAI client needed for a faithfulness-only run


def test_judge_charges_budget_before_calling(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    budget = CallBudget(1)
    judge = make_judge("claude-opus-5-5", budget)
    from unittest.mock import MagicMock

    runnable = MagicMock()
    judge._runnable = lambda m: runnable  # type: ignore[method-assign]
    judge.generate("p", dict)
    assert runnable.invoke.call_count == 1
    with pytest.raises(BudgetExceeded):
        judge.generate("p", dict)
    assert runnable.invoke.call_count == 1


def test_judge_is_accepted_by_ragas_metrics(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from ragas.metrics.collections import ContextRecall, Faithfulness

    judge = make_judge("claude-opus-5-5", CallBudget(5))
    Faithfulness(llm=judge)
    ContextRecall(llm=judge)


class FakeJudge:
    def __init__(self, facts):
        self.facts = facts
        self.prompts = []

    async def agenerate(self, prompt, response_model):
        self.prompts.append((prompt, response_model))
        return FactList(facts=self.facts)


def test_extract_facts_prompt_drops_advice_and_returns_clean_facts():
    import asyncio

    judge = FakeJudge(["  Candidate built X  ", "", "Company did Y"])
    facts = asyncio.run(extract_facts(judge, "Talking point: say X"))
    assert facts == ["Candidate built X", "Company did Y"]
    prompt, model = judge.prompts[0]
    assert "Talking point: say X" in prompt and model is FactList
    assert (
        "Do not add" in EXTRACT_FACTS_PROMPT and "Drop advice" in EXTRACT_FACTS_PROMPT
    )


def test_prescriptive_scorer_extracts_then_scores_facts_only(monkeypatch):
    """The real scorer must send only extracted facts (not advice wording) to
    Faithfulness, and return NaN (null) when no facts remain."""
    import asyncio

    from evals import score as score_mod
    from evals.samples import Sample

    seen = {}

    class FakeFaith:
        def __init__(self, llm):
            pass

        async def ascore(self, user_input, response, retrieved_contexts):
            seen["response"] = response
            return type("R", (), {"value": 0.75})()

    judge = FakeJudge(["Candidate built X"])
    monkeypatch.setattr(score_mod, "make_judge", lambda m, b: judge)
    monkeypatch.setattr(score_mod, "make_embeddings", lambda m: object())
    import ragas.metrics.collections as coll

    monkeypatch.setattr(coll, "Faithfulness", FakeFaith)
    monkeypatch.setattr(coll, "AnswerRelevancy", lambda **k: None)
    monkeypatch.setattr(coll, "ContextPrecisionWithReference", lambda **k: None)
    monkeypatch.setattr(coll, "ContextRecall", lambda **k: None)
    scorer = score_mod.make_ragas_scorer("j", "e", CallBudget(5))
    sample = Sample(
        "faithfulness_prescriptive",
        "q",
        "Talking point: say X",
        ["ctx"],
        extract_facts=True,
    )
    assert asyncio.run(scorer(sample)) == 0.75
    assert seen["response"] == "Candidate built X"

    judge.facts = []
    import math

    assert math.isnan(asyncio.run(scorer(sample)))


def test_case_scores_report_all_synthesis_variants():
    out = score_case(
        collected(),
        fake_scorer(
            {
                "faithfulness_synthesis": 0.9,
                "faithfulness_synthesis_all": 0.6,
                "faithfulness_prescriptive": 0.8,
            }
        ),
    )
    assert out.scores["faithfulness_synthesis"] == 0.9
    assert out.scores["faithfulness_synthesis_all"] == 0.6
    assert out.scores["faithfulness_prescriptive"] == 0.8
    # the case-level mean covers the factual groups only
    assert (
        "faithfulness_prescriptive"
        not in __import__("evals.samples", fromlist=["x"]).FAITHFULNESS_METRICS
    )
