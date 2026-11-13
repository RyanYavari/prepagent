from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """A stored chunk returned by RAG retrieval. Never carries the embedding vector."""

    doc_type: str  # 'resume' | 'briefing'
    section: str
    content: str
    company: str | None = None
    role: str | None = None
    created_at: str | None = None


class RetrievalResult(BaseModel):
    resume_chunks: list[RetrievedChunk] = Field(default_factory=list)
    briefing_chunks: list[RetrievedChunk] = Field(default_factory=list)
