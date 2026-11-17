import json
from pathlib import Path

import pytest

from evals.dataset import DatasetError, load_dataset

GOOD = {
    "id": "acme-01",
    "company": "Acme",
    "role": "Engineer",
    "interviewer": None,
    "interviewer_kind": None,
    "resume_text": "Experience\nBuilt services at Northwind Labs.\nSkills\nPython",
    "prior_briefings": [],
    "reference": ["Acme makes anvils"],
    "tags": [],
}


def write(tmp_path: Path, cases: list[dict], version: str = "v1") -> Path:
    path = tmp_path / "golden_test.json"
    path.write_text(json.dumps({"version": version, "cases": cases}))
    return path


def test_valid_load_and_stable_hash(tmp_path):
    path = write(tmp_path, [GOOD])
    a = load_dataset(path)
    b = load_dataset(path)
    assert a.version == "v1"
    assert [c.id for c in a.cases] == ["acme-01"]
    assert a.sha256 == b.sha256 and len(a.sha256) == 64


def test_hash_changes_with_content(tmp_path):
    a = load_dataset(write(tmp_path, [GOOD]))
    b = load_dataset(write(tmp_path, [{**GOOD, "company": "Other"}]))
    assert a.sha256 != b.sha256


@pytest.mark.parametrize(
    "bad_resume",
    [
        "Experience\nmail me at jane.doe@example.com",
        "Experience\ncall 415-555-0123 now",
        "Experience\nsee https://example.com/me",
        "Experience\nsee www.example.com/me",
    ],
)
def test_resume_pii_rejected_without_echo(tmp_path, bad_resume):
    path = write(tmp_path, [{**GOOD, "resume_text": bad_resume}])
    with pytest.raises(DatasetError) as exc:
        load_dataset(path)
    msg = str(exc.value)
    assert "acme-01" in msg
    assert bad_resume not in msg and "jane.doe" not in msg and "555" not in msg


def test_duplicate_id(tmp_path):
    with pytest.raises(DatasetError, match="acme-01"):
        load_dataset(write(tmp_path, [GOOD, GOOD]))


def test_missing_company_names_case(tmp_path):
    bad = {k: v for k, v in GOOD.items() if k != "company"}
    with pytest.raises(DatasetError, match="acme-01"):
        load_dataset(write(tmp_path, [bad]))


def test_empty_reference_rejected(tmp_path):
    with pytest.raises(DatasetError, match="acme-01"):
        load_dataset(write(tmp_path, [{**GOOD, "reference": []}]))


def test_interviewer_kind_must_match_interviewer(tmp_path):
    with pytest.raises(DatasetError, match="acme-01"):
        load_dataset(write(tmp_path, [{**GOOD, "interviewer": "Pat Q"}]))
    with pytest.raises(DatasetError, match="acme-01"):
        load_dataset(write(tmp_path, [{**GOOD, "interviewer_kind": "fictional"}]))


def test_no_resume_allowed(tmp_path):
    ds = load_dataset(write(tmp_path, [{**GOOD, "resume_text": None}]))
    assert ds.cases[0].resume_text is None


def test_malformed_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{nope")
    with pytest.raises(DatasetError):
        load_dataset(p)


def test_shipped_golden_dataset_is_valid():
    ds = load_dataset()
    assert ds.version == "v1"
    assert 8 <= len(ds.cases) <= 10
    kinds = {c.interviewer_kind for c in ds.cases}
    assert {"public_figure", "fictional", None} <= kinds
    assert any(c.resume_text is None for c in ds.cases)
    assert any(c.prior_briefings for c in ds.cases)


def test_golden_v1_is_unchanged_and_has_no_jd():
    from evals.dataset import DEFAULT_PATH

    # the hash recorded in the committed baselines: golden_v1.json must never be edited
    assert (
        load_dataset(DEFAULT_PATH).sha256
        == "01e47019627708f3da077c6f935cbec8408d6fac86c3e459358cf07c66c2b444"
    )
    assert not any(c.job_description for c in load_dataset(DEFAULT_PATH).cases)


def test_committed_baselines_are_scores_only_and_jd_snapshots_match_golden_v2():
    from evals.dataset import DEFAULT_PATH

    base = DEFAULT_PATH.parent / "baselines"
    v2_sha = load_dataset(DEFAULT_PATH.parent / "golden_v2.json").sha256
    for path in base.glob("*.json"):
        data = json.loads(path.read_text())
        for case in data["cases"]:
            assert not {"contexts", "answer", "answers"} & set(case), path.name
    for mode in ("off", "on"):
        snap = json.loads(
            (base / f"golden_v2_sonnet_metric_v2_jd_{mode}.json").read_text()
        )
        assert snap["meta"]["baseline_label"] == "sonnet-judge-metric-v2-jd-spike"
        assert snap["meta"]["cases_run"] == 3 and len(snap["cases"]) == 3
        assert snap["meta"]["config"]["jd_mode"] == mode
        # the snapshot was scored on exactly the golden_v2.json in the repo
        assert snap["meta"]["dataset_sha256"] == v2_sha
