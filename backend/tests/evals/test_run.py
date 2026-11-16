import json
from unittest.mock import MagicMock, patch

import pytest

from evals import run as run_mod
from evals.briefing_cache import BriefingCache
from evals.budget import BudgetExceeded
from evals.report import format_table, prompt_hashes
from evals.run import RefusedToRun, run
from evals.run import guard_environment as real_guard
from tests.evals.test_samples import collected


@pytest.fixture(autouse=True)
def allow_run(monkeypatch):
    """run() refuses under pytest by design; lift that and set fake keys."""
    # pytest re-sets PYTEST_CURRENT_TEST at call time, so patch the guard itself;
    # the guard has its own test below.
    monkeypatch.setattr(run_mod, "guard_environment", lambda env=None: None)
    monkeypatch.setattr(run_mod, "post_feedback", lambda *a, **k: None)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.setenv(k, "sk-test-SECRETVALUE")


def fake_collect(calls):
    def collect(case, budget, cache):
        calls.append(case.id)
        col = collected()
        col.case = case
        return col

    return collect


def ok_scorer(judge, emb, budget):
    async def score(sample):
        return 0.9

    return score


def go(tmp_path, *extra, collect=None, scorer=ok_scorer):
    lines: list[str] = []
    calls: list[str] = []
    code = run(
        ["--results-dir", str(tmp_path), *extra],
        collect=collect or fake_collect(calls),
        scorer_factory=scorer,
        briefing_cache=BriefingCache(tmp_path / "briefings"),
        out=lines.append,
    )
    return code, lines, calls


def results_file(tmp_path):
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text()), files[0]


def test_cases_flag_runs_first_n(tmp_path):
    code, _, calls = go(tmp_path, "--limit", "2")
    data, _ = results_file(tmp_path)
    assert code == 0 and len(calls) == 2 and data["meta"]["cases_run"] == 2


def test_ids_flag(tmp_path):
    _, _, calls = go(tmp_path, "--cases", "datadog-sre-01")
    assert calls == ["datadog-sre-01"]


def test_results_shape_and_meta(tmp_path):
    go(tmp_path, "--limit", "1", "--label", "my change")
    data, path = results_file(tmp_path)
    assert path.name.endswith("-my-change.json")
    meta = data["meta"]
    assert set(meta["config"]["prompt_hashes"]) == {
        "company",
        "interviewer",
        "synthesis",
    }
    assert meta["config"]["judge_model"] == "claude-sonnet-5-5"  # cheaper default
    assert meta["dataset_version"] == "v1" and len(meta["dataset_sha256"]) == 64
    assert meta["config"]["metric_version"] == 2
    assert meta["truncated"] is False and "git" in meta
    case = data["cases"][0]
    assert {"scores", "contexts", "answer", "thresholds_met", "score_errors"} <= set(
        case
    )
    assert data["summary"]["faithfulness"]["n"] == 1


def test_dry_run_makes_no_clients(tmp_path):
    factory = MagicMock()
    collect = MagicMock()
    lines: list[str] = []
    with patch("evals.run.WebCache") as cache:
        code = run(
            ["--dry-run", "--limit", "2", "--results-dir", str(tmp_path)],
            collect=collect,
            scorer_factory=factory,
            out=lines.append,
        )
    assert code == 0
    factory.assert_not_called()
    collect.assert_not_called()
    cache.assert_not_called()
    assert not list(tmp_path.glob("*.json"))


def test_preflight_aborts_above_cap(tmp_path):
    code, lines, calls = go(tmp_path, "--limit", "3", "--max-llm-calls", "10")
    assert code == 2 and calls == []
    assert any("exceeds" in line for line in lines)


def test_no_force_flag_cap_is_a_hard_refusal(tmp_path):
    with pytest.raises(SystemExit):
        go(tmp_path, "--limit", "1", "--force")


def test_cap_truncates_and_writes_partial(tmp_path):
    calls: list[str] = []

    def collect(case, budget, cache):
        calls.append(case.id)
        if len(calls) == 2:
            raise BudgetExceeded("cap")
        col = collected()
        col.case = case
        return col

    code, _lines, _ = go(tmp_path, "--limit", "3", collect=collect)
    data, _ = results_file(tmp_path)
    assert code == 0
    assert data["meta"]["truncated"] is True and len(data["cases"]) == 1
    assert "truncated" in format_table(data)


def test_pipeline_error_case_is_reported_not_fatal(tmp_path):
    def collect(case, budget, cache):
        col = collected()
        col.case, col.sections, col.error = case, None, "RuntimeError"
        return col

    code, _lines, _ = go(tmp_path, "--limit", "1", collect=collect)
    data, _ = results_file(tmp_path)
    assert code == 0 and data["cases"][0]["error"] == "RuntimeError"
    assert all(v is None for v in data["cases"][0]["scores"].values())


def test_exit_code_zero_with_low_scores(tmp_path):
    def low(judge, emb, budget):
        async def score(sample):
            return 0.1

        return score

    code, lines, _ = go(tmp_path, "--limit", "1", scorer=low)
    assert code == 0
    assert "!" in "\n".join(lines)


def test_refuses_in_ci_and_pytest():
    with pytest.raises(RefusedToRun):
        real_guard({"CI": "true"})
    with pytest.raises(RefusedToRun):
        real_guard({"PYTEST_CURRENT_TEST": "x"})
    real_guard({})


def test_self_grading_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("JUDGE_MODEL", "claude-opus-5-5")
    _, lines, _ = go(tmp_path, "--limit", "1")
    data, _ = results_file(tmp_path)
    assert data["meta"]["self_grading"] is True
    assert any("self-grading" in line for line in lines)


def test_missing_keys_listed_without_values(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    code, lines, calls = go(tmp_path, "--limit", "1")
    assert code == 2 and calls == []
    text = "\n".join(lines)
    assert "OPENAI_API_KEY" in text and "SECRETVALUE" not in text


def test_no_secret_in_output_or_results(tmp_path):
    _, lines, _ = go(tmp_path, "--limit", "1")
    _, path = results_file(tmp_path)
    assert "SECRETVALUE" not in "\n".join(lines) + path.read_text()


def test_unknown_id_is_an_error(tmp_path):
    from evals.dataset import DatasetError

    with pytest.raises(DatasetError):
        go(tmp_path, "--cases", "nope")


def test_repeat_writes_one_file_each(tmp_path):
    go(tmp_path, "--limit", "1", "--repeat", "2", "--label", "x")
    names = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(names) == 2


def test_prompt_hashes_change_with_prompt():
    a = prompt_hashes()
    with patch("agents.company.SYSTEM_PROMPT", "different"):
        assert prompt_hashes()["company"] != a["company"]


def selected_scores(tmp_path):
    data, _ = results_file(tmp_path)
    return data, data["cases"][0]["scores"]


def test_context_recall_is_opt_in(tmp_path):
    go(tmp_path, "--limit", "1")
    data, scores = selected_scores(tmp_path)
    assert scores["context_recall"] is None
    assert "context_recall" not in data["meta"]["config"]["metrics"]
    assert scores["context_precision"] is not None


def test_metrics_flag_selects_and_recall_can_be_enabled(tmp_path):
    seen = []

    def scorer(judge, emb, budget):
        async def score(sample):
            seen.append(sample.metric)
            return 0.9

        return score

    go(
        tmp_path,
        "--limit",
        "1",
        "--metrics",
        "context_recall,faithfulness_company",
        scorer=scorer,
    )
    assert sorted(seen) == ["context_recall", "faithfulness_company"]
    data, scores = selected_scores(tmp_path)
    assert scores["context_recall"] == 0.9 and scores["answer_relevancy"] is None
    assert data["meta"]["config"]["metrics"] == [
        "context_recall",
        "faithfulness_company",
    ]
    table = format_table(data)
    assert "c.recall" in table and "relev" not in table


def test_metrics_faithfulness_alias_and_unknown_metric(tmp_path):
    go(tmp_path, "--limit", "1", "--metrics", "faithfulness")
    data, _ = results_file(tmp_path)
    assert data["meta"]["config"]["metrics"] == [
        "faithfulness_company",
        "faithfulness_interviewer",
        "faithfulness_synthesis",
    ]
    with pytest.raises(ValueError, match="unknown metric"):
        go(tmp_path / "x", "--limit", "1", "--metrics", "bogus")


def test_cases_flag_runs_listed_ids_in_order(tmp_path):
    _, _, calls = go(tmp_path, "--cases", "datadog-sre-01,stripe-backend-01")
    assert calls == ["datadog-sre-01", "stripe-backend-01"]


def test_limit_defaults_to_three(tmp_path):
    _, _, calls = go(tmp_path)
    assert len(calls) == 3


def test_pipeline_output_is_cached_after_a_normal_run(tmp_path):
    go(tmp_path, "--limit", "1")
    assert (tmp_path / "briefings" / "stripe-backend-01.json").exists()


def test_rescore_end_to_end_shared_cache(tmp_path):
    cache_dir = tmp_path / "briefings"
    lines: list[str] = []
    calls: list[str] = []

    def invoke(*extra, collect):
        return run(
            ["--results-dir", str(tmp_path / "res"), *extra],
            collect=collect,
            scorer_factory=ok_scorer,
            briefing_cache=BriefingCache(cache_dir),
            out=lines.append,
        )

    assert invoke("--limit", "2", collect=fake_collect(calls)) == 0
    calls.clear()

    def must_not_run(case, budget, cache):
        raise AssertionError("pipeline must not run on --rescore")

    assert invoke("--limit", "2", "--rescore", collect=must_not_run) == 0
    files = sorted((tmp_path / "res").glob("*.json"))
    data = json.loads(files[-1].read_text())
    assert data["meta"]["config"]["rescore"] is True
    assert data["meta"]["llm_calls"]["pipeline"] == 0
    assert all(c["error"] is None for c in data["cases"])
    # settings come from the cached briefings, not the current code
    assert set(data["meta"]["config"]["prompt_hashes"]) == {
        "company",
        "interviewer",
        "synthesis",
    }
    assert any("rescored from cached" in line for line in lines)


def test_rescore_cache_miss_is_a_case_error_not_a_crash(tmp_path):
    def must_not_run(case, budget, cache):
        raise AssertionError("pipeline must not run on --rescore")

    code, _lines, _ = go(tmp_path, "--limit", "1", "--rescore", collect=must_not_run)
    data, _ = results_file(tmp_path)
    assert code == 0 and data["cases"][0]["error"] == "BriefingCacheMiss"


def test_rescore_needs_no_tavily_or_openai_key_when_unneeded(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY")
    code, lines, _ = go(
        tmp_path, "--limit", "1", "--rescore", "--metrics", "faithfulness_company"
    )
    assert code == 0 and not any("Missing environment" in line for line in lines)


def test_preflight_prints_per_model_estimate_and_refuses_above_cap(tmp_path):
    code, lines, calls = go(tmp_path, "--limit", "4", "--max-llm-calls", "20")
    text = "\n".join(lines)
    assert code == 2 and calls == []
    assert "claude-sonnet-5-5: ~" in text and "vs cap 20" in text
    assert "Refusing to start" in text


def test_preflight_separates_agent_and_judge_models(tmp_path, monkeypatch):
    monkeypatch.setenv("JUDGE_MODEL", "claude-opus-5-5")
    _, lines, _ = go(tmp_path, "--limit", "1", "--dry-run")
    text = "\n".join(lines)
    assert "claude-sonnet-5-5: ~" in text and "claude-opus-5-5: ~" in text
    assert "self-grading" not in text


def test_rescore_estimate_has_no_pipeline_calls(tmp_path):
    _, lines, _ = go(tmp_path, "--limit", "2", "--rescore", "--dry-run")
    text = "\n".join(lines)
    assert "pipeline]" not in text and "Tavily ~0" in text
