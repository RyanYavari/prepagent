"""Cache of generated briefings (the pipeline's output) so re-scoring never re-runs
the pipeline. Stores the briefing, the contexts it was scored against and the settings
that produced it. Contains synthetic data and public web content only."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.collect import CollectedCase
from evals.dataset import GoldenCase
from models.briefing import BriefingSections
from models.research import SearchResult
from models.retrieval import RetrievedChunk

DEFAULT_DIR = Path(__file__).parent / "cache" / "briefings"


class BriefingCacheMiss(Exception):
    """No usable cached briefing. The message says what to do; it has no case content."""


def case_hash(case: GoldenCase) -> str:
    return hashlib.sha256(case.model_dump_json().encode()).hexdigest()


class BriefingCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or DEFAULT_DIR

    def _path(self, case_id: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in case_id)
        return self.directory / f"{safe}.json"

    def save(
        self,
        col: CollectedCase,
        *,
        agent_model: str,
        prompt_hashes: dict[str, str],
    ) -> bool:
        """Cache a successful case. Errored cases are never cached."""
        if col.error or col.sections is None:
            return False
        self.directory.mkdir(parents=True, exist_ok=True)
        entry = {
            "case_id": col.case.id,
            "case_hash": case_hash(col.case),
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "agent_model": agent_model,
            "prompt_hashes": prompt_hashes,
            "sections": col.sections.model_dump(),
            "web_company": [r.model_dump() for r in col.web_company],
            "web_interviewer": [r.model_dump() for r in col.web_interviewer],
            "resume_chunks": [c.model_dump() for c in col.resume_chunks],
            "prior_chunks": [c.model_dump() for c in col.prior_chunks],
            "pipeline_warnings": col.pipeline_warnings,
            "elapsed_seconds": col.elapsed_seconds,
        }
        self._path(col.case.id).write_text(json.dumps(entry, indent=1))
        return True

    def load(self, case: GoldenCase) -> tuple[CollectedCase, dict[str, Any]]:
        """The cached CollectedCase and its generation settings
        ({agent_model, prompt_hashes, created_at}). Raises BriefingCacheMiss."""
        path = self._path(case.id)
        if not path.exists():
            raise BriefingCacheMiss(
                f"no cached briefing for {case.id!r}; run once without --rescore"
            )
        try:
            entry = json.loads(path.read_text())
            if entry["case_hash"] != case_hash(case):
                raise BriefingCacheMiss(
                    f"cached briefing for {case.id!r} is stale (the case changed); "
                    "run without --rescore"
                )
            col = CollectedCase(
                case=case,
                sections=BriefingSections.model_validate(entry["sections"]),
                web_company=[
                    SearchResult.model_validate(r) for r in entry["web_company"]
                ],
                web_interviewer=[
                    SearchResult.model_validate(r) for r in entry["web_interviewer"]
                ],
                resume_chunks=[
                    RetrievedChunk.model_validate(c) for c in entry["resume_chunks"]
                ],
                prior_chunks=[
                    RetrievedChunk.model_validate(c) for c in entry["prior_chunks"]
                ],
                pipeline_warnings=list(entry["pipeline_warnings"]),
                elapsed_seconds=float(entry.get("elapsed_seconds", 0.0)),
            )
        except BriefingCacheMiss:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise BriefingCacheMiss(
                f"cached briefing for {case.id!r} is unreadable ({type(exc).__name__}); "
                "run without --rescore"
            ) from None
        meta = {k: entry.get(k) for k in ("agent_model", "prompt_hashes", "created_at")}
        return col, meta
