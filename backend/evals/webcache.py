"""Record/replay cache for Tavily results, so a prompt-only change can be compared
on identical search results. Holds public web content only (never resume text:
queries are built from company, role and interviewer names)."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from models.research import SearchResult

Mode = Literal["off", "record", "replay"]
DEFAULT_DIR = Path(__file__).parent / "cache"


class WebCacheMiss(Exception):
    """replay mode was asked for a query that was never recorded."""


class WebCache:
    def __init__(self, mode: Mode = "off", directory: Path | None = None) -> None:
        self.mode = mode
        self.directory = directory or DEFAULT_DIR

    def _path(self, query: str, max_results: int) -> Path:
        key = hashlib.sha256(f"{max_results}\n{query}".encode()).hexdigest()
        return self.directory / f"{key}.json"

    def get(self, query: str, max_results: int) -> list[SearchResult] | None:
        """Cached results, or None when the cache is off or (record mode) cold.

        Raises WebCacheMiss on a cold replay.
        """
        if self.mode == "off":
            return None
        path = self._path(query, max_results)
        if path.exists():
            return [
                SearchResult.model_validate(r) for r in json.loads(path.read_text())
            ]
        if self.mode == "replay":
            raise WebCacheMiss(
                "no recorded web results for a query; run with record first"
            )
        return None

    def put(self, query: str, max_results: int, results: list[SearchResult]) -> None:
        if self.mode != "record":
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path(query, max_results).write_text(
            json.dumps([r.model_dump() for r in results])
        )
