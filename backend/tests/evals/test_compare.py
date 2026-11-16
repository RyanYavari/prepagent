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
