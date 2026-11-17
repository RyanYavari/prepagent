import sys
from unittest.mock import MagicMock, patch

import pytest

from evals.tracing import enabled, post_feedback


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)


def test_noop_without_env_and_client_not_imported():
    sys.modules.pop("langsmith", None)
    post_feedback("run-1", {"faithfulness": 0.9})
    assert not enabled()
    assert "langsmith" not in sys.modules


def test_posts_non_null_scores_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-key")
    client = MagicMock()
    with patch("langsmith.Client", return_value=client):
        post_feedback("run-1", {"faithfulness": 0.9, "context_recall": None})
    client.create_feedback.assert_called_once_with(
        run_id="run-1", key="eval.faithfulness", score=0.9
    )


def test_feedback_failure_is_swallowed_and_logged_by_class(monkeypatch, caplog):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-key")
    client = MagicMock()
    client.create_feedback.side_effect = RuntimeError("boom ls-key")
    with patch("langsmith.Client", return_value=client):
        post_feedback("run-1", {"faithfulness": 0.9})
    assert "RuntimeError" in caplog.text and "ls-key" not in caplog.text
