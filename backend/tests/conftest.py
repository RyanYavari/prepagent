"""Shared test setup."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_startup_sweep():
    """App startup must never sweep a real database from a test run (backend/.env
    holds real credentials). Tests of the sweep call it directly."""
    with patch("main._startup_sweep"):
        yield
