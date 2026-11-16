"""Shared test setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _no_startup_sweep():
    """App startup must never sweep a real database from a test run (backend/.env
    holds real credentials). Tests of the sweep call it directly."""
    with patch("main._startup_sweep"):
        yield


@pytest.fixture(autouse=True)
def _no_async_retry_backoff():
    """Retry backoff must not make tests wait. Only net_config's own `asyncio`
    reference is replaced; the real asyncio.sleep is untouched."""
    with patch("services.net_config.asyncio", SimpleNamespace(sleep=AsyncMock())):
        yield
