# tests/conftest.py — shared fixtures for all test modules

import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure .env is NOT loaded during tests — set dummy env vars before anything imports
os.environ.setdefault("DEEPGRAM_API_KEY", "test-deepgram-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture
def mock_groq_client():
    """Returns a fully mocked AsyncGroq client with chat.completions.create."""
    mock = MagicMock()
    mock.chat.completions.create = AsyncMock()
    return mock


@pytest.fixture
def mock_deepgram_response():
    """Builds a fake Deepgram ListenV1Response-shaped object."""
    alternative = MagicMock()
    alternative.transcript = "I need a nodejs app with redis and postgresql"

    channel = MagicMock()
    channel.alternatives = [alternative]

    results = MagicMock()
    results.channels = [channel]

    response = MagicMock()
    response.results = results
    return response
