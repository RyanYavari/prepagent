"""Golden dataset loading and validation.

Cases are synthetic by contract. The loader rejects anything that looks like
contact details in a resume, and its errors name the case id and field only, never
the offending text.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

DEFAULT_PATH = Path(__file__).parent / "golden_v1.json"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"
)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


class DatasetError(Exception):
    """The dataset is malformed. The message never contains case content."""


class PriorBriefing(BaseModel):
    company: str
    role: str | None = None
    section: str
    content: str


class GoldenCase(BaseModel):
    id: str = Field(min_length=1)
    company: str = Field(min_length=1)
    role: str | None = None
    interviewer: str | None = None
    interviewer_kind: Literal["public_figure", "fictional"] | None = None
    resume_text: str | None = None
    job_description: str | None = None  # synthetic JD (specs/job-description-input.md)
    prior_briefings: list[PriorBriefing] = Field(default_factory=list)
    reference: list[str] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("resume_text", "job_description")
    @classmethod
    def _no_contact_details(cls, value: str | None) -> str | None:
        if value and (
            _EMAIL.search(value) or _PHONE.search(value) or _URL.search(value)
        ):
            raise ValueError("text contains an email, phone number or URL")
        return value

    @field_validator("reference")
    @classmethod
    def _reference_not_blank(cls, value: list[str]) -> list[str]:
        if any(not line.strip() for line in value):
            raise ValueError("reference lines must not be blank")
        return value

    def model_post_init(self, _context: object, /) -> None:
        if bool(self.interviewer) != bool(self.interviewer_kind):
            raise ValueError("interviewer and interviewer_kind must be set together")


class Dataset(BaseModel):
    version: str
    sha256: str
    cases: list[GoldenCase]


def _describe(case_id: str, exc: ValidationError) -> str:
    # Locations only: pydantic messages can echo the input value.
    fields = sorted(
        {".".join(str(p) for p in e["loc"]) or "case" for e in exc.errors()}
    )
    return f"case {case_id!r}: invalid field(s): {', '.join(fields)}"


def load_dataset(path: Path | str | None = None) -> Dataset:
    """Load and validate a golden dataset file."""
    target = Path(path) if path else DEFAULT_PATH
    raw = target.read_bytes()
    try:
        data = json.loads(raw)
        version = str(data["version"])
        raw_cases = list(data["cases"])
    except (ValueError, KeyError, TypeError) as exc:
        raise DatasetError(
            f"{target.name}: not a valid dataset file ({type(exc).__name__})"
        ) from None

    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_cases):
        case_id = (
            str(item.get("id", f"#{index}")) if isinstance(item, dict) else f"#{index}"
        )
        try:
            case = GoldenCase.model_validate(item)
        except ValidationError as exc:
            raise DatasetError(_describe(case_id, exc)) from None
        if case.id in seen:
            raise DatasetError(f"case {case.id!r}: duplicate id")
        seen.add(case.id)
        cases.append(case)
    return Dataset(version=version, sha256=hashlib.sha256(raw).hexdigest(), cases=cases)
