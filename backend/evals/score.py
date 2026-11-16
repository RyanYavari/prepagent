"""RAGAS scoring: judge adapter, per-case scoring, aggregation, thresholds.

ragas 0.4.3 collections metrics need an `InstructorBaseRagasLLM`; the judge here
implements that interface on the project's LangChain ChatAnthropic
(`method="json_schema"`, no temperature: the model rejects it) and charges every
call to the shared budget, which is how the hard cap is enforced.
"""

import asyncio
import logging
import math
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from evals.budget import BudgetExceeded, CallBudget
from evals.collect import CollectedCase
from evals.samples import (
    DIAGNOSTIC_WITH_PRIOR,
    FAITHFULNESS_METRICS,
    METRICS,
    Sample,
    build_samples,
)
from services.net_config import env_float, env_int

logger = logging.getLogger(__name__)

DEFAULT_JUDGE_MODEL = "claude-opus-5-5"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
# Faithfulness verdicts list every claim; 4096 truncated the JSON on a long briefing
# (OutputParserException on the first real run).
JUDGE_MAX_TOKENS = 12000

# Starting baselines (ADR section 5 + /eval skill). Reported, never enforced.
THRESHOLDS = {
    "faithfulness": 0.85,
    "answer_relevancy": 0.80,
    "context_precision": 0.70,
    "context_recall": 0.75,
}

Scorer = Callable[[Sample], Awaitable[float]]


class FactList(BaseModel):
    facts: list[str] = Field(default_factory=list)


EXTRACT_FACTS_PROMPT = """You will be given interview-preparation items: talking points, \
stories to prepare and conversation starters. Rewrite them as standalone factual \
statements about the candidate, the company or the interviewer that the items assert \
or rely on.

Rules:
- Keep only statements of fact (what the candidate did, what the company does or \
announced, what the interviewer did).
- Drop advice and framing: what to say, ask, emphasize or prepare; that something is a \
talking point, story or question; generic story templates such as "cover the situation, \
actions and results".
- Do not add, infer or improve any fact. Use only what the items say.
- Each statement must be self-contained (name the subject; no pronouns like "it").
- If an item contains no facts, produce nothing for it.

Items:
{items}
"""


async def extract_facts(judge: Any, items: str) -> list[str]:
    """Judge call: reduce prescriptive items to the facts they rely on, so the advice
    wording is not scored against context that can never contain it."""
    result = await judge.agenerate(EXTRACT_FACTS_PROMPT.format(items=items), FactList)
    return [f.strip() for f in result.facts if f and f.strip()]


def threshold_for(metric: str) -> float | None:
    if metric.startswith("faithfulness"):
        return THRESHOLDS["faithfulness"]
    return THRESHOLDS.get(metric)


def resolve_judge_model(agent_model: str) -> tuple[str, bool]:
    """(judge model, self_grading). JUDGE_MODEL env, default differs from the
    default agent model. Equal models are allowed but flagged."""
    judge = os.getenv("JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
    return judge, judge == agent_model


def make_judge(model: str, budget: CallBudget) -> Any:
    from langchain_anthropic import ChatAnthropic
    from ragas.llms.base import InstructorBaseRagasLLM

    class _Judge(InstructorBaseRagasLLM):
        def __init__(self) -> None:
            self.model = model
            self._llm = ChatAnthropic(  # type: ignore[call-arg]
                model=model,
                timeout=env_float("LLM_TIMEOUT_SECONDS") * 2,
                max_retries=env_int("LLM_MAX_RETRIES"),
                max_tokens=JUDGE_MAX_TOKENS,
            )

        def _runnable(self, response_model: Any) -> Any:
            return self._llm.with_structured_output(
                response_model, method="json_schema"
            )

        def generate(self, prompt: str, response_model: Any) -> Any:
            budget.charge("judge")
            return self._runnable(response_model).invoke(prompt)

        async def agenerate(self, prompt: str, response_model: Any) -> Any:
            budget.charge("judge")
            return await self._runnable(response_model).ainvoke(prompt)

    return _Judge()


def make_embeddings(model: str) -> Any:
    from openai import OpenAI
    from ragas.embeddings.base import BaseRagasEmbedding

    class _Embeddings(BaseRagasEmbedding):
        def __init__(self) -> None:
            super().__init__()
            self._client = OpenAI(
                timeout=env_float("EMBEDDING_TIMEOUT_SECONDS"),
                max_retries=env_int("EMBEDDING_MAX_RETRIES"),
            )

        def embed_text(self, text: str, **kwargs: Any) -> list[float]:
            resp = self._client.embeddings.create(model=model, input=text)
            return list(resp.data[0].embedding)

        async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
            return await asyncio.to_thread(self.embed_text, text)

    return _Embeddings()


def make_ragas_scorer(
    judge_model: str, embedding_model: str, budget: CallBudget
) -> Scorer:
    """Build the real scorer over ragas 0.4.3 collections metrics."""
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    judge = make_judge(judge_model, budget)
    faithfulness = Faithfulness(llm=judge)
    relevancy = AnswerRelevancy(llm=judge, embeddings=make_embeddings(embedding_model))
    precision = ContextPrecisionWithReference(llm=judge)
    recall = ContextRecall(llm=judge)

    async def score(sample: Sample) -> float:
        if sample.metric.startswith("faithfulness"):
            response = sample.response
            if sample.extract_facts:
                facts = await extract_facts(judge, response)
                if not facts:
                    return float("nan")  # nothing factual to check: null, not 0
                response = "\n".join(facts)
            result = await faithfulness.ascore(
                user_input=sample.user_input,
                response=response,
                retrieved_contexts=sample.contexts,
            )
        elif sample.metric == "answer_relevancy":
            result = await relevancy.ascore(
                user_input=sample.user_input, response=sample.response
            )
        elif sample.metric == "context_precision":
            result = await precision.ascore(
                user_input=sample.user_input,
                reference=sample.reference,
                retrieved_contexts=sample.contexts,
            )
        elif sample.metric == "context_recall":
            result = await recall.ascore(
                user_input=sample.user_input,
                retrieved_contexts=sample.contexts,
                reference=sample.reference,
            )
        else:
            raise ValueError("unknown metric")
        return float(result.value)

    return score


@dataclass
class CaseScores:
    scores: dict[str, float | None] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)  # metric -> exception class
    diagnostics: dict[str, float | int | None] = field(default_factory=dict)


def _clean(value: float) -> float | None:
    return None if value is None or math.isnan(value) else round(float(value), 4)


async def _score_samples(
    samples: dict[str, Sample | None], scorer: Scorer
) -> dict[str, tuple[float | None, str | None]]:
    names = [n for n, s in samples.items() if s is not None]

    async def one(name: str) -> tuple[float | None, str | None]:
        sample = samples[name]
        assert sample is not None
        try:
            value = _clean(await scorer(sample))
        except BudgetExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one metric failing must not end the run
            logger.warning("metric=%s event=error error=%s", name, type(exc).__name__)
            return None, type(exc).__name__
        return (value, None) if value is not None else (None, "NaN")

    results = await asyncio.gather(*(one(n) for n in names), return_exceptions=True)
    for r in results:
        if isinstance(r, BudgetExceeded):
            raise r
    return {
        n: (None, type(r).__name__) if isinstance(r, BaseException) else r
        for n, r in zip(names, results, strict=True)
    }


def score_case(col: CollectedCase, scorer: Scorer) -> CaseScores:
    """Score one collected case. Skipped metrics are None (never 0). Raises only
    BudgetExceeded."""
    samples = build_samples(col)
    results = asyncio.run(_score_samples(samples, scorer))
    out = CaseScores(scores={m: None for m in METRICS})
    for name, (value, err) in results.items():
        if name in out.scores:
            out.scores[name] = value
        if err:
            out.errors[name] = err

    groups = [v for m in FAITHFULNESS_METRICS if (v := out.scores[m]) is not None]
    out.scores["faithfulness"] = round(mean(groups), 4) if groups else None

    out.diagnostics["prior_briefing_chunk_count"] = len(col.prior_chunks)
    with_prior = results.get(DIAGNOSTIC_WITH_PRIOR, (None, None))[0]
    base = out.scores["faithfulness_synthesis"]
    out.diagnostics["faithfulness_synthesis_with_prior"] = with_prior
    out.diagnostics["prior_faithfulness_delta"] = (
        round(with_prior - base, 4)
        if with_prior is not None and base is not None
        else None
    )
    return out


REPORTED = (*METRICS, "faithfulness")


def aggregate(all_scores: list[dict[str, float | None]]) -> dict[str, dict[str, Any]]:
    """Per-metric mean/min/n over non-null scores and the count below threshold."""
    summary: dict[str, dict[str, Any]] = {}
    for metric in REPORTED:
        values = [v for s in all_scores if (v := s.get(metric)) is not None]
        limit = threshold_for(metric)
        summary[metric] = {
            "mean": round(mean(values), 4) if values else None,
            "min": round(min(values), 4) if values else None,
            "n": len(values),
            "threshold": limit,
            "below_threshold_count": (
                sum(1 for v in values if v < limit) if limit is not None else 0
            ),
        }
    return summary
