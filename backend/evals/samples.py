"""Turn a collected case into RAGAS samples.

Definitions (specs/ragas-eval-harness.md):
* question: a fixed template, never containing resume text.
* answer: rendered briefing text with `[Source: ...]` / `[Resume: ...]` tags stripped
  and warnings excluded.
* contexts: web results the research nodes used, plus resume chunks. Prior-briefing
  chunks are NOT scored contexts (they are not citable); they only feed a diagnostic.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from evals.collect import CollectedCase
from models.briefing import BriefingSections
from models.research import SearchResult
from models.retrieval import RetrievedChunk

# Metric definitions version. 2 = factual/prescriptive split of synthesis faithfulness
# (specs/ragas-eval-harness.md, "Metric v2"). Recorded in results meta so `compare`
# flags a run made under different definitions.
METRIC_VERSION = 2

# The case-level `faithfulness` mean averages these three factual groups.
FAITHFULNESS_METRICS = (
    "faithfulness_company",
    "faithfulness_interviewer",
    "faithfulness_synthesis",
)
METRICS = (
    *FAITHFULNESS_METRICS,
    "faithfulness_synthesis_all",
    "faithfulness_prescriptive",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)

DIAGNOSTIC_WITH_PRIOR = "faithfulness_synthesis_with_prior"
DIAGNOSTIC_METRICS = (DIAGNOSTIC_WITH_PRIOR,)
ALL_METRICS = (*METRICS, *DIAGNOSTIC_METRICS)
# Opt-in: context recall is ~1.0 by construction (retrieval returns every chunk) and
# the prior-briefing diagnostic is an extra faithfulness pass; both cost judge calls.
OPT_IN_METRICS = ("context_recall", DIAGNOSTIC_WITH_PRIOR)
DEFAULT_METRICS = tuple(m for m in ALL_METRICS if m not in OPT_IN_METRICS)
_GROUPS = {"faithfulness": FAITHFULNESS_METRICS}


def parse_metrics(text: str | None) -> tuple[str, ...]:
    """Parse a --metrics value: comma-separated metric names; `faithfulness` expands
    to the three factual groups. None selects DEFAULT_METRICS. Raises ValueError."""
    if text is None:
        return DEFAULT_METRICS
    chosen: list[str] = []
    for raw in text.split(","):
        name = raw.strip()
        if not name:
            continue
        for m in _GROUPS.get(name, (name,)):
            if m not in ALL_METRICS:
                raise ValueError(
                    f"unknown metric {name!r}; choose from: "
                    + ", ".join([*_GROUPS, *ALL_METRICS])
                )
            if m not in chosen:
                chosen.append(m)
    if not chosen:
        raise ValueError("--metrics selected nothing")
    return tuple(chosen)


_CITATION = re.compile(r"\s*\[(?:Source|Resume):[^\]]*\]")


@dataclass
class Sample:
    metric: str
    user_input: str
    response: str = ""
    contexts: list[str] = field(default_factory=list)
    reference: str = ""
    # True: `response` holds prescriptive items; the scorer first extracts only the
    # factual assertions they rely on, then checks those against `contexts`.
    extract_facts: bool = False


def build_question(role: str | None, company: str, interviewer: str | None) -> str:
    who = f", interviewing with {interviewer}" if interviewer else ""
    return (
        f"Prepare an interview briefing for the {role or 'unspecified'} role "
        f"at {company}{who}."
    )


def strip_citations(text: str) -> str:
    return _CITATION.sub("", text).strip()


def _items(label: str, values: list[str]) -> list[str]:
    return [f"{label}: {strip_citations(v)}" for v in values if strip_citations(v)]


def _line(label: str, value: str) -> list[str]:
    text = strip_citations(value)
    return [f"{label}: {text}"] if text else []


def render_company(s: BriefingSections) -> str:
    c = s.company_overview
    return "\n".join(
        _line("Summary", c.summary)
        + _items("Recent news", c.recent_news)
        + _items("Tech stack", c.tech_stack)
        + _line("Culture", c.culture_notes)
    )


def render_interviewer_facts(s: BriefingSections) -> str:
    i = s.interviewer_profile
    return "\n".join(_line("Summary", i.summary) + _line("Background", i.background))


def render_synthesis_facts(s: BriefingSections) -> str:
    """Factual synthesis fields: role insights and shared interests. These state
    things about the role, company, candidate or interviewer, so they are checked
    as written."""
    r, i = s.role_insights, s.interviewer_profile
    return "\n".join(
        _items("Requirement", r.key_requirements)
        + _items("Alignment", r.resume_alignment)
        + _items("Gap", r.potential_gaps)
        + _items("Shared interest", i.shared_interests)
    )


def render_prescriptive(s: BriefingSections) -> str:
    """Prescriptive fields: advice on what to say, ask or prepare. Their wording is
    never in the context, so only the facts they rely on are scored."""
    t, i = s.talking_points, s.interviewer_profile
    return "\n".join(
        _items("Talking point", t.talking_points)
        + _items("Story", t.stories_to_prepare)
        + _items("Conversation starter", i.conversation_starters)
    )


def render_synthesis_all(s: BriefingSections) -> str:
    """Everything synthesis generates, as written (the v1 `faithfulness_synthesis`)."""
    return "\n".join(
        part for part in (render_synthesis_facts(s), render_prescriptive(s)) if part
    )


def render_full_briefing(s: BriefingSections) -> str:
    """All four sections for answer relevancy (includes suggested questions)."""
    parts = [
        render_company(s),
        render_interviewer_facts(s),
        render_synthesis_all(s),
        "\n".join(_items("Suggested question", s.talking_points.suggested_questions)),
    ]
    return "\n".join(p for p in parts if p)


def _web_text(r: SearchResult) -> str:
    return f"{r.title}\n{r.content}".strip()


def _resume_text(c: RetrievedChunk) -> str:
    return f"[{c.section}] {c.content}"


def build_samples(
    col: CollectedCase, metrics: Iterable[str] | None = None
) -> dict[str, Sample | None]:
    """One entry per metric (plus the diagnostic); None means skipped (score null).
    Only metrics in `metrics` (default: all) are built, so unselected ones cost
    nothing."""
    wanted = set(ALL_METRICS if metrics is None else metrics)
    out = _build_all(col)
    return {k: (v if k in wanted else None) for k, v in out.items()}


def _build_all(col: CollectedCase) -> dict[str, Sample | None]:
    out: dict[str, Sample | None] = {m: None for m in METRICS}
    if col.sections is None or col.error:
        return out
    case, s = col.case, col.sections
    question = build_question(case.role, case.company, case.interviewer)
    web_c = [_web_text(r) for r in col.web_company]
    web_i = [_web_text(r) for r in col.web_interviewer]
    resume = [_resume_text(c) for c in col.resume_chunks]

    company_text = render_company(s)
    if company_text and web_c:
        out["faithfulness_company"] = Sample(
            "faithfulness_company", question, company_text, web_c
        )

    interviewer_text = render_interviewer_facts(s)
    if case.interviewer and interviewer_text and web_i:
        out["faithfulness_interviewer"] = Sample(
            "faithfulness_interviewer", question, interviewer_text, web_i
        )

    primary = web_c + web_i + resume
    facts_text = render_synthesis_facts(s)
    all_text = render_synthesis_all(s)
    presc_text = render_prescriptive(s)
    if facts_text and primary:
        out["faithfulness_synthesis"] = Sample(
            "faithfulness_synthesis", question, facts_text, primary
        )
        if col.prior_chunks:
            prior = [
                f"({c.company}, {c.section}) {c.content}" for c in col.prior_chunks
            ]
            out[DIAGNOSTIC_WITH_PRIOR] = Sample(
                DIAGNOSTIC_WITH_PRIOR, question, facts_text, primary + prior
            )
    if all_text and primary:
        out["faithfulness_synthesis_all"] = Sample(
            "faithfulness_synthesis_all", question, all_text, primary
        )
    if presc_text and primary:
        out["faithfulness_prescriptive"] = Sample(
            "faithfulness_prescriptive",
            question,
            presc_text,
            primary,
            extract_facts=True,
        )

    full = render_full_briefing(s)
    if full:
        out["answer_relevancy"] = Sample("answer_relevancy", question, full)

    if resume:
        reference = "\n".join(case.reference)
        out["context_precision"] = Sample(
            "context_precision", question, contexts=resume, reference=reference
        )
        out["context_recall"] = Sample(
            "context_recall", question, contexts=resume, reference=reference
        )
    return out
