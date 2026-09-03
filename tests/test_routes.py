# tests/test_routes.py — FastAPI integration tests (TestClient with mocked services)

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestGenerateTextEndpoint:
    @pytest.mark.asyncio
    async def test_empty_text_returns_400(self, client):
        resp = await client.post("/generate-text", data={"text": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_400(self, client):
        resp = await client.post("/generate-text", data={"text": "   "})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_text_full_pipeline(self, client):
        """Mock all external calls and verify the full pipeline works."""
        mock_intent_response = MagicMock()
        mock_intent_response.choices = [MagicMock()]
        mock_intent_response.choices[0].message.content = json.dumps({
            "services": ["nodejs", "redis"],
            "unsupported": [],
            "deploy_cloud": False,
        })

        with patch("app.services.extract_intent.groq_client") as mock_groq, \
             patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate:
            mock_groq.chat.completions.create = AsyncMock(return_value=mock_intent_response)
            mock_validate.return_value = {"valid": None, "errors": [], "tool_available": False}

            resp = await client.post("/generate-text", data={"text": "I need nodejs with redis"})

        assert resp.status_code == 200
        body = resp.json()
        assert "transcript" in body
        assert "dockerfile" in body
        assert body["dockerfile"] is not None
        assert "node" in body["dockerfile"].lower() or "FROM" in body["dockerfile"]
        assert "docker_compose" in body
        assert body["docker_compose"] is not None

    @pytest.mark.asyncio
    async def test_cloud_deployment_generates_terraform(self, client):
        mock_intent_response = MagicMock()
        mock_intent_response.choices = [MagicMock()]
        mock_intent_response.choices[0].message.content = json.dumps({
            "services": ["fastapi"],
            "unsupported": [],
            "deploy_cloud": True,
        })

        with patch("app.services.extract_intent.groq_client") as mock_groq, \
             patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate:
            mock_groq.chat.completions.create = AsyncMock(return_value=mock_intent_response)
            mock_validate.return_value = {"valid": None, "errors": [], "tool_available": False}

            resp = await client.post("/generate-text", data={"text": "deploy fastapi to the cloud"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["terraform"] is not None
        assert "alicloud" in body["terraform"]

    @pytest.mark.asyncio
    async def test_intent_extraction_failure_returns_502(self, client):
        with patch("app.services.extract_intent.groq_client") as mock_groq:
            mock_groq.chat.completions.create = AsyncMock(
                side_effect=Exception("LLM down")
            )
            resp = await client.post("/generate-text", data={"text": "hello world"})

        assert resp.status_code == 502


class TestGenerateConfigEndpoint:
    @pytest.mark.asyncio
    async def test_speech_failure_returns_502(self, client):
        """Mocked speech_to_text fails — should return 502."""
        with patch("app.routers.route.speech_to_text", new_callable=AsyncMock) as mock_stt:
            mock_stt.side_effect = Exception("Deepgram error")
            # Reset circuit breaker state for this test
            from app.routers.route import speech_breaker
            speech_breaker.failure_count = 0
            speech_breaker.state = "closed"

            resp = await client.post(
                "/generate-config",
                files={"audio": ("test.wav", b"fake audio", "audio/wav")},
            )

        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_circuit_open_returns_503(self, client):
        """When circuit breaker is open, should return 503."""
        from app.routers.route import speech_breaker
        speech_breaker.state = "open"
        speech_breaker.last_failure_time = float("inf")  # cooldown never expires

        try:
            resp = await client.post(
                "/generate-config",
                files={"audio": ("test.wav", b"fake audio", "audio/wav")},
            )
            assert resp.status_code == 503
        finally:
            # Reset circuit breaker
            speech_breaker.state = "closed"
            speech_breaker.failure_count = 0
            speech_breaker.last_failure_time = 0.0


class TestAnalyticsEndpoint:
    @pytest.mark.asyncio
    async def test_analytics_returns_dict(self, client):
        """Analytics should return even when DB is unavailable."""
        resp = await client.get("/api/analytics")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_requests" in body
        assert "success_rate" in body
        assert "avg_healing_count" in body
        assert "recent_requests" in body


class TestStaticPages:
    @pytest.mark.asyncio
    async def test_index_page(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_generate_page(self, client):
        resp = await client.get("/generate")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_analytics_page(self, client):
        resp = await client.get("/analytics")
        assert resp.status_code == 200
