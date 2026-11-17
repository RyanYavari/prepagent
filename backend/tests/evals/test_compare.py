import copy
import json

from evals.compare import compare, differing_meta, main


def run(**over):
    base = {
        "meta": {
            "run_id": "20260101T000000Z",
            "started_at": "t",
            "label": None,
            "dataset_version": "v1",
            "dataset_sha256": "aa",
            "cases_run": 2,
            "truncated": False,
            "llm_calls": {"pipeline": 1, "judge": 1, "cap": 9},
            "tavily_calls": 1,
            "git": {"sha": "abc", "dirty": False},
            "config": {
                "agent_model": "m1",
                "judge_model": "j1",
                "prompt_hashes": {"company": "h1", "synthesis": "h2"},
            },
        },
        "cases": [
            {"id": "a", "scores": {"faithfulness": 0.80, "answer_relevancy": 0.90}},
            {"id": "b", "scores": {"faithfulness": 0.70, "answer_relevancy": None}},
        ],
        "summary": {},
    }
    base.update(over)
    return base


def test_deltas_for_shared_cases_and_prompt_hash_diff():
    a = run()
    b = copy.deepcopy(a)
    b["meta"]["run_id"] = "20260102T000000Z"
    b["meta"]["config"]["prompt_hashes"]["synthesis"] = "h9"
    b["cases"][0]["scores"]["faithfulness"] = 0.95
    out = compare(a, b)
    assert "config.prompt_hashes.synthesis: 'h2' -> 'h9'" in out
    assert "+0.15" in out
    assert "20260102T000000Z" in out


def test_identical_meta_message_and_noise_marker():
    a = run()
    b = copy.deepcopy(a)
    b["cases"][0]["scores"]["faithfulness"] = 0.82
    out = compare(a, b)
    assert "differ only in results" in out
    assert "+0.02~" in out


def test_dataset_version_mismatch_warns_and_compares_shared_only():
    a = run()
    b = copy.deepcopy(a)
    b["meta"]["dataset_version"] = "v2"
    b["cases"] = [b["cases"][0], {"id": "c", "scores": {"faithfulness": 0.5}}]
    out = compare(a, b)
    assert "not a like-for-like" in out
    assert "(present in only one run): b, c" in out
    assert "\nc " not in out


def test_null_scores_dash():
    a = run()
    b = copy.deepcopy(a)
    out = compare(a, b)
    row = next(line for line in out.splitlines() if line.startswith("b "))
    assert "-" in row


def test_differing_meta_ignores_identity_fields():
    a = run()
    b = copy.deepcopy(a)
    b["meta"]["run_id"] = "other"
    b["meta"]["llm_calls"]["judge"] = 99
    assert differing_meta(a, b) == []


def test_cli(tmp_path, capsys):
    pa, pb = tmp_path / "a.json", tmp_path / "b.json"
    pa.write_text(json.dumps(run()))
    pb.write_text(json.dumps(run()))
    assert main([str(pa), str(pb)]) == 0
    assert "Delta (B - A)" in capsys.readouterr().out
    assert main([str(pa)]) == 2


def test_compare_shows_both_synthesis_variants_and_flags_metric_version():
    a = run()
    a["meta"]["config"]["metric_version"] = 1
    b = copy.deepcopy(a)
    b["meta"]["config"]["metric_version"] = 2
    a["cases"][0]["scores"]["faithfulness_synthesis"] = 0.5
    b["cases"][0]["scores"]["faithfulness_synthesis"] = 0.9
    b["cases"][0]["scores"]["faithfulness_synthesis_all"] = 0.5
    out = compare(a, b)
    assert "config.metric_version: 1 -> 2" in out
    assert "f.synth" in out and "f.s.all" in out and "f.presc" in out
    assert "+0.40" in out


def test_terminal_table_and_summary_include_new_metrics():
    from evals.report import format_table
    from evals.score import aggregate

    scores = {
        "faithfulness_synthesis": 0.9,
        "faithfulness_synthesis_all": 0.6,
        "faithfulness_prescriptive": 0.8,
    }
    results = {
        "meta": {"llm_calls": {"pipeline": 0, "judge": 0, "cap": 1}, "tavily_calls": 0},
        "cases": [{"id": "a", "scores": scores}],
        "summary": aggregate([scores]),
    }
    table = format_table(results)
    assert "f.s.all" in table and "f.presc" in table
    assert results["summary"]["faithfulness_synthesis_all"]["mean"] == 0.6


def test_judge_change_gets_a_loud_not_comparable_warning():
    a = run()
    b = copy.deepcopy(a)
    b["meta"]["config"]["judge_model"] = "j2"
    out = compare(a, b)
    assert "WARNING: judge model changed" in out and "NOT comparable" in out
    same = compare(a, copy.deepcopy(a))
    assert "WARNING: judge model changed" not in same
