import json
from unittest.mock import MagicMock, patch

import pytest

from evals import run as run_mod
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
        out=lines.append,
    )
    return code, lines, calls


def results_file(tmp_path):
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text()), files[0]


def test_cases_flag_runs_first_n(tmp_path):
    code, _, calls = go(tmp_path, "--cases", "2")
    data, _ = results_file(tmp_path)
    assert code == 0 and len(calls) == 2 and data["meta"]["cases_run"] == 2


def test_ids_flag(tmp_path):
    _, _, calls = go(tmp_path, "--ids", "datadog-sre-01")
    assert calls == ["datadog-sre-01"]


def test_results_shape_and_meta(tmp_path):
    go(tmp_path, "--cases", "1", "--label", "my change")
    data, path = results_file(tmp_path)
    assert path.name.endswith("-my-change.json")
    meta = data["meta"]
    assert set(meta["config"]["prompt_hashes"]) == {
        "company",
        "interviewer",
        "synthesis",
    }
    assert meta["config"]["judge_model"] != meta["config"]["agent_model"]
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
            ["--dry-run", "--cases", "2", "--results-dir", str(tmp_path)],
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
    code, lines, calls = go(tmp_path, "--cases", "3", "--max-llm-calls", "10")
    assert code == 2 and calls == []
    assert any("exceeds" in line for line in lines)


def test_force_overrides_preflight(tmp_path):
    code, _, calls = go(tmp_path, "--cases", "1", "--max-llm-calls", "10", "--force")
    assert code == 0 and len(calls) == 1


def test_cap_truncates_and_writes_partial(tmp_path):
    calls: list[str] = []

    def collect(case, budget, cache):
        calls.append(case.id)
        if len(calls) == 2:
            raise BudgetExceeded("cap")
        col = collected()
        col.case = case
        return col

    code, _lines, _ = go(tmp_path, "--cases", "3", collect=collect)
    data, _ = results_file(tmp_path)
    assert code == 0
    assert data["meta"]["truncated"] is True and len(data["cases"]) == 1
    assert "truncated" in format_table(data)


def test_pipeline_error_case_is_reported_not_fatal(tmp_path):
    def collect(case, budget, cache):
        col = collected()
        col.case, col.sections, col.error = case, None, "RuntimeError"
        return col

    code, _lines, _ = go(tmp_path, "--cases", "1", collect=collect)
    data, _ = results_file(tmp_path)
    assert code == 0 and data["cases"][0]["error"] == "RuntimeError"
    assert all(v is None for v in data["cases"][0]["scores"].values())


def test_exit_code_zero_with_low_scores(tmp_path):
    def low(judge, emb, budget):
        async def score(sample):
            return 0.1

        return score

    code, lines, _ = go(tmp_path, "--cases", "1", scorer=low)
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
    _, lines, _ = go(tmp_path, "--cases", "1")
    data, _ = results_file(tmp_path)
    assert data["meta"]["self_grading"] is True
    assert any("self-grading" in line for line in lines)


def test_missing_keys_listed_without_values(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    code, lines, calls = go(tmp_path, "--cases", "1")
    assert code == 2 and calls == []
    text = "\n".join(lines)
    assert "OPENAI_API_KEY" in text and "SECRETVALUE" not in text


def test_no_secret_in_output_or_results(tmp_path):
    _, lines, _ = go(tmp_path, "--cases", "1")
    _, path = results_file(tmp_path)
    assert "SECRETVALUE" not in "\n".join(lines) + path.read_text()


def test_unknown_id_is_an_error(tmp_path):
    from evals.dataset import DatasetError

    with pytest.raises(DatasetError):
        go(tmp_path, "--ids", "nope")


def test_repeat_writes_one_file_each(tmp_path):
    go(tmp_path, "--cases", "1", "--repeat", "2", "--label", "x")
    names = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(names) == 2


def test_prompt_hashes_change_with_prompt():
    a = prompt_hashes()
    with patch("agents.company.SYSTEM_PROMPT", "different"):
        assert prompt_hashes()["company"] != a["company"]
    assert run_mod.PER_CASE_LLM_ESTIMATE > 0
