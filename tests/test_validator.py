# tests/test_validator.py — tests for Dockerfile, Terraform, and Compose validation

import pytest
import tempfile
from unittest.mock import patch, MagicMock
from app.services.validator import validate_dockerfile, validate_terraform, validate_compose


class TestValidateDockerfile:
    @pytest.mark.asyncio
    async def test_hadolint_not_installed(self):
        """When hadolint is missing, valid=None (unchecked) — never displayed as a pass."""
        with patch("app.services.validator.find_tool", return_value=None):
            result = await validate_dockerfile("FROM node:20\n")
        assert result["valid"] is None
        assert result["tool_available"] is False
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_hadolint_passes(self):
        """When hadolint returns no output, Dockerfile is valid."""
        mock_proc = MagicMock()
        mock_proc.stdout = b""
        mock_proc.stderr = b""
        mock_proc.returncode = 0

        with patch("app.services.validator.find_tool", return_value="/usr/bin/hadolint"), \
             patch("subprocess.run", return_value=mock_proc):
            result = await validate_dockerfile("FROM node:20-alpine\n")

        assert result["valid"] is True
        assert result["tool_available"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_hadolint_finds_errors(self):
        """When hadolint returns JSON errors."""
        import json
        hadolint_output = json.dumps([
            {"line": 1, "code": "DL3007", "message": "Using latest is prone to errors"},
        ]).encode()
        mock_proc = MagicMock()
        mock_proc.stdout = hadolint_output
        mock_proc.stderr = b""
        mock_proc.returncode = 1

        with patch("app.services.validator.find_tool", return_value="/usr/bin/hadolint"), \
             patch("subprocess.run", return_value=mock_proc):
            result = await validate_dockerfile("FROM node:latest\n")

        assert result["valid"] is False
        assert result["tool_available"] is True
        assert len(result["errors"]) == 1
        assert "DL3007" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_hadolint_empty_json_means_valid(self):
        """Empty JSON array = no errors."""
        mock_proc = MagicMock()
        mock_proc.stdout = b"[]"
        mock_proc.stderr = b""
        mock_proc.returncode = 0

        with patch("app.services.validator.find_tool", return_value="/usr/bin/hadolint"), \
             patch("subprocess.run", return_value=mock_proc):
            result = await validate_dockerfile("FROM node:20\n")

        assert result["valid"] is True


class TestValidateTerraform:
    @pytest.mark.asyncio
    async def test_terraform_not_installed(self):
        """When terraform is missing, valid=None (unchecked) — never displayed as a pass."""
        with patch("app.services.validator.find_tool", return_value=None):
            result = await validate_terraform('provider "alicloud" {}')
        assert result["valid"] is None
        assert result["tool_available"] is False

    @pytest.mark.asyncio
    async def test_terraform_valid_output(self):
        """When terraform validate returns valid JSON."""
        import json
        tf_valid_output = json.dumps({"valid": True, "diagnostics": []}).encode()
        tmpdir = tempfile.mkdtemp(prefix="voicops_test_")

        mock_init_proc = MagicMock()
        mock_init_proc.stdout = b""
        mock_init_proc.stderr = b""
        mock_init_proc.returncode = 0

        mock_validate_proc = MagicMock()
        mock_validate_proc.stdout = tf_valid_output
        mock_validate_proc.stderr = b""
        mock_validate_proc.returncode = 0

        call_count = 0
        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_init_proc
            return mock_validate_proc

        with patch("app.services.validator.find_tool", return_value="/usr/bin/terraform"), \
             patch("subprocess.run", side_effect=mock_run), \
             patch("tempfile.mkdtemp", return_value=tmpdir), \
             patch("shutil.rmtree"):
            result = await validate_terraform('provider "alicloud" {}')

        assert result["valid"] is True
        assert result["tool_available"] is True

    @pytest.mark.asyncio
    async def test_terraform_invalid_output(self):
        """When terraform validate returns errors."""
        import json
        tf_invalid_output = json.dumps({
            "valid": False,
            "diagnostics": [
                {"summary": "Missing required argument", "detail": "region is required"},
            ],
        }).encode()
        tmpdir = tempfile.mkdtemp(prefix="voicops_test_")

        mock_init_proc = MagicMock()
        mock_init_proc.stdout = b""
        mock_init_proc.stderr = b""
        mock_init_proc.returncode = 0

        mock_validate_proc = MagicMock()
        mock_validate_proc.stdout = tf_invalid_output
        mock_validate_proc.stderr = b""
        mock_validate_proc.returncode = 0

        call_count = 0
        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_init_proc
            return mock_validate_proc

        with patch("app.services.validator.find_tool", return_value="/usr/bin/terraform"), \
             patch("subprocess.run", side_effect=mock_run), \
             patch("tempfile.mkdtemp", return_value=tmpdir), \
             patch("shutil.rmtree"):
            result = await validate_terraform("bad terraform")

        assert result["valid"] is False
        assert result["tool_available"] is True
        assert len(result["errors"]) == 1
        assert "Missing required argument" in result["errors"][0]


class TestValidateCompose:
    @pytest.mark.asyncio
    async def test_valid_compose_passes(self):
        """Valid YAML passes yamllint with no errors."""
        valid_yaml = (
            "version: '3.8'\n"
            "services:\n"
            "  app:\n"
            "    build: .\n"
            "    ports:\n"
            '      - "3000:3000"\n'
        )
        result = await validate_compose(valid_yaml)
        assert result["valid"] is True
        assert result["tool_available"] is True
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_duplicate_keys_detected(self):
        """yamllint catches duplicate keys in YAML."""
        bad_yaml = (
            "version: '3.8'\n"
            "services:\n"
            "  app:\n"
            "    build: .\n"
            "    build: ./other\n"
        )
        result = await validate_compose(bad_yaml)
        assert result["valid"] is False
        assert result["tool_available"] is True
        assert len(result["errors"]) >= 1
        assert any("duplication" in e.lower() or "duplicate" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_bad_indentation_detected(self):
        """yamllint catches bad indentation."""
        bad_yaml = (
            "version: '3.8'\n"
            "services:\n"
            "  app:\n"
            "     build: .\n"
        )
        result = await validate_compose(bad_yaml)
        assert result["valid"] is False
        assert result["tool_available"] is True
        assert len(result["errors"]) >= 1

    @pytest.mark.asyncio
    async def test_tool_always_available(self):
        """yamllint is pip-installed, so tool_available is always True."""
        result = await validate_compose("version: '3.8'\n")
        assert result["tool_available"] is True
