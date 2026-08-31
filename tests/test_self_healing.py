# tests/test_self_healing.py — tests for self-healing logic and strip_code_fences

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.self_healing import strip_code_fences, heal_dockerfile, heal_terraform, MAX_HEALING_ATTEMPTS


class TestStripCodeFences:
    def test_no_fences(self):
        assert strip_code_fences("FROM node:20") == "FROM node:20"

    def test_removes_plain_fences(self):
        text = "```\nFROM node:20\n```"
        assert strip_code_fences(text) == "FROM node:20"

    def test_removes_fences_with_language(self):
        text = "```dockerfile\nFROM node:20\n```"
        assert strip_code_fences(text) == "FROM node:20"

    def test_removes_fences_with_hcl(self):
        text = "```hcl\nresource \"aws_instance\" {}\n```"
        assert strip_code_fences(text) == 'resource "aws_instance" {}'

    def test_strips_whitespace(self):
        assert strip_code_fences("  FROM node:20  ") == "FROM node:20"

    def test_fences_without_newline(self):
        text = "```FROM node:20```"
        result = strip_code_fences(text)
        assert result == "FROM node:20"

    def test_empty_string(self):
        assert strip_code_fences("") == ""

    def test_only_fences(self):
        assert strip_code_fences("```\n```") == ""


class TestHealDockerfile:
    @pytest.mark.asyncio
    async def test_valid_dockerfile_passes_through(self):
        """If validator says valid, no healing needed."""
        with patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {"valid": True, "errors": [], "tool_available": True}
            result = await heal_dockerfile("FROM node:20\n")

        assert result["valid"] is True
        assert result["healing_count"] == 0
        assert result["content"] == "FROM node:20\n"

    @pytest.mark.asyncio
    async def test_tool_unavailable_returns_immediately(self):
        """If hadolint not installed, skip healing."""
        with patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {"valid": True, "errors": [], "tool_available": False}
            result = await heal_dockerfile("FROM node:20\n")

        assert result["tool_available"] is False
        assert result["healing_count"] == 0

    @pytest.mark.asyncio
    async def test_heals_on_first_attempt(self):
        """Validator fails first time, LLM fixes it, validator passes."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "FROM node:20-alpine\nWORKDIR /app"

        with patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate, \
             patch("app.services.self_healing.groq_client") as mock_client:
            mock_validate.side_effect = [
                {"valid": False, "errors": ["Missing WORKDIR"], "tool_available": True},
                {"valid": True, "errors": [], "tool_available": True},
            ]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            result = await heal_dockerfile("FROM node:20-alpine\n")

        assert result["valid"] is True
        assert result["healing_count"] == 1

    @pytest.mark.asyncio
    async def test_heals_on_second_attempt(self):
        """First fix still invalid, second fix works."""
        mock_resp1 = MagicMock()
        mock_resp1.choices = [MagicMock()]
        mock_resp1.choices[0].message.content = "FROM node:20-alpine\nWORKDIR /app\nCOPY . ."

        mock_resp2 = MagicMock()
        mock_resp2.choices = [MagicMock()]
        mock_resp2.choices[0].message.content = "FROM node:20-alpine\nWORKDIR /app\nCOPY . .\nCMD npm start"

        with patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate, \
             patch("app.services.self_healing.groq_client") as mock_client:
            mock_validate.side_effect = [
                {"valid": False, "errors": ["Missing WORKDIR"], "tool_available": True},
                {"valid": False, "errors": ["Missing CMD"], "tool_available": True},
                {"valid": True, "errors": [], "tool_available": True},
            ]
            mock_client.chat.completions.create = AsyncMock(side_effect=[mock_resp1, mock_resp2])

            result = await heal_dockerfile("FROM node:20-alpine\n")

        assert result["valid"] is True
        assert result["healing_count"] == 2

    @pytest.mark.asyncio
    async def test_exhausted_attempts(self):
        """All healing attempts fail."""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "FROM broken"

        with patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate, \
             patch("app.services.self_healing.groq_client") as mock_client:
            mock_validate.return_value = {"valid": False, "errors": ["Still broken"], "tool_available": True}
            mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

            result = await heal_dockerfile("FROM broken\n")

        assert result["valid"] is False
        assert result["healing_count"] == MAX_HEALING_ATTEMPTS

    @pytest.mark.asyncio
    async def test_llm_exception_returns_gracefully(self):
        """If LLM call fails, return gracefully without crashing."""
        with patch("app.services.self_healing.validate_dockerfile", new_callable=AsyncMock) as mock_validate, \
             patch("app.services.self_healing.groq_client") as mock_client:
            mock_validate.return_value = {"valid": False, "errors": ["Error"], "tool_available": True}
            mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("LLM down"))

            result = await heal_dockerfile("FROM broken\n")

        assert result["valid"] is False
        assert result["healing_count"] == 0  # attempt - 1 = 1 - 1 = 0


class TestHealTerraform:
    @pytest.mark.asyncio
    async def test_valid_terraform_passes_through(self):
        with patch("app.services.self_healing.validate_terraform", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {"valid": True, "errors": [], "tool_available": True}
            result = await heal_terraform('provider "alicloud" {}')

        assert result["valid"] is True
        assert result["healing_count"] == 0

    @pytest.mark.asyncio
    async def test_tool_unavailable_returns_immediately(self):
        with patch("app.services.self_healing.validate_terraform", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = {"valid": True, "errors": [], "tool_available": False}
            result = await heal_terraform('provider "alicloud" {}')

        assert result["tool_available"] is False
