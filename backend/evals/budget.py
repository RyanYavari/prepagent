"""Hard cap on LLM calls, shared by the pipeline and the judge."""

import threading


class BudgetExceeded(Exception):
    """The next LLM call would exceed the configured cap."""


class CallBudget:
    """Counts calls and refuses the one that would pass the cap.

    Thread-safe: the graph runs its two research nodes in parallel threads.
    Tavily calls are counted for reporting but do not draw on the LLM cap.
    """

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self._lock = threading.Lock()
        self.pipeline = 0
        self.judge = 0
        self.tavily = 0
        self.web_cache_hits = 0

    @property
    def llm_total(self) -> int:
        return self.pipeline + self.judge

    def charge(self, kind: str) -> None:
        """Count one LLM call of `kind` ('pipeline' or 'judge') or raise first."""
        with self._lock:
            if self.llm_total + 1 > self.cap:
                raise BudgetExceeded(f"LLM call cap of {self.cap} reached")
            if kind == "pipeline":
                self.pipeline += 1
            elif kind == "judge":
                self.judge += 1
            else:
                raise ValueError(f"unknown call kind {kind!r}")

    def count_tavily(self, *, cached: bool = False) -> None:
        with self._lock:
            if cached:
                self.web_cache_hits += 1
            else:
                self.tavily += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "pipeline": self.pipeline,
                "judge": self.judge,
                "cap": self.cap,
                "tavily": self.tavily,
                "web_cache_hits": self.web_cache_hits,
            }
