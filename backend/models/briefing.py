from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from models.text_safety import clean_long_text, validate_safe_field


class BriefingStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


# --- Request models ---


class BriefingCreate(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    interviewer: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    interview_date: str | None = Field(
        default=None, description="Date of the interview, e.g. 2025-06-15"
    )
    resume_text: str | None = Field(
        default=None,
        max_length=50_000,
        description="Raw resume text to use for this briefing.",
    )
    job_description: str | None = Field(
        default=None,
        max_length=12_000,
        description=(
            "Optional pasted job description. Request-scoped: used for this "
            "briefing's generation and never stored or logged."
        ),
    )

    @field_validator("company", "interviewer", "role")
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        return validate_safe_field(value)

    @field_validator("job_description")
    @classmethod
    def _clean_job_description(cls, value: str | None) -> str | None:
        return clean_long_text(value)


# --- Section models ---


class CompanyOverview(BaseModel):
    summary: str = ""
    recent_news: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    culture_notes: str = ""
    sources: list[str] = Field(default_factory=list)


class InterviewerProfile(BaseModel):
    summary: str = ""
    background: str = ""
    shared_interests: list[str] = Field(default_factory=list)
    conversation_starters: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class RoleInsights(BaseModel):
    key_requirements: list[str] = Field(default_factory=list)
    resume_alignment: list[str] = Field(default_factory=list)
    potential_gaps: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class TalkingPoints(BaseModel):
    talking_points: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)
    stories_to_prepare: list[str] = Field(default_factory=list)


class BriefingSections(BaseModel):
    company_overview: CompanyOverview = Field(default_factory=CompanyOverview)
    interviewer_profile: InterviewerProfile = Field(default_factory=InterviewerProfile)
    role_insights: RoleInsights = Field(default_factory=RoleInsights)
    talking_points: TalkingPoints = Field(default_factory=TalkingPoints)
    warnings: list[str] = Field(default_factory=list)


# --- Response models ---


class BriefingResponse(BaseModel):
    id: str
    user_id: str
    company: str
    interviewer: str | None = None
    role: str | None = None
    interview_date: str | None = None
    status: BriefingStatus
    content: BriefingSections | None = None
    failure_reason: str | None = None
    created_at: str


class BriefingListItem(BaseModel):
    id: str
    company: str
    interviewer: str | None = None
    role: str | None = None
    status: BriefingStatus
    created_at: str


class BriefingListResponse(BaseModel):
    briefings: list[BriefingListItem]
    total: int
