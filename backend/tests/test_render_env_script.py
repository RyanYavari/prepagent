"""deploy/render-env.sh against a stubbed `aws` that paginates like the real CLI.

`aws ssm get-parameters-by-path` returns at most 10 parameters per page, and with
`--query` the CLI applies the query to every page and prints one result per page. So
`length(Parameters)` for 12 parameters prints "10" then "2" on separate lines, and the
rendering query prints two JSON arrays back to back.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "render-env.sh"
PAGE_SIZE = 10

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="needs bash and jq",
)

STUB = textwrap.dedent(
    """\
    #!/usr/bin/env bash
    # Fake aws: reads PARAMS_FILE, serves it in pages of 10 like the real CLI.
    echo "$*" >>"$STUB_LOG"
    python3 - "$@" <<'PY'
    import json, os, sys
    params = json.load(open(os.environ["PARAMS_FILE"]))
    pages = [params[i:i + 10] for i in range(0, len(params), 10)]
    args = " ".join(sys.argv[1:])
    if "length(Parameters)" in args:
        for page in pages:
            print(len(page))
    else:
        for page in pages:
            print(json.dumps([{"n": p["Name"], "v": p["Value"]} for p in page]))
    PY
    """
)


def _run(tmp_path, params, extra_env=None):
    (tmp_path / "bin").mkdir()
    stub = tmp_path / "bin" / "aws"
    stub.write_text(STUB)
    stub.chmod(0o755)
    params_file = tmp_path / "params.json"
    params_file.write_text(json.dumps(params))
    out = tmp_path / "backend.env"
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "PARAMS_FILE": str(params_file),
        "STUB_LOG": str(tmp_path / "calls.log"),
        **(extra_env or {}),
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), "/prepagent/prod/", str(out)],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    return proc, out


def _params(n, **override):
    items = [
        {"Name": f"/prepagent/prod/VAR_{i:02d}", "Value": f"value{i}"} for i in range(n)
    ]
    for index, value in override.items():
        items[int(index)]["Value"] = value
    return items


def test_two_pages_are_summed_not_compared_as_a_list(tmp_path):
    proc, out = _run(tmp_path, _params(12))
    assert proc.returncode == 0, proc.stderr
    assert "wrote 12 variable(s)" in proc.stdout
    assert len(out.read_text().splitlines()) == 12


def test_exactly_one_full_page_and_a_single_short_page_still_work(tmp_path):
    for count in (10, 3):
        sub = tmp_path / str(count)
        sub.mkdir()
        proc, out = _run(sub, _params(count))
        assert proc.returncode == 0, proc.stderr
        assert len(out.read_text().splitlines()) == count


def test_a_real_mismatch_still_fails_and_installs_nothing(tmp_path):
    # A value with a newline renders 13 lines for 12 parameters.
    proc, out = _run(tmp_path, _params(12, **{"3": "line1\nline2"}))
    assert proc.returncode == 1
    assert "expected 12 parameter(s)" in proc.stderr
    assert "rendered 13 line(s)" in proc.stderr
    assert not out.exists()
    assert "line1" not in proc.stdout + proc.stderr


def test_empty_prefix_still_fails(tmp_path):
    proc, out = _run(tmp_path, [])
    assert proc.returncode == 1
    assert not out.exists()


def test_region_is_passed_to_every_aws_call(tmp_path):
    proc, _ = _run(tmp_path, _params(12), {"AWS_REGION": "us-east-2"})
    assert proc.returncode == 0, proc.stderr
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert len(calls) == 2 and all("--region us-east-2" in c for c in calls)
