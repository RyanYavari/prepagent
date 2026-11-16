"""Shared LLM construction for the agent nodes.

One place decides the model and the structured-output method so the three
agents cannot drift apart.

claude-sonnet-5-5 rejects forced tool_choice ("tool"/"any"), which is what
LangChain's default `with_structured_output` (method="function_calling")
sends. Native structured outputs (method="json_schema") work on it.
"""

import os
from typing import Literal

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from services.net_config import env_float, env_int

DEFAULT_MODEL = "claude-sonnet-5-5"
STRUCTURED_OUTPUT_METHOD: Literal["function_calling", "json_schema"] = "json_schema"


def get_model_name() -> str:
    return os.getenv("AGENT_MODEL") or DEFAULT_MODEL


def structured_llm(schema: type[BaseModel]):
    """Return a runnable that yields `schema` instances from the shared model."""
    # No temperature: claude-sonnet-5-5 returns 400 "`temperature` is deprecated
    # for this model".
    # Bounded wait + retries (LLM_TIMEOUT_SECONDS / LLM_MAX_RETRIES): the SDK default
    # is a 600s read timeout, which let one stalled call hang a whole briefing.
    llm = ChatAnthropic(  # type: ignore[call-arg]
        model=get_model_name(),
        timeout=env_float("LLM_TIMEOUT_SECONDS"),
        max_retries=env_int("LLM_MAX_RETRIES"),
    )
    return llm.with_structured_output(schema, method=STRUCTURED_OUTPUT_METHOD)
