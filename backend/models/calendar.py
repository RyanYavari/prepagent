from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.text_safety import validate_safe_field


class CalendarConnectURL(BaseModel):
    url: str


class CalendarCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=256)


class CalendarStatus(BaseModel):
    connected: bool
    status: str | None = None  # "active" | "revoked" | None when not connected
    last_synced_at: str | None = None


class SyncResponse(BaseModel):
    events_scanned: int = 0
    candidates: int = 0
    briefings_created: int = 0
    needs_confirmation: int = 0
    ignored: int = 0
    errors: int = 0
    truncated: bool = False
    skipped: str | None = None


class DetectionItem(BaseModel):
    id: str
    status: str
    event_start: str | None = None
    event_title: str | None = None
    confidence: float | None = None
    company: str | None = None
    role: str | None = None
    interviewer_names: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class DetectionListResponse(BaseModel):
    detections: list[DetectionItem]


class DetectionConfirmRequest(BaseModel):
    """Optional edits made in the confirmation UI. Same limits as /prep/new."""

    model_config = ConfigDict(extra="forbid")

    company: str | None = Field(None, min_length=1, max_length=200)
    role: str | None = Field(None, max_length=200)
    interviewer: str | None = Field(None, max_length=200)

    @field_validator("company", "role", "interviewer")
    @classmethod
    def _safe_text(cls, value: str | None) -> str | None:
        return validate_safe_field(value)


class DetectionConfirmResponse(BaseModel):
    briefing_id: str
    status: str = "briefing_created"
