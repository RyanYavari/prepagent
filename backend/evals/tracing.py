"""Optional LangSmith score feedback. A no-op (and no import of the client) unless
LANGSMITH_TRACING is true and an API key is set. Never fails a run."""

import logging
import os

logger = logging.getLogger(__name__)


def enabled() -> bool:
    flag = (
        os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2") or ""
    ).lower()
    key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    return flag in ("true", "1") and bool(key)


def post_feedback(run_id: str | None, scores: dict[str, float | None]) -> None:
    if not run_id or not enabled():
        return
    try:
        from langsmith import Client

        client = Client()
        for metric, value in scores.items():
            if value is not None:
                client.create_feedback(run_id=run_id, key=f"eval.{metric}", score=value)
    except Exception as exc:  # noqa: BLE001 - tracing must never fail an eval
        logger.warning("LangSmith feedback failed: %s", type(exc).__name__)
