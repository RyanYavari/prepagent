"""
Synthesis agent node.

Final fixed-DAG step (ARCHITECTURE_DECISIONS.md section 1): assembles the 4-section
briefing from company research, interviewer research and retrieved context.
Company overview and interviewer summary pass through unchanged; role insights,
talking points and interviewer enrichment are generated, with source attribution
enforced in code (section 6, guardrails 1 and 3).
"""

import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel, Field

from models.briefing import (
    BriefingSections,
    CompanyOverview,
    InterviewerProfile,
    RoleInsights,
    TalkingPoints,
)
from models.retrieval import RetrievalResult, RetrievedChunk

DEFAULT_MODEL = "claude-sonnet-5-5"
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


SYSTEM_PROMPT = (
    "You write the role-insights and talking-points sections of an interview "
    "briefing, using ONLY the context provided. Every factual claim must cite its "
    "source. For facts about the company or interviewer, end the item with "
    "[Source: <url>] using a URL listed in the context. For references to the "
    "candidate's background, end the item with [Resume: <Section>] naming the "
    "resume section it comes from. If you cannot cite a source, do not include the "
    "claim. Do not connect the candidate's experience to the company's needs unless "
    "both are present in the context. Prior briefings are background only and "
    "cannot be cited. Suggested questions are questions for the candidate to ask "
    "and do not need citations. {interviewer_rule}"
)
INTERVIEWER_RULE_ON = (
    "Also fill shared_interests and conversation_starters from the interviewer "
    "facts and the resume, with citations."
)
INTERVIEWER_RULE_OFF = "Leave shared_interests and conversation_starters empty."


def _format_company(c: CompanyOverview) -> str:
    lines = [f"Summary: {c.summary}"] if c.summary else []
    if c.recent_news:
        lines.append("Recent news: " + "; ".join(c.recent_news))
    if c.tech_stack:
        lines.append("Tech stack: " + ", ".join(c.tech_stack))
    if c.culture_notes:
        lines.append(f"Culture: {c.culture_notes}")
    if c.sources:
        lines.append("Source URLs: " + ", ".join(c.sources))
    return "\n".join(lines) or "(none)"


def _format_interviewer(i: InterviewerProfile) -> str:
    lines = [f"Summary: {i.summary}"] if i.summary else []
    if i.background:
        lines.append(f"Background: {i.background}")
    if i.sources:
        lines.append("Source URLs: " + ", ".join(i.sources))
    return "\n".join(lines)


def _format_chunks(chunks: list[RetrievedChunk], tag: bool) -> str:
    return "\n\n".join(
        (f"[Resume: {c.section}]\n" if tag else f"({c.company}, {c.section})\n")
        + c.content
        for c in chunks
    )


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
    parts = [f"Company: {company}"]
    if role:
        parts.append(f"Role being interviewed for: {role}")
    parts.append(f"Company research:\n{_format_company(company_research)}")
    if include_interviewer:
        parts.append(f"Interviewer research:\n{_format_interviewer(interviewer)}")
    parts.append(
        "Candidate resume sections:\n" + _format_chunks(resume_chunks, True)
        if resume_chunks
        else "Candidate resume sections: (none on file)"
    )
    if briefing_chunks:
        parts.append(
            "Prior briefings for this company (background only, not citable):\n"
            + _format_chunks(briefing_chunks, False)
        )

    system = SYSTEM_PROMPT.format(
        interviewer_rule=INTERVIEWER_RULE_ON
        if include_interviewer
        else INTERVIEWER_RULE_OFF
    )
    llm = ChatAnthropic(  # type: ignore[call-arg]
        model=os.getenv("SYNTHESIS_AGENT_MODEL", DEFAULT_MODEL),
        temperature=0,
    )
    structured = llm.with_structured_output(SynthesisOutput)
    result = structured.invoke([("system", system), ("human", "\n\n".join(parts))])
    return (
        result
        if isinstance(result, SynthesisOutput)
        else SynthesisOutput.model_validate(result)
    )


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
