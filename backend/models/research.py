from __future__ import annotations

from pydantic import BaseModel


class SearchResult(BaseModel):
    """A single web search hit returned by the search service."""

    title: str = ""
    url: str
    content: str = ""
