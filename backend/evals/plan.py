"""Preflight: estimate LLM calls (per model) and rough cost before any call is made.

Call counts come from the ragas 0.4.3 metric implementations and the pipeline's
structure, using each case's real shape (interviewer, resume chunks, prior briefings).
Dollar figures are a rough guide: they assume a fixed average prompt/response size per
call and the list prices below, so treat them as an order of magnitude.
"""

from dataclasses import dataclass, field

from evals.dataset import GoldenCase
from evals.samples import DIAGNOSTIC_WITH_PRIOR
from services.embeddings import chunk_resume

# $ per million tokens (input, output). First-party list prices; update when they change.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
# Average tokens per call. Judge calls carry the web + resume context; pipeline calls
# carry search results (company/interviewer) or all research (synthesis).
AVG_IN_TOKENS = 6000
AVG_OUT_TOKENS = 900
STRICTNESS = 3  # AnswerRelevancy questions generated per answer
EMBEDDINGS_PER_CASE = STRICTNESS + 1
TAVILY_PER_CASE = 3  # typical (query ladder stops early); max 6


def pipeline_calls(case: GoldenCase) -> int:
    """company summary + synthesis, plus the interviewer summary when there is one."""
    return 2 + (1 if case.interviewer else 0)


def judge_calls(case: GoldenCase, metrics: tuple[str, ...]) -> int:
    chunks = len(chunk_resume(case.resume_text))
    has_prior = any(
        p.company.strip().casefold() == case.company.strip().casefold()
        for p in case.prior_briefings
    )
    per_metric = {
        "faithfulness_company": 2,
        "faithfulness_interviewer": 2 if case.interviewer else 0,
        "faithfulness_synthesis": 2,
        "faithfulness_synthesis_all": 2,
        "faithfulness_prescriptive": 3,  # fact extraction + 2
        "answer_relevancy": STRICTNESS,
        "context_precision": chunks,  # one verdict per retrieved chunk
        "context_recall": 1 if chunks else 0,
        DIAGNOSTIC_WITH_PRIOR: 2 if has_prior else 0,
    }
    return sum(per_metric.get(m, 0) for m in metrics)


def call_cost(model: str, calls: int) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    return calls * (AVG_IN_TOKENS * price[0] + AVG_OUT_TOKENS * price[1]) / 1_000_000


@dataclass
class Plan:
    cases: int
    metrics: tuple[str, ...]
    rescore: bool
    agent_model: str
    judge_model: str
    agent_calls: int
    judge_calls: int
    tavily_calls: int
    embedding_calls: int
    per_model: dict[str, int] = field(default_factory=dict)

    @property
    def total_calls(self) -> int:
        return self.agent_calls + self.judge_calls

    @property
    def cost(self) -> float | None:
        costs = [call_cost(m, n) for m, n in self.per_model.items()]
        return None if any(c is None for c in costs) else sum(c for c in costs if c)


def make_plan(
    cases: list[GoldenCase],
    metrics: tuple[str, ...],
    *,
    rescore: bool,
    agent_model: str,
    judge_model: str,
    web_cache: str = "off",
    repeat: int = 1,
) -> Plan:
    agent = 0 if rescore else sum(pipeline_calls(c) for c in cases) * repeat
    judge = sum(judge_calls(c, metrics) for c in cases) * repeat
    per_model: dict[str, int] = {}
    for model, n in ((agent_model, agent), (judge_model, judge)):
        if n:
            per_model[model] = per_model.get(model, 0) + n
    relevancy = "answer_relevancy" in metrics
    return Plan(
        cases=len(cases),
        metrics=metrics,
        rescore=rescore,
        agent_model=agent_model,
        judge_model=judge_model,
        agent_calls=agent,
        judge_calls=judge,
        tavily_calls=0
        if rescore or web_cache == "replay"
        else len(cases) * TAVILY_PER_CASE * repeat,
        embedding_calls=len(cases) * EMBEDDINGS_PER_CASE * repeat if relevancy else 0,
        per_model=per_model,
    )


def format_plan(plan: Plan, cap: int) -> list[str]:
    lines = [
        f"plan: {plan.cases} case(s){' (rescore: cached briefings, no pipeline)' if plan.rescore else ''}",
        "metrics: " + ", ".join(plan.metrics),
    ]
    for model, n in plan.per_model.items():
        parts = []
        if model == plan.agent_model and plan.agent_calls:
            parts.append(f"{plan.agent_calls} pipeline")
        if model == plan.judge_model and plan.judge_calls:
            parts.append(f"{plan.judge_calls} judge")
        cost = call_cost(model, n)
        price = f" (~${cost:.2f})" if cost is not None else " (price unknown)"
        lines.append(f"  {model}: ~{n} LLM calls [{' + '.join(parts)}]{price}")
    if not plan.per_model:
        lines.append("  no LLM calls")
    cost = plan.cost
    lines.append(
        f"  total ~{plan.total_calls} LLM calls vs cap {cap}"
        + (
            f", ~${cost:.2f} (rough: {AVG_IN_TOKENS} in / {AVG_OUT_TOKENS} out tokens per call)"
            if cost is not None
            else ""
        )
    )
    lines.append(
        f"  Tavily ~{plan.tavily_calls}, OpenAI embeddings ~{plan.embedding_calls}"
    )
    if plan.agent_model == plan.judge_model and not plan.rescore:
        lines.append("  note: judge model equals agent model (self-grading)")
    return lines
