"""Tests for briefing CRUD endpoints with resume embedding integration."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from openai import OpenAIError

from dependencies.auth import CurrentUser, get_current_user
from main import app


@pytest.fixture
def mock_user_id():
    """Mock user UUID."""
    return str(uuid4())


@pytest.fixture
def override_get_current_user(mock_user_id):
    """Override the auth dependency to return a mock user."""

    async def _mock_get_current_user():
        return CurrentUser(user_id=mock_user_id, email="test@example.com")

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_auth(override_get_current_user):
    """Test client with mocked authentication."""
    return TestClient(app)


class TestCreateBriefingWithResume:
    """Test POST /briefings with resume embedding integration."""

    @patch("routers.research.process_resume_embedding")
    @patch("routers.research._get_supabase")
    def test_create_briefing_with_resume_embeds_successfully(
        self, mock_supabase_fn, mock_process_resume, client_with_auth, mock_user_id
    ):
        """Test that creating briefing with resume triggers embedding."""
        # Mock Supabase
        mock_supabase = MagicMock()
        mock_supabase_fn.return_value = mock_supabase

        # Mock user update
        mock_user_update = MagicMock()
        mock_user_update.data = [{"id": mock_user_id}]
        mock_supabase.table("users").update().eq().execute.return_value = (
            mock_user_update
        )

        # Mock briefing insert
        mock_briefing_insert = MagicMock()
        mock_briefing_insert.data = [
            {
                "id": str(uuid4()),
                "user_id": mock_user_id,
                "company": "Acme Corp",
                "interviewer": None,
                "role": "Senior Engineer",
                "interview_date": None,
                "status": "pending",
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]
        mock_supabase.table("briefings").insert().execute.return_value = (
            mock_briefing_insert
        )

        # Mock embedding process
        mock_process_resume.return_value = 3  # 3 chunks created

        response = client_with_auth.post(
            "/briefings",
            json={
                "company": "Acme Corp",
                "role": "Senior Engineer",
                "resume_text": "## Experience\nJob 1\n\n## Education\nDegree 1",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Verify embedding was called
        mock_process_resume.assert_called_once_with(
            mock_user_id, "## Experience\nJob 1\n\n## Education\nDegree 1"
        )

    @patch("routers.research.process_resume_embedding")
    @patch("routers.research._get_supabase")
    def test_create_briefing_without_resume_skips_embedding(
        self, mock_supabase_fn, mock_process_resume, client_with_auth, mock_user_id
    ):
        """Test that creating briefing without resume doesn't call embedding."""
        # Mock Supabase
        mock_supabase = MagicMock()
        mock_supabase_fn.return_value = mock_supabase

        # Mock briefing insert
        mock_briefing_insert = MagicMock()
        mock_briefing_insert.data = [
            {
                "id": str(uuid4()),
                "user_id": mock_user_id,
                "company": "Acme Corp",
                "interviewer": None,
                "role": None,
                "interview_date": None,
                "status": "pending",
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]
        mock_supabase.table("briefings").insert().execute.return_value = (
            mock_briefing_insert
        )

        response = client_with_auth.post(
            "/briefings",
            json={"company": "Acme Corp"},
        )

        assert response.status_code == status.HTTP_201_CREATED

        # Verify embedding was NOT called
        mock_process_resume.assert_not_called()

    @patch("routers.research.process_resume_embedding")
    @patch("routers.research._get_supabase")
    def test_create_briefing_openai_error_returns_503(
        self, mock_supabase_fn, mock_process_resume, client_with_auth, mock_user_id
    ):
        """Test that OpenAI API failure returns 503 Service Unavailable."""
        # Mock Supabase
        mock_supabase = MagicMock()
        mock_supabase_fn.return_value = mock_supabase

        # Mock user update success
        mock_user_update = MagicMock()
        mock_user_update.data = [{"id": mock_user_id}]
        mock_supabase.table("users").update().eq().execute.return_value = (
            mock_user_update
        )

        # Mock embedding failure
        mock_process_resume.side_effect = OpenAIError("Rate limit exceeded")

        response = client_with_auth.post(
            "/briefings",
            json={
                "company": "Acme Corp",
                "resume_text": "Resume content",
            },
        )

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "temporarily unavailable" in response.json()["detail"].lower()

    @patch("routers.research.process_resume_embedding")
    @patch("routers.research._get_supabase")
    def test_create_briefing_missing_api_key_returns_500(
        self, mock_supabase_fn, mock_process_resume, client_with_auth, mock_user_id
    ):
        """Test that missing OPENAI_API_KEY returns 500 configuration error."""
        # Mock Supabase
        mock_supabase = MagicMock()
        mock_supabase_fn.return_value = mock_supabase

        # Mock user update success
        mock_user_update = MagicMock()
        mock_user_update.data = [{"id": mock_user_id}]
        mock_supabase.table("users").update().eq().execute.return_value = (
            mock_user_update
        )

        # Mock embedding failure due to missing API key
        mock_process_resume.side_effect = ValueError(
            "OPENAI_API_KEY environment variable not set"
        )

        response = client_with_auth.post(
            "/briefings",
            json={
                "company": "Acme Corp",
                "resume_text": "Resume content",
            },
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "configuration error" in response.json()["detail"].lower()

    @patch("routers.research.process_resume_embedding")
    @patch("routers.research._get_supabase")
    def test_create_briefing_updated_resume_triggers_re_embedding(
        self, mock_supabase_fn, mock_process_resume, client_with_auth, mock_user_id
    ):
        """Test that providing new resume_text re-embeds (deletes old chunks)."""
        # Mock Supabase
        mock_supabase = MagicMock()
        mock_supabase_fn.return_value = mock_supabase

        # Mock user update
        mock_user_update = MagicMock()
        mock_user_update.data = [{"id": mock_user_id}]
        mock_supabase.table("users").update().eq().execute.return_value = (
            mock_user_update
        )

        # Mock briefing insert
        mock_briefing_insert = MagicMock()
        mock_briefing_insert.data = [
            {
                "id": str(uuid4()),
                "user_id": mock_user_id,
                "company": "Acme Corp",
                "interviewer": None,
                "role": None,
                "interview_date": None,
                "status": "pending",
                "created_at": "2025-01-01T00:00:00Z",
            }
        ]
        mock_supabase.table("briefings").insert().execute.return_value = (
            mock_briefing_insert
        )

        # Mock embedding process (internally it deletes then re-embeds)
        mock_process_resume.return_value = 2

        response = client_with_auth.post(
            "/briefings",
            json={
                "company": "Acme Corp",
                "resume_text": "## New Resume\nUpdated content",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED

        # process_resume_embedding internally calls delete_user_resume_embeddings
        # We verified this in the unit tests for process_resume_embedding
        mock_process_resume.assert_called_once()
