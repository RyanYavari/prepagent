"""Before/after comparison of two results files: `python -m evals.compare A.json B.json`."""

import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from evals.report import SHORT, TABLE_METRICS

NOISE = 0.05  # judge sampling + web drift; revisit with measured --repeat spread


def _flatten(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out[prefix] = value


def differing_meta(a: dict[str, Any], b: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """Meta fields that differ, ignoring identity/time/usage fields that always do."""
    skip = {
        "run_id",
        "started_at",
        "label",
        "cases_run",
        "llm_calls",
        "tavily_calls",
        "web_cache_hits",
    }
    fa: dict[str, Any] = {}
    fb: dict[str, Any] = {}
    _flatten("", {k: v for k, v in a["meta"].items() if k not in skip}, fa)
    _flatten("", {k: v for k, v in b["meta"].items() if k not in skip}, fb)
    return [
        (k, fa.get(k), fb.get(k))
        for k in sorted(set(fa) | set(fb))
        if fa.get(k) != fb.get(k)
    ]


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def _fmt_delta(d: float | None) -> str:
    if d is None:
        return "   -  "
    mark = "~" if abs(d) < NOISE else " "
    return f"{d:+.2f}{mark}".rjust(6)


def compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    lines: list[str] = []
    ma, mb = a["meta"], b["meta"]
    lines.append(f"A: {ma['run_id']} {ma.get('label') or ''}".rstrip())
    lines.append(f"B: {mb['run_id']} {mb.get('label') or ''}".rstrip())

    if ma["dataset_version"] != mb["dataset_version"]:
        lines.append(
            f"WARNING: dataset versions differ ({ma['dataset_version']} vs "
            f"{mb['dataset_version']}); this is not a like-for-like comparison."
        )
    diffs = differing_meta(a, b)
    if diffs:
        lines.append(
            "Differences between the runs (anything here can explain a score change):"
        )
        lines += [f"  {k}: {va!r} -> {vb!r}" for k, va, vb in diffs]
    else:
        lines.append(
            "Runs differ only in results (same dataset, models, prompts, versions)."
        )
    for side, meta in (("A", ma), ("B", mb)):
        if meta.get("truncated"):
            lines.append(f"WARNING: run {side} was truncated by the call cap.")

    by_a = {c["id"]: c for c in a["cases"]}
    by_b = {c["id"]: c for c in b["cases"]}
    shared = [i for i in by_a if i in by_b]
    only = sorted(set(by_a) ^ set(by_b))
    if only:
        lines.append("Not compared (present in only one run): " + ", ".join(only))
    if not shared:
        lines.append("No shared cases to compare.")
        return "\n".join(lines)

    head = f"{'case':<28}" + "".join(f"{SHORT[m]:>9}" for m in TABLE_METRICS)
    lines += ["", "Delta (B - A) per case:", head, "-" * len(head)]
    for cid in shared:
        sa, sb = by_a[cid]["scores"], by_b[cid]["scores"]
        lines.append(
            f"{cid:<28}"
            + "".join(
                f"{_fmt_delta(_delta(sa.get(m), sb.get(m))):>9}" for m in TABLE_METRICS
            )
        )
    lines.append("-" * len(head))
    mean_row = f"{'mean delta':<28}"
    for m in TABLE_METRICS:
        ds = [
            d
            for cid in shared
            if (d := _delta(by_a[cid]["scores"].get(m), by_b[cid]["scores"].get(m)))
            is not None
        ]
        mean_row += f"{_fmt_delta(mean(ds) if ds else None):>9}"
    lines.append(mean_row)
    lines.append(
        f"('~' = within +/-{NOISE:.2f}, treat as noise until a --repeat run shows a tighter spread)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "usage: python -m evals.compare RESULTS_A.json RESULTS_B.json",
            file=sys.stderr,
        )
        return 2
    a, b = (json.loads(Path(p).read_text()) for p in args)
    print(compare(a, b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
