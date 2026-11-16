"""Results JSON and terminal summary."""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.budget import CallBudget
from evals.collect import CollectedCase
from evals.score import REPORTED, CaseScores, aggregate, threshold_for

RESULTS_DIR = Path(__file__).parent / "results"


def prompt_hashes() -> dict[str, str]:
    """Short hashes of each agent's system prompt, so a prompt edit shows up as a
    changed field when two runs are compared."""
    from agents import company, interviewer, synthesis

    return {
        name: hashlib.sha256(module.SYSTEM_PROMPT.encode()).hexdigest()[:12]
        for name, module in (
            ("company", company),
            ("interviewer", interviewer),
            ("synthesis", synthesis),
        )
    }


def git_info() -> dict[str, Any]:
    cwd = Path(__file__).parent
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()
        )
        return {"sha": sha, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"sha": None, "dirty": None}


def case_result(col: CollectedCase, scores: CaseScores | None) -> dict[str, Any]:
    scores = scores or CaseScores()
    met = {
        m: (None if v is None else v >= (threshold_for(m) or 0.0))
        for m, v in scores.scores.items()
        if threshold_for(m) is not None
    }
    return {
        "id": col.case.id,
        "tags": col.case.tags,
        "interviewer_kind": col.case.interviewer_kind,
        "error": col.error,
        "scores": scores.scores,
        "score_errors": scores.errors,
        "diagnostics": scores.diagnostics,
        "thresholds_met": met,
        "contexts": {
            "web_company": [r.model_dump() for r in col.web_company],
            "web_interviewer": [r.model_dump() for r in col.web_interviewer],
            "resume": [c.model_dump() for c in col.resume_chunks],
            "prior_count": len(col.prior_chunks),
        },
        "answer": col.sections.model_dump() if col.sections else None,
        "pipeline_warnings": col.pipeline_warnings,
        "elapsed_seconds": col.elapsed_seconds,
    }


def build_results(
    *,
    run_id: str,
    started_at: str,
    label: str | None,
    dataset_version: str,
    dataset_sha256: str,
    cases: list[dict[str, Any]],
    budget: CallBudget,
    truncated: bool,
    config: dict[str, Any],
    git: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "meta": {
            "run_id": run_id,
            "started_at": started_at,
            "label": label,
            "dataset_version": dataset_version,
            "dataset_sha256": dataset_sha256,
            "cases_run": len(cases),
            "truncated": truncated,
            "llm_calls": {
                "pipeline": budget.pipeline,
                "judge": budget.judge,
                "cap": budget.cap,
            },
            "tavily_calls": budget.tavily,
            "web_cache_hits": budget.web_cache_hits,
            "git": git if git is not None else git_info(),
            "config": config,
            "self_grading": config.get("self_grading", False),
        },
        "cases": cases,
        "summary": aggregate([c["scores"] for c in cases]),
    }


def new_run_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def write_results(results: dict[str, Any], directory: Path | None = None) -> Path:
    directory = directory or RESULTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    label = results["meta"].get("label")
    suffix = "-" + re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-") if label else ""
    path = directory / f"{results['meta']['run_id']}{suffix}.json"
    path.write_text(json.dumps(results, indent=2))
    return path


def _fmt(value: float | None, metric: str) -> str:
    if value is None:
        return "  -  "
    limit = threshold_for(metric)
    flag = "" if limit is None or value >= limit else "!"
    return f"{value:.2f}{flag}".rjust(5)


SHORT = {
    "faithfulness_company": "f.comp",
    "faithfulness_interviewer": "f.intv",
    "faithfulness_synthesis": "f.synth",
    "answer_relevancy": "relev",
    "context_precision": "c.prec",
    "context_recall": "c.recall",
    "faithfulness": "f.mean",
}
TABLE_METRICS = tuple(SHORT)


def format_table(results: dict[str, Any]) -> str:
    meta = results["meta"]
    lines: list[str] = []
    if meta.get("self_grading"):
        lines.append(
            "NOTE: judge model equals agent model (self-grading); scores are likely "
            "optimistic."
        )
    if meta.get("truncated"):
        lines.append("NOTE: run truncated by the LLM call cap; results are partial.")
    head = f"{'case':<28}" + "".join(f"{SHORT[m]:>9}" for m in TABLE_METRICS)
    lines += [head, "-" * len(head)]
    for case in results["cases"]:
        row = f"{case['id']:<28}"
        if case.get("error"):
            row += f"  pipeline error: {case['error']}"
        else:
            row += "".join(
                f"{_fmt(case['scores'].get(m), m):>9}" for m in TABLE_METRICS
            )
        lines.append(row)
    lines.append("-" * len(head))
    mean_row = f"{'mean':<28}"
    for m in TABLE_METRICS:
        mean_row += f"{_fmt(results['summary'][m]['mean'], m):>9}"
    lines.append(mean_row)
    lines.append("('!' = below starting threshold; '-' = not scored)")
    calls = meta["llm_calls"]
    lines.append(
        f"LLM calls: {calls['pipeline'] + calls['judge']}/{calls['cap']} "
        f"(pipeline {calls['pipeline']}, judge {calls['judge']}); "
        f"Tavily: {meta['tavily_calls']} (+{meta.get('web_cache_hits', 0)} cached)"
    )
    return "\n".join(lines)


assert set(TABLE_METRICS) <= set(REPORTED)
