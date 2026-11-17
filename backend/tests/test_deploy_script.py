"""deploy/deploy.sh against stubbed docker, git, curl and sleep.

The compose file requires IMAGE_TAG (`${IMAGE_TAG:?...}`), and compose interpolates it
for every subcommand, `ps` included. The stub `docker` refuses a compose call with no
IMAGE_TAG, like the real one, so a call that forgets it shows up here.
"""

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
TAG = "abcdef123456"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

STUBS = {
    "docker": """\
        echo "IMAGE_TAG=${IMAGE_TAG-<unset>} $*" >>"$STUB_LOG"
        case "$1" in
          compose)
            if [ -z "${IMAGE_TAG:-}" ]; then
              echo "required variable IMAGE_TAG is missing a value" >&2
              exit 1
            fi
            case "$*" in *" ps -q api"*) echo cid123 ;; esac
            exit 0 ;;
          inspect) echo "${STUB_HEALTH:-healthy}" ;;
        esac
        exit 0
    """,
    "git": """\
        [ "$1" = "rev-parse" ] && echo abcdef123456
        exit 0
    """,
    "curl": """\
        case "$*" in *http_code*) echo 404 ;; esac
        exit 0
    """,
    "sleep": "exit 0",
}


def _run(tmp_path, *, health="healthy", previous=None):
    repo = tmp_path / "repo"
    (repo / "deploy").mkdir(parents=True)
    (repo / "backend").mkdir()
    shutil.copy(DEPLOY / "deploy.sh", repo / "deploy" / "deploy.sh")
    (repo / "deploy" / "docker-compose.prod.yml").write_text("services: {}\n")
    render = repo / "deploy" / "render-env.sh"
    render.write_text("#!/usr/bin/env bash\nexit 0\n")
    render.chmod(0o755)

    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "deploy.conf").write_text("DOMAIN=example.test\n")
    if previous:
        (etc / "current_tag").write_text(previous + "\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        path = bin_dir / name
        path.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
        path.chmod(0o755)

    log = tmp_path / "calls.log"
    log.write_text("")
    proc = subprocess.run(
        ["bash", str(repo / "deploy" / "deploy.sh"), "--yes"],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "PREPAGENT_ETC": str(etc),
            "STUB_LOG": str(log),
            "STUB_HEALTH": health,
        },
    )
    return proc, etc, log.read_text().splitlines()


def test_a_healthy_container_passes_the_health_check(tmp_path):
    proc, etc, calls = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert f"{TAG} is healthy" in proc.stdout
    assert (etc / "current_tag").read_text().strip() == TAG
    # Every compose call, `ps` included, carries the tag being deployed.
    compose = [c for c in calls if " compose " in c]
    assert compose and all(c.startswith(f"IMAGE_TAG={TAG} ") for c in compose)


def test_an_unhealthy_container_fails_and_restarts_the_previous_tag(tmp_path):
    proc, etc, calls = _run(tmp_path, health="unhealthy", previous="oldtag000000")
    assert proc.returncode == 1
    assert "failed its health/smoke check" in proc.stderr
    assert (etc / "current_tag").read_text().strip() == "oldtag000000"
    ups = [c for c in calls if " compose " in c and c.rstrip().endswith("up -d")]
    assert ups[-1].startswith("IMAGE_TAG=oldtag000000 ")
