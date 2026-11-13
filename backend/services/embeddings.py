"""
Resume embedding service for RAG retrieval.

Handles chunking resume text by section headers and storing embeddings in pgvector.
"""

import os
import re
from dataclasses import dataclass
from uuid import UUID

from openai import OpenAI
from supabase import create_client


@dataclass
class ResumeChunk:
    """A single chunk of resume text with metadata."""

    section: str  # 'experience', 'education', 'skills', 'projects', 'other'
    content: str


def chunk_resume(resume_text: str | None) -> list[ResumeChunk]:
    """
    Split resume text into semantic chunks by section headers.

    Chunks are split by common section headers (case-insensitive):
    - Experience
    - Education
    - Skills
    - Projects
    - Summary
    - Certifications

    If no headers are found, returns a single chunk with section='other'.
    If resume_text is None or empty, returns an empty list.

    Args:
        resume_text: Raw resume text, potentially with markdown headers

    Returns:
        List of ResumeChunk objects, each with section type and content
    """
    if not resume_text or not resume_text.strip():
        return []

    # Section header pattern (case-insensitive)
    # Matches: "## Experience", "Experience:", "**Experience**", etc.
    # Use word boundaries to avoid matching "Experienced" as "Experience"
    section_pattern = re.compile(
        r"^#+\s*(Experience|Education|Skills|Projects|Summary|Certifications)\b"
        r"|^(Experience|Education|Skills|Projects|Summary|Certifications)\b\s*:?"
        r"|^\*\*(Experience|Education|Skills|Projects|Summary|Certifications)\*\*",
        re.IGNORECASE | re.MULTILINE,
    )

    # Find all section headers and their positions
    matches = list(section_pattern.finditer(resume_text))

    if not matches:
        # No headers found - treat entire text as single "other" chunk
        return [ResumeChunk(section="other", content=resume_text.strip())]

    chunks: list[ResumeChunk] = []

    for i, match in enumerate(matches):
        # Extract section name (from one of the capture groups)
        section_name = next(g.lower() for g in match.groups() if g is not None)

        # Content starts after the header
        start_pos = match.end()

        # Content ends at the next header (or end of text)
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(resume_text)

        content = resume_text[start_pos:end_pos].strip()

        # Only add non-empty chunks
        if content:
            chunks.append(ResumeChunk(section=section_name, content=content))

    # If all sections were empty, return single "other" chunk
    if not chunks:
        return [ResumeChunk(section="other", content=resume_text.strip())]

    return chunks


def embed_text(text: str) -> list[float]:
    """
    Generate embedding for a text chunk using OpenAI text-embedding-3-small.

    Args:
        text: Text to embed

    Returns:
        List of 1536 floats (embedding vector)

    Raises:
        ValueError: If OPENAI_API_KEY is not set
        openai.OpenAIError: If API call fails
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    client = OpenAI(api_key=api_key)

    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
        encoding_format="float",
    )

    return response.data[0].embedding


def delete_user_resume_embeddings(user_id: str | UUID) -> None:
    """
    Delete all existing resume embeddings for a user.

    Called before re-embedding when resume text is updated.

    Args:
        user_id: User UUID

    Raises:
        Exception: If Supabase delete fails
    """
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )

    supabase.table("resume_embeddings").delete().eq("user_id", str(user_id)).eq(
        "doc_type", "resume"
    ).execute()


def store_resume_embeddings(
    user_id: str | UUID, chunks: list[ResumeChunk], embeddings: list[list[float]]
) -> None:
    """
    Store resume chunks and their embeddings in pgvector.

    Args:
        user_id: User UUID
        chunks: List of resume chunks with section metadata
        embeddings: List of embedding vectors (1536 dims each)

    Raises:
        ValueError: If chunks and embeddings lengths don't match
        Exception: If Supabase insert fails
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have same length"
        )

    if not chunks:
        return  # Nothing to store

    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )

    rows = [
        {
            "user_id": str(user_id),
            "doc_type": "resume",
            "section": chunk.section,
            "content": chunk.content,
            "embedding": embedding,
        }
        for chunk, embedding in zip(chunks, embeddings)
    ]

    supabase.table("resume_embeddings").insert(rows).execute()


def process_resume_embedding(user_id: str | UUID, resume_text: str) -> int:
    """
    Complete pipeline: chunk, embed, and store resume.

    This is the main entry point called from the API endpoint.

    Args:
        user_id: User UUID
        resume_text: Raw resume text

    Returns:
        Number of chunks created and stored

    Raises:
        ValueError: If OPENAI_API_KEY not set
        openai.OpenAIError: If embedding API fails
        Exception: If Supabase operations fail
    """
    # Delete old embeddings
    delete_user_resume_embeddings(user_id)

    # Chunk the resume
    chunks = chunk_resume(resume_text)

    if not chunks:
        return 0

    # Generate embeddings for each chunk
    embeddings = [embed_text(chunk.content) for chunk in chunks]

    # Store in pgvector
    store_resume_embeddings(user_id, chunks, embeddings)

    return len(chunks)
