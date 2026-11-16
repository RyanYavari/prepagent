"""Run the RAGAS eval: `python -m evals.run` from backend/.

Costs real money: it runs the real graph (Claude + Tavily) and scores with an LLM
judge. It refuses to run in CI or under pytest. Never prints or stores API keys or
resume text in logs (resume chunks appear in the results file only because every
golden case is synthetic).
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.budget import BudgetExceeded, CallBudget
from evals.collect import CollectedCase, collect_case
from evals.dataset import DatasetError, GoldenCase, load_dataset
from evals.report import (
    build_results,
    case_result,
    format_table,
    new_run_id,
    prompt_hashes,
    write_results,
)
from evals.samples import METRIC_VERSION
from evals.score import (
    DEFAULT_EMBEDDING_MODEL,
    CaseScores,
    Scorer,
    make_ragas_scorer,
    resolve_judge_model,
    score_case,
)
from evals.tracing import post_feedback
from evals.webcache import WebCache

logger = logging.getLogger(__name__)

DEFAULT_CASES = 3
DEFAULT_MAX_LLM_CALLS = 150
# Pipeline 3 + judge ~15 + synthesis_all 2 + prescriptive 3 + prior diagnostic 2 +
# headroom; recalibrate after real runs.
PER_CASE_LLM_ESTIMATE = 27
PER_CASE_TAVILY_ESTIMATE = 6


class RefusedToRun(Exception):
    pass


def guard_environment(env: Mapping[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    if env.get("CI") or env.get("PYTEST_CURRENT_TEST"):
        raise RefusedToRun("evals never run in CI or under pytest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    sel = p.add_mutually_exclusive_group()
    sel.add_argument(
        "--cases", type=int, default=DEFAULT_CASES, help="run the first N cases"
    )
    sel.add_argument("--ids", help="comma-separated case ids")
    sel.add_argument("--all", action="store_true", help="run every case")
    p.add_argument("--max-llm-calls", type=int, default=DEFAULT_MAX_LLM_CALLS)
    p.add_argument("--force", action="store_true", help="ignore the preflight estimate")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the plan; make no calls",
    )
    p.add_argument("--web-cache", choices=["off", "record", "replay"], default="off")
    p.add_argument(
        "--label", help="short name for this run, added to the results filename"
    )
    p.add_argument("--dataset", type=Path, help="path to a golden JSON file")
    p.add_argument("--results-dir", type=Path)
    p.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run the selection N times (noise estimate)",
    )
    return p.parse_args(argv)


def select_cases(cases: list[GoldenCase], args: argparse.Namespace) -> list[GoldenCase]:
    if args.ids:
        wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
        by_id = {c.id: c for c in cases}
        unknown = [i for i in wanted if i not in by_id]
        if unknown:
            raise DatasetError(f"unknown case id(s): {', '.join(unknown)}")
        return [by_id[i] for i in wanted]
    if args.all:
        return list(cases)
    return cases[: max(args.cases, 0)]


def estimate(n_cases: int, repeat: int = 1) -> dict[str, int]:
    return {
        "llm_calls": n_cases * PER_CASE_LLM_ESTIMATE * repeat,
        "tavily_calls": n_cases * PER_CASE_TAVILY_ESTIMATE * repeat,
    }


def missing_env(web_cache: str) -> list[str]:
    needed = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]
    if web_cache != "replay":
        needed.append("TAVILY_API_KEY")
    return [name for name in needed if not os.getenv(name)]


def run(
    argv: list[str] | None = None,
    *,
    collect: Callable[..., CollectedCase] = collect_case,
    scorer_factory: Callable[[str, str, CallBudget], Scorer] = make_ragas_scorer,
    out: Callable[[str], Any] = print,
) -> int:
    args = parse_args(argv)
    guard_environment()
    dataset = load_dataset(args.dataset)
    selected = select_cases(dataset.cases, args)
    est = estimate(len(selected), args.repeat)

    from agents.llm import get_model_name

    agent_model = get_model_name()
    judge_model, self_grading = resolve_judge_model(agent_model)
    out(
        f"dataset {dataset.version}: {len(selected)} case(s); estimate ~{est['llm_calls']} "
        f"LLM calls, ~{est['tavily_calls']} Tavily calls (cap {args.max_llm_calls})"
    )
    if self_grading:
        out(
            "WARNING: JUDGE_MODEL equals the agent model (self-grading); scores are optimistic."
        )
    if args.dry_run:
        out("dry run: " + ", ".join(c.id for c in selected))
        return 0
    if est["llm_calls"] > args.max_llm_calls and not args.force:
        out(
            f"Estimate {est['llm_calls']} exceeds --max-llm-calls {args.max_llm_calls}. "
            "Lower --cases, raise the cap, or pass --force."
        )
        return 2
    missing = missing_env(args.web_cache)
    if missing:
        out("Missing environment variables: " + ", ".join(missing))
        return 2

    status = 0
    for repeat in range(args.repeat):
        status = max(
            status,
            _run_once(
                args,
                dataset,
                selected,
                agent_model,
                judge_model,
                self_grading,
                repeat,
                collect,
                scorer_factory,
                out,
            ),
        )
    return status


def _run_once(
    args: argparse.Namespace,
    dataset: Any,
    selected: list[GoldenCase],
    agent_model: str,
    judge_model: str,
    self_grading: bool,
    repeat: int,
    collect: Callable[..., CollectedCase],
    scorer_factory: Callable[[str, str, CallBudget], Scorer],
    out: Callable[[str], Any],
) -> int:
    budget = CallBudget(args.max_llm_calls)
    embedding_model = os.getenv("EVAL_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
    cache = WebCache(args.web_cache)
    scorer = scorer_factory(judge_model, embedding_model, budget)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    truncated = False

    for index, case in enumerate(selected, start=1):
        out(f"[{index}/{len(selected)}] {case.id} ...")
        try:
            collected = collect(case, budget, cache)
            scores: CaseScores | None = None
            if collected.error is None:
                scores = score_case(collected, scorer)
                post_feedback(collected.trace_run_id, scores.scores)
            rows.append(case_result(collected, scores))
        except BudgetExceeded:
            truncated = True
            out("LLM call cap reached; stopping with partial results.")
            break

    from importlib.metadata import version

    label = args.label if args.repeat == 1 else f"{args.label or 'run'}-r{repeat + 1}"
    results = build_results(
        run_id=new_run_id(),
        started_at=started_at,
        label=label,
        dataset_version=dataset.version,
        dataset_sha256=dataset.sha256,
        cases=rows,
        budget=budget,
        truncated=truncated,
        config={
            "agent_model": agent_model,
            "judge_model": judge_model,
            "embedding_model": embedding_model,
            "self_grading": self_grading,
            "ragas_version": version("ragas"),
            "metric_version": METRIC_VERSION,
            "prompt_hashes": prompt_hashes(),
            "retrieval_mode": "in_memory",
            "web_cache": args.web_cache,
        },
    )
    path = write_results(results, args.results_dir)
    out(format_table(results))
    out(f"results: {path}")
    return 0


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    try:
        sys.exit(run())
    except (RefusedToRun, DatasetError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
