"""Run the RAGAS eval: `python -m evals.run` from backend/.

Costs real money: it runs the real graph (Claude + Tavily) and scores with an LLM
judge. Use --dry-run to see the per-model call estimate first. It refuses to run in
CI or under pytest. Never prints or stores API keys or resume text in logs (resume
chunks appear in the results file only because every golden case is synthetic).
"""

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.briefing_cache import BriefingCache, BriefingCacheMiss
from evals.budget import BudgetExceeded, CallBudget
from evals.collect import CollectedCase, collect_case
from evals.dataset import DatasetError, GoldenCase, load_dataset
from evals.plan import format_plan, make_plan
from evals.report import (
    build_results,
    case_result,
    format_table,
    new_run_id,
    prompt_hashes,
    write_results,
)
from evals.samples import METRIC_VERSION, parse_metrics
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

DEFAULT_LIMIT = 3
DEFAULT_MAX_LLM_CALLS = 150


class RefusedToRun(Exception):
    pass


def guard_environment(env: Mapping[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    if env.get("CI") or env.get("PYTEST_CURRENT_TEST"):
        raise RefusedToRun("evals never run in CI or under pytest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__)
    sel = p.add_mutually_exclusive_group()
    sel.add_argument("--cases", help="comma-separated case ids to run")
    sel.add_argument(
        "--limit",
        type=int,
        help=f"run only the first N cases (default {DEFAULT_LIMIT})",
    )
    sel.add_argument("--all", action="store_true", help="run every case")
    p.add_argument(
        "--metrics",
        help="comma-separated metrics to score (default: everything except "
        "context_recall and the prior-briefing diagnostic, which are opt-in); "
        "`faithfulness` selects the three factual groups",
    )
    p.add_argument(
        "--rescore",
        action="store_true",
        help="reuse cached briefings (no pipeline, no Tavily) and only call the judge",
    )
    p.add_argument(
        "--jd",
        choices=["on", "off"],
        default="on",
        help="`off` drops each case's job_description (same cases, "
        "no JD) so runs with and without it can be compared",
    )
    p.add_argument("--max-llm-calls", type=int, default=DEFAULT_MAX_LLM_CALLS)
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and estimate; make no calls",
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
    if args.cases:
        wanted = [i.strip() for i in args.cases.split(",") if i.strip()]
        by_id = {c.id: c for c in cases}
        unknown = [i for i in wanted if i not in by_id]
        if unknown:
            raise DatasetError(f"unknown case id(s): {', '.join(unknown)}")
        return [by_id[i] for i in wanted]
    if args.all:
        return list(cases)
    limit = DEFAULT_LIMIT if args.limit is None else args.limit
    return cases[: max(limit, 0)]


def apply_jd_mode(cases: list[GoldenCase], mode: str) -> list[GoldenCase]:
    if mode == "off":
        return [c.model_copy(update={"job_description": None}) for c in cases]
    return cases


def missing_env(web_cache: str, rescore: bool, metrics: tuple[str, ...]) -> list[str]:
    needed = ["ANTHROPIC_API_KEY"]  # the judge always needs it
    if "answer_relevancy" in metrics:
        needed.append("OPENAI_API_KEY")  # judge embeddings
    if not rescore and web_cache != "replay":
        needed.append("TAVILY_API_KEY")
    return [name for name in needed if not os.getenv(name)]


def run(
    argv: list[str] | None = None,
    *,
    collect: Callable[..., CollectedCase] = collect_case,
    scorer_factory: Callable[[str, str, CallBudget], Scorer] = make_ragas_scorer,
    briefing_cache: BriefingCache | None = None,
    out: Callable[[str], Any] = print,
) -> int:
    args = parse_args(argv)
    guard_environment()
    metrics = parse_metrics(args.metrics)
    dataset = load_dataset(args.dataset)
    selected = apply_jd_mode(select_cases(dataset.cases, args), args.jd)

    from agents.llm import get_model_name

    agent_model = get_model_name()
    judge_model, self_grading = resolve_judge_model(agent_model)
    plan = make_plan(
        selected,
        metrics,
        rescore=args.rescore,
        agent_model=agent_model,
        judge_model=judge_model,
        web_cache=args.web_cache,
        repeat=args.repeat,
    )
    out(f"dataset {dataset.version}")
    for line in format_plan(plan, args.max_llm_calls):
        out(line)
    if self_grading:
        out(
            "WARNING: JUDGE_MODEL equals the agent model (self-grading); scores are optimistic."
        )
    if args.dry_run:
        out("dry run: " + ", ".join(c.id for c in selected))
        return 0
    if plan.total_calls > args.max_llm_calls:
        out(
            f"Refusing to start: estimated {plan.total_calls} LLM calls exceeds "
            f"--max-llm-calls {args.max_llm_calls}. Run fewer cases or metrics, use "
            "--rescore, or raise the cap."
        )
        return 2
    missing = missing_env(args.web_cache, args.rescore, metrics)
    if missing:
        out("Missing environment variables: " + ", ".join(missing))
        return 2

    cache = briefing_cache or BriefingCache()
    status = 0
    for repeat in range(args.repeat):
        status = max(
            status,
            _run_once(
                args,
                dataset,
                selected,
                metrics,
                agent_model,
                judge_model,
                self_grading,
                repeat,
                collect,
                scorer_factory,
                cache,
                out,
            ),
        )
    return status


def _get_collected(
    case: GoldenCase,
    args: argparse.Namespace,
    budget: CallBudget,
    web_cache: WebCache,
    cache: BriefingCache,
    agent_model: str,
    collect: Callable[..., CollectedCase],
    generated: list[dict[str, Any]],
) -> CollectedCase:
    """Rescore: the cached briefing (no calls). Otherwise run the pipeline and cache
    the result. A cache miss is recorded on the case, not raised."""
    if args.rescore:
        try:
            col, meta = cache.load(case)
        except BriefingCacheMiss as exc:
            logger.warning("case=%s event=cache_miss", case.id)
            col = CollectedCase(case=case, error="BriefingCacheMiss")
            col.pipeline_warnings = [str(exc)]
            return col
        generated.append(meta)
        return col
    col = collect(case, budget, web_cache)
    cache.save(col, agent_model=agent_model, prompt_hashes=prompt_hashes())
    return col


def _generation_config(
    generated: list[dict[str, Any]], agent_model: str, rescore: bool
) -> tuple[str, dict[str, str] | str]:
    """Settings that produced the scored briefings: the current code for a normal
    run, the cache entries for a rescore (so compare stays honest after a prompt edit)."""
    if not rescore:
        return agent_model, prompt_hashes()
    if not generated:
        return "unknown", "unknown"
    models = {g["agent_model"] for g in generated}
    hashes = {tuple(sorted((g["prompt_hashes"] or {}).items())) for g in generated}
    return (
        models.pop() if len(models) == 1 else "mixed",
        dict(hashes.pop()) if len(hashes) == 1 else "mixed",
    )


def _run_once(
    args: argparse.Namespace,
    dataset: Any,
    selected: list[GoldenCase],
    metrics: tuple[str, ...],
    agent_model: str,
    judge_model: str,
    self_grading: bool,
    repeat: int,
    collect: Callable[..., CollectedCase],
    scorer_factory: Callable[[str, str, CallBudget], Scorer],
    cache: BriefingCache,
    out: Callable[[str], Any],
) -> int:
    budget = CallBudget(args.max_llm_calls)
    embedding_model = os.getenv("EVAL_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL
    web_cache = WebCache(args.web_cache)
    scorer = scorer_factory(judge_model, embedding_model, budget)
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    truncated = False

    for index, case in enumerate(selected, start=1):
        out(f"[{index}/{len(selected)}] {case.id} ...")
        try:
            collected = _get_collected(
                case, args, budget, web_cache, cache, agent_model, collect, generated
            )
            scores: CaseScores | None = None
            if collected.error is None:
                scores = score_case(collected, scorer, metrics)
                post_feedback(collected.trace_run_id, scores.scores)
            rows.append(case_result(collected, scores))
        except BudgetExceeded:
            truncated = True
            out("LLM call cap reached; stopping with partial results.")
            break

    from importlib.metadata import version

    label = args.label if args.repeat == 1 else f"{args.label or 'run'}-r{repeat + 1}"
    gen_model, gen_hashes = _generation_config(generated, agent_model, args.rescore)
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
            "agent_model": gen_model,
            "judge_model": judge_model,
            "embedding_model": embedding_model,
            "self_grading": self_grading,
            "ragas_version": version("ragas"),
            "metric_version": METRIC_VERSION,
            "metrics": list(metrics),
            "rescore": args.rescore,
            "prompt_hashes": gen_hashes,
            "retrieval_mode": "in_memory",
            "web_cache": args.web_cache,
            "jd_mode": args.jd,
            "jd_cases": sum(1 for c in selected if c.job_description),
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
    except (RefusedToRun, DatasetError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
