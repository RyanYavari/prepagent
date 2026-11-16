"""
Web search service backed by Tavily.

Used by the research agents (ARCHITECTURE_DECISIONS.md section 1). Errors from
Tavily propagate so callers never mistake an outage for "no results".
"""

import os

import requests
from tavily import TavilyClient

from models.research import SearchResult
from services.net_config import env_float, env_int, retry_call

# Transient failures worth retrying (DNS/connect problems, timeouts). Tavily's
# TimeoutError is raised when its request times out. API errors (4xx) propagate.
_RETRYABLE = (
    TimeoutError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def search_web(query: str, max_results: int = 5) -> list[SearchResult]:
    """
    Run a Tavily search and return normalized results.

    Raises:
        RuntimeError: TAVILY_API_KEY is not configured
        Exception: Tavily/network failures propagate
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    client = TavilyClient(api_key=api_key)
    response = retry_call(
        lambda: client.search(
            query=query,
            max_results=max_results,
            timeout=env_float("TAVILY_TIMEOUT_SECONDS"),
        ),
        retries=env_int("TAVILY_MAX_RETRIES"),
        retry_on=_RETRYABLE,
        label="tavily search",
    )

    results: list[SearchResult] = []
    for item in response.get("results", []):
        url = item.get("url")
        if not url:
            continue
        results.append(
            SearchResult(
                title=item.get("title") or "",
                url=url,
                content=item.get("content") or "",
            )
        )
    return results
