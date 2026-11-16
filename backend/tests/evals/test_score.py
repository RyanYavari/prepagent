import logging

import pytest

from evals.budget import BudgetExceeded, CallBudget
from evals.score import (
    aggregate,
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
    model, same = resolve_judge_model("claude-sonnet-5-5")
    assert model != "claude-sonnet-5-5" and not same
    monkeypatch.setenv("JUDGE_MODEL", "claude-sonnet-5-5")
    assert resolve_judge_model("claude-sonnet-5-5") == ("claude-sonnet-5-5", True)


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
