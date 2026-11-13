"""Tests for resume chunking and embedding service."""

import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from services.embeddings import (
    ResumeChunk,
    chunk_resume,
    delete_user_resume_embeddings,
    embed_text,
    process_resume_embedding,
    store_resume_embeddings,
)


class TestResumeChunking:
    """Test cases for resume text chunking."""

    def test_multi_section_resume_with_markdown_headers(self):
        """Test chunking a resume with markdown ## headers."""
        resume_text = """
## Experience

Senior Engineer at Acme Corp
Built distributed systems

## Education

BS Computer Science, MIT
Graduated 2020

## Skills

Python, Go, TypeScript
"""
        chunks = chunk_resume(resume_text)

        assert len(chunks) == 3
        assert chunks[0].section == "experience"
        assert "Acme Corp" in chunks[0].content
        assert chunks[1].section == "education"
        assert "MIT" in chunks[1].content
        assert chunks[2].section == "skills"
        assert "Python" in chunks[2].content

    def test_section_headers_with_colons(self):
        """Test chunking with colon-style headers."""
        resume_text = """
Experience:
Engineer at StartupXYZ

Education:
MS in AI, Stanford
"""
        chunks = chunk_resume(resume_text)

        assert len(chunks) == 2
        assert chunks[0].section == "experience"
        assert "StartupXYZ" in chunks[0].content
        assert chunks[1].section == "education"
        assert "Stanford" in chunks[1].content

    def test_section_headers_with_bold_markdown(self):
        """Test chunking with **bold** headers."""
        resume_text = """
**Summary**
Experienced software engineer

**Projects**
Built an AI agent system
"""
        chunks = chunk_resume(resume_text)

        assert len(chunks) == 2
        assert chunks[0].section == "summary"
        assert "software engineer" in chunks[0].content
        assert chunks[1].section == "projects"
        assert "AI agent" in chunks[1].content

    def test_case_insensitive_headers(self):
        """Test that section headers are case-insensitive."""
        resume_text = """
## EXPERIENCE
Senior Role

## education
University Degree
"""
        chunks = chunk_resume(resume_text)

        assert len(chunks) == 2
        assert chunks[0].section == "experience"
        assert chunks[1].section == "education"

    def test_no_headers_returns_single_other_chunk(self):
        """Test that text without headers becomes a single 'other' chunk."""
        resume_text = "Just a random paragraph with no section markers."

        chunks = chunk_resume(resume_text)

        assert len(chunks) == 1
        assert chunks[0].section == "other"
        assert chunks[0].content == resume_text

    def test_empty_string_returns_empty_list(self):
        """Test that empty string returns no chunks."""
        assert chunk_resume("") == []
        assert chunk_resume("   ") == []

    def test_none_input_returns_empty_list(self):
        """Test that None input returns no chunks."""
        assert chunk_resume(None) == []

    def test_empty_sections_are_filtered_out(self):
        """Test that sections with no content are not included."""
        resume_text = """
## Experience

## Education
BS Degree

## Skills
"""
        chunks = chunk_resume(resume_text)

        # Only Education has content, others are empty
        assert len(chunks) == 1
        assert chunks[0].section == "education"
        assert "BS Degree" in chunks[0].content

    def test_all_supported_section_types(self):
        """Test all recognized section types."""
        resume_text = """
## Experience
Job 1

## Education
Degree 1

## Skills
Skill 1

## Projects
Project 1

## Summary
Brief summary

## Certifications
Cert 1
"""
        chunks = chunk_resume(resume_text)

        assert len(chunks) == 6
        section_names = {chunk.section for chunk in chunks}
        assert section_names == {
            "experience",
            "education",
            "skills",
            "projects",
            "summary",
            "certifications",
        }

    def test_mixed_header_styles(self):
        """Test a resume with mixed header styles."""
        resume_text = """
## Experience
Job at Company A

**Education**
University X

Skills:
Python, Go
"""
        chunks = chunk_resume(resume_text)

        assert len(chunks) == 3
        assert chunks[0].section == "experience"
        assert chunks[1].section == "education"
        assert chunks[2].section == "skills"


class TestEmbedding:
    """Test cases for OpenAI embedding integration."""

    @patch("services.embeddings.OpenAI")
    def test_embed_text_returns_1536_dimensional_vector(self, mock_openai_class):
        """Test that embed_text returns correct dimension vector."""
        # Mock OpenAI response
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_client.embeddings.create.return_value = mock_response

        # Set API key
        os.environ["OPENAI_API_KEY"] = "test-key"

        embedding = embed_text("Test text")

        assert len(embedding) == 1536
        assert all(isinstance(x, float) for x in embedding)
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input="Test text",
            encoding_format="float",
        )

    def test_embed_text_raises_error_if_no_api_key(self):
        """Test that embed_text raises ValueError if OPENAI_API_KEY not set."""
        # Temporarily unset API key
        original_key = os.environ.get("OPENAI_API_KEY")
        if "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]

        try:
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                embed_text("Test text")
        finally:
            # Restore original key
            if original_key:
                os.environ["OPENAI_API_KEY"] = original_key


class TestSupabaseStorage:
    """Test cases for pgvector storage operations."""

    @patch("services.embeddings.create_client")
    def test_delete_user_resume_embeddings(self, mock_create_client):
        """Test deleting user's resume embeddings."""
        mock_supabase = MagicMock()
        mock_create_client.return_value = mock_supabase

        user_id = uuid4()
        delete_user_resume_embeddings(user_id)

        # Verify delete was called with correct filters
        mock_supabase.table.assert_called_once_with("resume_embeddings")
        mock_supabase.table().delete().eq.assert_called()

    @patch("services.embeddings.create_client")
    def test_store_resume_embeddings(self, mock_create_client):
        """Test storing resume chunks with embeddings."""
        mock_supabase = MagicMock()
        mock_create_client.return_value = mock_supabase

        user_id = uuid4()
        chunks = [
            ResumeChunk(section="experience", content="Job at Company A"),
            ResumeChunk(section="education", content="BS Degree"),
        ]
        embeddings = [[0.1] * 1536, [0.2] * 1536]

        store_resume_embeddings(user_id, chunks, embeddings)

        # Verify insert was called
        mock_supabase.table.assert_called_once_with("resume_embeddings")
        insert_call = mock_supabase.table().insert
        assert insert_call.called

        # Verify inserted data structure
        inserted_rows = insert_call.call_args[0][0]
        assert len(inserted_rows) == 2
        assert inserted_rows[0]["user_id"] == str(user_id)
        assert inserted_rows[0]["doc_type"] == "resume"
        assert inserted_rows[0]["section"] == "experience"
        assert inserted_rows[0]["content"] == "Job at Company A"
        assert inserted_rows[0]["embedding"] == [0.1] * 1536

    @patch("services.embeddings.create_client")
    def test_store_resume_embeddings_raises_if_length_mismatch(
        self, mock_create_client
    ):
        """Test that store raises ValueError if chunks/embeddings length mismatch."""
        user_id = uuid4()
        chunks = [ResumeChunk(section="experience", content="Job")]
        embeddings = [[0.1] * 1536, [0.2] * 1536]  # 2 embeddings for 1 chunk

        with pytest.raises(ValueError, match="must have same length"):
            store_resume_embeddings(user_id, chunks, embeddings)

    @patch("services.embeddings.create_client")
    def test_store_resume_embeddings_handles_empty_list(self, mock_create_client):
        """Test that storing empty list doesn't call Supabase."""
        user_id = uuid4()
        store_resume_embeddings(user_id, [], [])

        # Should return early without calling Supabase
        mock_create_client.assert_not_called()


class TestProcessResumePipeline:
    """Test cases for the complete resume embedding pipeline."""

    @patch("services.embeddings.store_resume_embeddings")
    @patch("services.embeddings.embed_text")
    @patch("services.embeddings.delete_user_resume_embeddings")
    def test_process_resume_embedding_full_pipeline(
        self, mock_delete, mock_embed, mock_store
    ):
        """Test the complete pipeline: delete, chunk, embed, store."""
        user_id = uuid4()
        resume_text = """
## Experience
Job at Company A

## Education
BS Degree
"""
        mock_embed.return_value = [0.1] * 1536

        result = process_resume_embedding(user_id, resume_text)

        # Verify pipeline steps
        mock_delete.assert_called_once_with(user_id)
        assert mock_embed.call_count == 2  # 2 chunks
        mock_store.assert_called_once()

        # Verify return value
        assert result == 2  # 2 chunks created

    @patch("services.embeddings.delete_user_resume_embeddings")
    def test_process_resume_embedding_empty_resume(self, mock_delete):
        """Test that empty resume returns 0 and doesn't call embed/store."""
        user_id = uuid4()
        result = process_resume_embedding(user_id, "")

        mock_delete.assert_called_once_with(user_id)
        assert result == 0
