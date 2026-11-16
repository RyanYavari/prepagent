"""Guards for the shared agent LLM config.

Mocked-LLM node tests cannot catch API-level incompatibilities (a model
rejecting forced tool_choice slipped through them once), so these pin the
model/method choice and `live` tests make one real call per structured schema.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from agents import llm
from agents.synthesis import SynthesisOutput
from models.briefing import CompanyOverview, InterviewerProfile


def test_default_model_when_env_unset(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    assert llm.get_model_name() == llm.DEFAULT_MODEL == "claude-sonnet-5-5"


def test_agent_model_env_overrides_default(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "claude-custom")
    assert llm.get_model_name() == "claude-custom"


def test_empty_agent_model_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "")
    assert llm.get_model_name() == llm.DEFAULT_MODEL


def test_structured_output_avoids_forced_tool_choice():
    """claude-sonnet-5-5 returns 400 for tool_choice type tool/any, which is
    what LangChain's default function_calling method sends."""
    assert llm.STRUCTURED_OUTPUT_METHOD == "json_schema"
    fake = MagicMock()
    with patch("agents.llm.ChatAnthropic", return_value=fake) as ctor:
        llm.structured_llm(CompanyOverview)
    assert ctor.call_args.kwargs["model"] == llm.get_model_name()
    assert "temperature" not in ctor.call_args.kwargs  # deprecated for this model
    fake.with_structured_output.assert_called_once_with(
        CompanyOverview, method="json_schema"
    )


@pytest.mark.parametrize("module", ["company", "interviewer", "synthesis"])
def test_agents_use_shared_helper_not_own_model(module):
    import importlib

    mod = importlib.import_module(f"agents.{module}")
    assert mod.structured_llm is llm.structured_llm
    assert not hasattr(mod, "ChatAnthropic")
    assert not hasattr(mod, "DEFAULT_MODEL")


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_LLM_TESTS") or not os.getenv("ANTHROPIC_API_KEY"),
    reason="live smoke test: set RUN_LIVE_LLM_TESTS=1 and ANTHROPIC_API_KEY",
)
@pytest.mark.parametrize(
    "schema", [CompanyOverview, InterviewerProfile, SynthesisOutput]
)
def test_live_structured_call_accepted_by_api(schema):
    out = llm.structured_llm(schema).invoke("Fill the fields with brief sample text.")
    assert isinstance(out, schema)
