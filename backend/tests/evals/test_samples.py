from evals.collect import CollectedCase
from evals.dataset import GoldenCase
from evals.samples import (
    DIAGNOSTIC_WITH_PRIOR,
    build_question,
    build_samples,
    render_full_briefing,
    render_prescriptive,
    render_synthesis_all,
    render_synthesis_facts,
    strip_citations,
)
from models.briefing import BriefingSections
from models.research import SearchResult
from models.retrieval import RetrievedChunk


def sections() -> BriefingSections:
    return BriefingSections.model_validate(
        {
            "company_overview": {
                "summary": "Acme makes anvils.",
                "recent_news": ["Raised funds"],
            },
            "interviewer_profile": {
                "summary": "Pat leads infra.",
                "background": "Ex-X",
            },
            "role_insights": {
                "key_requirements": ["Go [Source: https://a.example/x]"],
                "resume_alignment": ["Built Go services [Resume: Experience]"],
            },
            "talking_points": {
                "talking_points": ["Talk about Go [Resume: Experience]"],
                "suggested_questions": ["What is the roadmap?"],
            },
            "warnings": ["Limited info"],
        }
    )


def collected(interviewer=None, prior=False, resume=True, sec=None) -> CollectedCase:
    case = GoldenCase.model_validate(
        {
            "id": "c",
            "company": "Acme",
            "role": "Engineer",
            "interviewer": interviewer,
            "interviewer_kind": "fictional" if interviewer else None,
            "reference": ["Built Go services", "Wrote tests"],
        }
    )
    return CollectedCase(
        case=case,
        sections=sec or sections(),
        web_company=[SearchResult(title="T", url="https://a", content="anvils")],
        web_interviewer=[SearchResult(title="P", url="https://p", content="Pat")]
        if interviewer
        else [],
        resume_chunks=[
            RetrievedChunk(doc_type="resume", section="experience", content="Go")
        ]
        if resume
        else [],
        prior_chunks=[
            RetrievedChunk(
                doc_type="briefing",
                section="talking_points",
                content="old",
                company="Acme",
            )
        ]
        if prior
        else [],
    )


def test_question_template_has_no_resume_and_optional_interviewer():
    assert build_question("Engineer", "Acme", None) == (
        "Prepare an interview briefing for the Engineer role at Acme."
    )
    assert build_question(None, "Acme", "Pat Q").endswith(
        "at Acme, interviewing with Pat Q."
    )
    assert "unspecified" in build_question(None, "Acme", None)


def test_strip_citations():
    assert strip_citations("Claim one [Source: https://x.y/z]") == "Claim one"
    assert strip_citations("Mine [Resume: Experience] end") == "Mine end"


def test_factual_synthesis_is_role_insights_and_shared_interests_only():
    sec = sections()
    sec.interviewer_profile.shared_interests = ["Both like Go [Resume: Skills]"]
    sec.interviewer_profile.conversation_starters = ["Ask about Go"]
    text = render_synthesis_facts(sec)
    assert "Requirement: Go" in text and "Alignment: Built Go services" in text
    assert "Shared interest: Both like Go" in text
    assert "Talking point" not in text and "Conversation starter" not in text
    assert "roadmap" not in text and "Limited info" not in text
    assert "[Source" not in text and "[Resume" not in text


def test_prescriptive_is_talking_points_stories_starters_only():
    sec = sections()
    sec.talking_points.stories_to_prepare = ["Scaling story"]
    sec.interviewer_profile.conversation_starters = ["Ask about Go"]
    text = render_prescriptive(sec)
    assert "Talking point: Talk about Go" in text
    assert (
        "Story: Scaling story" in text and "Conversation starter: Ask about Go" in text
    )
    assert "Requirement" not in text and "roadmap" not in text
    assert "[Resume" not in text


def test_all_is_the_union_in_v1_shape():
    sec = sections()
    all_text = render_synthesis_all(sec)
    assert "Requirement: Go" in all_text and "Talking point: Talk about Go" in all_text


def test_metric_version_is_2():
    from evals.samples import METRIC_VERSION

    assert METRIC_VERSION == 2


def test_synthesis_samples_use_factual_all_and_prescriptive_definitions():
    s = build_samples(collected())
    facts = s["faithfulness_synthesis"]
    all_ = s["faithfulness_synthesis_all"]
    presc = s["faithfulness_prescriptive"]
    assert "Talking point" not in facts.response and not facts.extract_facts
    assert "Talking point" in all_.response and not all_.extract_facts
    assert presc.extract_facts and "Requirement" not in presc.response
    # all three are scored against the same primary contexts
    assert facts.contexts == all_.contexts == presc.contexts


def test_prescriptive_sample_skipped_when_no_prescriptive_items():
    sec = sections()
    sec.talking_points.talking_points = []
    s = build_samples(collected(sec=sec))
    assert s["faithfulness_prescriptive"] is None
    assert s["faithfulness_synthesis"] is not None


def test_full_briefing_includes_questions_not_warnings():
    text = render_full_briefing(sections())
    assert "roadmap" in text and "Limited info" not in text


def test_no_interviewer_skips_interviewer_faithfulness():
    s = build_samples(collected(interviewer=None))
    assert s["faithfulness_interviewer"] is None
    assert s["faithfulness_company"].contexts == ["T\nanvils"]
    assert s["faithfulness_synthesis"] is not None
    assert "interviewing with" not in s["faithfulness_company"].user_input


def test_interviewer_sample_contexts_and_synthesis_union():
    s = build_samples(collected(interviewer="Pat Q"))
    assert s["faithfulness_interviewer"].contexts == ["P\nPat"]
    assert s["faithfulness_synthesis"].contexts == [
        "T\nanvils",
        "P\nPat",
        "[experience] Go",
    ]


def test_precision_recall_use_resume_chunks_and_reference():
    s = build_samples(collected())
    for name in ("context_precision", "context_recall"):
        assert s[name].contexts == ["[experience] Go"]
        assert s[name].reference == "Built Go services\nWrote tests"


def test_prior_chunks_never_in_scored_contexts_but_feed_diagnostic():
    s = build_samples(collected(prior=True))
    for name, sample in s.items():
        if sample is not None and name != DIAGNOSTIC_WITH_PRIOR:
            assert not any("old" in c for c in sample.contexts), name
    diag = s[DIAGNOSTIC_WITH_PRIOR]
    assert diag is not None and any("old" in c for c in diag.contexts)


def test_no_prior_no_diagnostic():
    assert build_samples(collected()).get(DIAGNOSTIC_WITH_PRIOR) is None


def test_no_resume_skips_resume_metrics_keeps_others():
    s = build_samples(collected(resume=False))
    assert s["context_precision"] is None and s["context_recall"] is None
    assert s["faithfulness_company"] is not None and s["answer_relevancy"] is not None


def test_failed_case_yields_nothing():
    col = collected()
    col.sections, col.error = None, "RuntimeError"
    assert all(v is None for v in build_samples(col).values())


def test_jd_tag_is_stripped_like_other_citations():
    assert strip_citations("Needs Go [JD]") == "Needs Go"
    assert strip_citations("Go [JD] [Resume: Experience]") == "Go"


def test_jd_is_a_scored_context_for_synthesis_groups_only():
    col = collected()
    col.case = col.case.model_copy(update={"job_description": "Requires Go 4 years"})
    out = build_samples(col)
    jd_ctx = "[Job description] Requires Go 4 years"
    for m in (
        "faithfulness_synthesis",
        "faithfulness_synthesis_all",
        "faithfulness_prescriptive",
    ):
        assert jd_ctx in out[m].contexts
    for m in ("faithfulness_company", "context_precision"):
        assert all("Job description" not in c for c in out[m].contexts)


def test_no_jd_leaves_synthesis_contexts_unchanged():
    out = build_samples(collected())
    assert all(
        "Job description" not in c for c in out["faithfulness_synthesis"].contexts
    )


def test_jd_is_not_a_context_for_interviewer_or_company_groups():
    col = collected(interviewer="Pat")
    col.case = col.case.model_copy(update={"job_description": "Requires Go 4 years"})
    out = build_samples(col)
    for m in ("faithfulness_company", "faithfulness_interviewer", "answer_relevancy"):
        assert all("Job description" not in c for c in out[m].contexts)
