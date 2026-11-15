"""
Synthesis agent node.

Final fixed-DAG step (ARCHITECTURE_DECISIONS.md section 1): assembles the 4-section
briefing from company research, interviewer research and retrieved context.
Company overview and interviewer summary pass through unchanged; role insights,
talking points and interviewer enrichment are generated, with source attribution
enforced in code (section 6, guardrails 1 and 3).
"""

from typing import Any

from pydantic import BaseModel, Field

from models.briefing import (
    BriefingSections,
    CompanyOverview,
    InterviewerProfile,
    RoleInsights,
    TalkingPoints,
)
from models.retrieval import RetrievalResult, RetrievedChunk

NO_CONTEXT_WARNING = (
    "Not enough research context to generate role insights or talking points."
)


class SynthesisOutput(BaseModel):
    """Fields the LLM generates. Everything else in the briefing is passthrough."""

    key_requirements: list[str] = Field(default_factory=list)
    resume_alignment: list[str] = Field(default_factory=list)
    potential_gaps: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    stories_to_prepare: list[str] = Field(default_factory=list)
    shared_interests: list[str] = Field(default_factory=list)
    conversation_starters: list[str] = Field(default_factory=list)


def _generate(
    *,
    company: str,
    role: str | None,
    company_research: CompanyOverview,
    interviewer: InterviewerProfile,
    resume_chunks: list[RetrievedChunk],
    briefing_chunks: list[RetrievedChunk],
    include_interviewer: bool,
) -> SynthesisOutput:
    raise NotImplementedError


def _has_company_facts(c: CompanyOverview) -> bool:
    return bool(c.summary or c.recent_news or c.tech_stack or c.culture_notes)


def _dedupe(urls: list[str]) -> list[str]:
    return list(dict.fromkeys(urls))


def synthesis_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Build the final BriefingSections from upstream node output.

    State in:  company, optional role, company_research, interviewer_research,
               retrieved_context, optional warnings
    State out: briefing_content (BriefingSections as dict), warnings

    Raises:
        ValueError: company missing/blank
        Exception: LLM failures propagate
    """
    company = str(state.get("company") or "").strip()
    if not company:
        raise ValueError("synthesis_node requires a company in state")
    role = str(state.get("role") or "").strip() or None
    warnings = list(state.get("warnings") or [])

    company_research = CompanyOverview.model_validate(
        state.get("company_research") or {}
    )
    interviewer = InterviewerProfile.model_validate(
        state.get("interviewer_research") or {}
    )
    context = RetrievalResult.model_validate(state.get("retrieved_context") or {})

    # Only enrich an interviewer we actually have facts about.
    include_interviewer = bool(interviewer.summary or interviewer.background)
    has_context = (
        _has_company_facts(company_research)
        or include_interviewer
        or bool(context.resume_chunks)
    )

    if has_context:
        generated = _generate(
            company=company,
            role=role,
            company_research=company_research,
            interviewer=interviewer,
            resume_chunks=context.resume_chunks,
            briefing_chunks=context.briefing_chunks,
            include_interviewer=include_interviewer,
        )
    else:
        generated = SynthesisOutput()
        warnings.append(NO_CONTEXT_WARNING)

    if include_interviewer:
        interviewer.shared_interests = generated.shared_interests
        interviewer.conversation_starters = generated.conversation_starters

    sections = BriefingSections(
        company_overview=company_research,
        interviewer_profile=interviewer,
        role_insights=RoleInsights(
            key_requirements=generated.key_requirements,
            resume_alignment=generated.resume_alignment,
            potential_gaps=generated.potential_gaps,
            # Sources are set in code so the model cannot cite a URL it was not given.
            sources=_dedupe(company_research.sources + interviewer.sources),
        ),
        talking_points=TalkingPoints(
            talking_points=generated.talking_points,
            suggested_questions=generated.suggested_questions,
            stories_to_prepare=generated.stories_to_prepare,
        ),
    )
    return {"briefing_content": sections.model_dump(), "warnings": warnings}
