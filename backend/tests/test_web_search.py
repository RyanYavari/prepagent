"""Tests for the Tavily search service (specs/company-intelligence.md scenario 10)."""

from unittest.mock import MagicMock, patch

import pytest

from models.research import SearchResult
from services.web_search import search_web


def test_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        search_web("Stripe")


def test_maps_tavily_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    client = MagicMock()
    client.search.return_value = {
        "results": [
            {"title": "Stripe", "url": "https://stripe.com", "content": "Payments"},
            {"url": "https://example.com/news"},
        ]
    }
    with patch("services.web_search.TavilyClient", return_value=client) as ctor:
        results = search_web("Stripe", max_results=3)

    ctor.assert_called_once_with(api_key="k")
    client.search.assert_called_once_with(query="Stripe", max_results=3, timeout=12.0)
    assert results == [
        SearchResult(title="Stripe", url="https://stripe.com", content="Payments"),
        SearchResult(url="https://example.com/news"),
    ]


def test_skips_results_without_url(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    client = MagicMock()
    client.search.return_value = {"results": [{"title": "no url"}]}
    with patch("services.web_search.TavilyClient", return_value=client):
        assert search_web("Stripe") == []


def test_tavily_errors_propagate(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    client = MagicMock()
    client.search.side_effect = ConnectionError("boom")
    with (
        patch("services.web_search.TavilyClient", return_value=client),
        pytest.raises(ConnectionError),
    ):
        search_web("Stripe")
