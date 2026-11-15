"""Tests for synthesis_node (specs/synthesis-agent.md)."""

from unittest.mock import MagicMock, patch

import pytest

from agents.synthesis import SynthesisOutput, synthesis_node
from models.briefing import BriefingSections

COMPANY = "Stripe"
URL_C = "https://stripe.com/about"
URL_I = "https://blog.example.com/jane"

COMPANY_RESEARCH = {
    "summary": "Payments company",
    "recent_news": ["Raised funding"],
    "tech_stack": ["Ruby"],
    "culture_notes": "Writing culture",
    "sources": [URL_C],
}
INTERVIEWER_RESEARCH = {
    "summary": "Staff engineer",
    "background": "Ex-Google",
    "shared_interests": [],
    "conversation_starters": [],
    "sources": [URL_I],
}
CONTEXT = {
    "resume_chunks": [
        {"doc_type": "resume", "section": "Experience", "content": "Built APIs"},
    ],
    "briefing_chunks": [],
}


def _state(**extra):
    base = {
        "company": COMPANY,
        "role": "Backend Engineer",
        "company_research": COMPANY_RESEARCH,
        "interviewer_research": INTERVIEWER_RESEARCH,
        "retrieved_context": CONTEXT,
    }
    base.update(extra)
    return base


def _output(**kw):
    defaults = {
        "key_requirements": [f"Scale APIs [Source: {URL_C}]"],
        "resume_alignment": ["Built APIs [Resume: Experience]"],
        "potential_gaps": [f"No Ruby [Source: {URL_C}]"],
        "talking_points": ["Payments APIs [Resume: Experience]"],
        "suggested_questions": ["How are services owned?"],
        "stories_to_prepare": ["API migration [Resume: Experience]"],
        "shared_interests": [f"Distributed systems [Source: {URL_I}]"],
        "conversation_starters": [f"Ask about the blog [Source: {URL_I}]"],
    }
    defaults.update(kw)
    return SynthesisOutput(**defaults)


def _run(state, output=None):
    generate = MagicMock(return_value=output or _output())
    with patch("agents.synthesis._generate", generate):
        out = synthesis_node(state)
    return out, generate


def test_happy_path_assembles_sections():  # scenario 1
    out, generate = _run(_state(warnings=[]))
    content = BriefingSections.model_validate(out["briefing_content"])

    assert generate.call_count == 1
    assert content.company_overview.summary == "Payments company"
    assert content.company_overview.recent_news == ["Raised funding"]
    assert content.interviewer_profile.summary == "Staff engineer"
    assert content.interviewer_profile.background == "Ex-Google"
    assert content.interviewer_profile.sources == [URL_I]
    assert content.interviewer_profile.shared_interests
    assert content.interviewer_profile.conversation_starters
    assert content.role_insights.key_requirements
    assert content.talking_points.talking_points
    assert out["warnings"] == []


def test_empty_interviewer_profile_stays_empty():  # scenario 9
    state = _state(interviewer_research={})
    out, generate = _run(state)
    profile = out["briefing_content"]["interviewer_profile"]

    assert generate.call_args.kwargs["include_interviewer"] is False
    assert profile["shared_interests"] == []
    assert profile["conversation_starters"] == []
    assert profile["summary"] == ""
    assert out["warnings"] == []


def test_interviewer_with_only_background_is_enriched():
    state = _state(interviewer_research={"background": "Ex-Google", "sources": []})
    _, generate = _run(state)
    assert generate.call_args.kwargs["include_interviewer"] is True


def test_no_usable_context_skips_llm_and_warns():  # scenario 11
    state = {"company": COMPANY}
    out, generate = _run(state)

    assert generate.call_count == 0
    content = BriefingSections.model_validate(out["briefing_content"])
    assert content.role_insights.key_requirements == []
    assert content.talking_points.talking_points == []
    assert any("Not enough research context" in w for w in out["warnings"])


def test_role_insights_sources_set_in_code():  # scenario 12
    state = _state(
        company_research={**COMPANY_RESEARCH, "sources": [URL_C, URL_I]},
    )
    out, _ = _run(state)
    # company urls first, then interviewer urls, de-duplicated, order preserved
    assert out["briefing_content"]["role_insights"]["sources"] == [URL_C, URL_I]


@pytest.mark.parametrize("company", [None, "", "   "])
def test_missing_company_raises_before_llm(company):  # scenario 13
    generate = MagicMock()
    with patch("agents.synthesis._generate", generate), pytest.raises(ValueError):
        synthesis_node(_state(company=company))
    generate.assert_not_called()


def test_existing_warnings_preserved():  # scenario 15
    out, _ = _run({"company": COMPANY, "warnings": ["a", "b"]})
    assert out["warnings"][:2] == ["a", "b"]
    assert len(out["warnings"]) == 3


@pytest.mark.parametrize(
    "missing", ["company_research", "interviewer_research", "retrieved_context"]
)
def test_missing_upstream_keys_tolerated(missing):  # scenario 16
    state = _state()
    del state[missing]
    out, _ = _run(state)
    BriefingSections.model_validate(out["briefing_content"])


# --- Slice 2: LLM generation + attribution prompt ---


def _run_with_llm(state, llm_output=None, side_effect=None):
    structured = MagicMock()
    if side_effect:
        structured.invoke.side_effect = side_effect
    else:
        structured.invoke.return_value = llm_output or _output()
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    with patch("agents.synthesis.ChatAnthropic", return_value=llm) as ctor:
        out = synthesis_node(state)
    return out, llm, structured, ctor


def _prompt_text(structured):
    messages = structured.invoke.call_args.args[0]
    return {m[0]: m[1] for m in messages}  # {"system": ..., "human": ...}


def test_llm_wired_with_structured_output():
    out, llm, structured, ctor = _run_with_llm(_state())
    llm.with_structured_output.assert_called_once_with(SynthesisOutput)
    structured.invoke.assert_called_once()
    assert ctor.call_args.kwargs["temperature"] == 0
    assert out["briefing_content"]["talking_points"]["talking_points"]


def test_model_overridable_via_env(monkeypatch):
    monkeypatch.setenv("SYNTHESIS_AGENT_MODEL", "claude-custom")
    _, _, _, ctor = _run_with_llm(_state())
    assert ctor.call_args.kwargs["model"] == "claude-custom"


def test_system_prompt_requires_source_attribution():  # scenario 2
    _, _, structured, _ = _run_with_llm(_state())
    system = _prompt_text(structured)["system"]
    assert "cite" in system.lower()
    assert "[Source:" in system and "[Resume:" in system
    assert "do not include" in system.lower()


def test_human_message_contains_context_with_sources():  # scenario 2
    state = _state(
        retrieved_context={
            "resume_chunks": [
                {"doc_type": "resume", "section": "Experience", "content": "Built APIs"}
            ],
            "briefing_chunks": [
                {
                    "doc_type": "briefing",
                    "section": "talking_points",
                    "content": "Old Stripe point",
                    "company": "Stripe",
                }
            ],
        }
    )
    _, _, structured, _ = _run_with_llm(state)
    human = _prompt_text(structured)["human"]

    assert COMPANY in human and "Backend Engineer" in human
    assert "Payments company" in human and "Raised funding" in human
    assert "Ruby" in human and "Writing culture" in human
    assert URL_C in human and URL_I in human
    assert "Staff engineer" in human and "Ex-Google" in human
    assert "[Resume: Experience]" in human and "Built APIs" in human
    assert "Old Stripe point" in human


def test_interviewer_section_omitted_from_prompt_when_empty():
    _, _, structured, _ = _run_with_llm(_state(interviewer_research={}))
    human = _prompt_text(structured)["human"]
    assert "Staff engineer" not in human
    system = _prompt_text(structured)["system"]
    assert "Leave shared_interests and conversation_starters empty" in system


def test_llm_failure_propagates():  # scenario 14
    with pytest.raises(RuntimeError, match="boom"):
        _run_with_llm(_state(), side_effect=RuntimeError("boom"))


def test_dict_result_from_llm_is_validated():
    out, *_ = _run_with_llm(_state(), llm_output=_output().model_dump())
    assert out["briefing_content"]["role_insights"]["key_requirements"]
