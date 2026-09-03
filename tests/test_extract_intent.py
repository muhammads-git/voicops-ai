# tests/test_extract_intent.py — tests for transcript normalization, fuzzy matching, intent extraction

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.extract_intent import (
    normalize_transcript,
    _edit_distance,
    _fuzzy_match,
    fuzzy_resolve,
    build_corrected_transcript,
    extract_intent,
    SUPPORTED_SERVICES,
)


# ── Layer 1: normalize_transcript ──

class TestNormalizeTranscript:
    def test_lowercases_input(self):
        assert normalize_transcript("HELLO WORLD") == "hello world"

    def test_fixes_nordjust_to_nodejs(self):
        assert "nodejs" in normalize_transcript("I want nordjust please")

    def test_fixes_postgres_equal_to_postgresql(self):
        assert "postgresql" in normalize_transcript("postgres equal database")

    def test_fixes_my_sequel_to_mysql(self):
        assert "mysql" in normalize_transcript("set up my sequel")

    def test_fixes_radish_to_redis(self):
        assert "redis" in normalize_transcript("use radish cache")

    def test_fixes_flash_to_flask(self):
        assert "flask" in normalize_transcript("build a flash app")

    def test_fixes_jango_to_django(self):
        assert "django" in normalize_transcript("jango web framework")

    def test_fixes_mango_to_mongodb(self):
        assert "mongodb" in normalize_transcript("store in mango")

    def test_no_change_for_clean_text(self):
        text = "i need a simple web server"
        assert normalize_transcript(text) == text

    def test_multiple_corrections_applied(self):
        result = normalize_transcript("nordjust with radish and my sequel")
        assert "nodejs" in result
        assert "redis" in result
        assert "mysql" in result


# ── Layer 2: edit distance and fuzzy matching ──

class TestEditDistance:
    def test_identical_strings(self):
        assert _edit_distance("redis", "redis") == 0

    def test_one_char_difference(self):
        assert _edit_distance("redis", "redix") == 1

    def test_empty_strings(self):
        assert _edit_distance("", "") == 0

    def test_one_empty(self):
        assert _edit_distance("redis", "") == 5
        assert _edit_distance("", "redis") == 5

    def test_completely_different(self):
        assert _edit_distance("abc", "xyz") == 3

    def test_symmetric(self):
        assert _edit_distance("redis", "redix") == _edit_distance("redix", "redis")

    def test_insertion(self):
        assert _edit_distance("node", "nodes") == 1


class TestFuzzyMatch:
    def test_exact_match(self):
        assert _fuzzy_match("redis") == "redis"

    def test_one_char_off(self):
        assert _fuzzy_match("redix") == "redis"

    def test_two_chars_off(self):
        result = _fuzzy_match("radish")
        # "radish" is 2 edits from "redis" — should match
        assert result == "redis"

    def test_too_far_returns_none(self):
        assert _fuzzy_match("kafka") is None

    def test_case_insensitive(self):
        assert _fuzzy_match("Redis") == "redis"

    def test_strips_whitespace(self):
        assert _fuzzy_match("  redis  ") == "redis"

    def test_custom_max_distance(self):
        # "radish" is 2 edits from "redis" — fails with max_distance=1
        assert _fuzzy_match("radish", max_distance=1) is None

    def test_empty_string(self):
        # Empty string should be too far from any service
        assert _fuzzy_match("") is None


# ── Layer 2+3: fuzzy_resolve ──

class TestFuzzyResolve:
    def test_known_services_pass_through(self):
        corrected, unsupported = fuzzy_resolve(["redis", "postgresql"], [])
        assert "redis" in corrected
        assert "postgresql" in corrected
        assert unsupported == []

    def test_fuzzy_correction_on_services(self):
        corrected, unsupported = fuzzy_resolve(["redix"], [])
        assert "redis" in corrected

    def test_duplicate_services_removed(self):
        corrected, _ = fuzzy_resolve(["redis", "redis"], [])
        assert corrected.count("redis") == 1

    def test_truly_unsupported_stays_unsupported(self):
        corrected, unsupported = fuzzy_resolve([], ["kafka"])
        assert "kafka" in unsupported
        assert "kafka" not in corrected

    def test_phonetic_alias_mongo_rescued(self):
        corrected, unsupported = fuzzy_resolve([], ["mongo"])
        assert "mongodb" in corrected
        assert "mongo" not in unsupported

    def test_phonetic_alias_postgres_rescued(self):
        corrected, unsupported = fuzzy_resolve([], ["postgres"])
        assert "postgresql" in corrected

    def test_phonetic_alias_django_rescued(self):
        corrected, unsupported = fuzzy_resolve([], ["jango"])
        assert "django" in corrected

    def test_phonetic_duplicate_not_duplicated(self):
        corrected, _ = fuzzy_resolve(["mongodb"], ["mongo"])
        assert corrected.count("mongodb") == 1

    def test_empty_inputs(self):
        corrected, unsupported = fuzzy_resolve([], [])
        assert corrected == []
        assert unsupported == []

    def test_mixed_known_and_unknown(self):
        corrected, unsupported = fuzzy_resolve(
            ["redis", "postgresql"],
            ["kafka", "rabbitmq"],
        )
        assert "redis" in corrected
        assert "postgresql" in corrected
        assert "kafka" in unsupported
        assert "rabbitmq" in unsupported


# ── build_corrected_transcript ──

class TestBuildCorrectedTranscript:
    def test_replaces_known_correction(self):
        result = build_corrected_transcript("I want nordjust", ["nodejs"])
        assert "nodejs" in result
        assert "nordjust" not in result

    def test_replaces_phonetic_alias(self):
        result = build_corrected_transcript("use mongo for storage", ["mongodb"])
        assert "mongodb" in result

    def test_lowercases_everything(self):
        result = build_corrected_transcript("I NEED REDIS", ["redis"])
        assert result == result.lower()

    def test_no_services_no_replacement(self):
        result = build_corrected_transcript("hello world", [])
        assert result == "hello world"

    def test_handles_punctuation_in_aliases(self):
        result = build_corrected_transcript("use mongo, and redis", ["mongodb", "redis"])
        assert "mongodb" in result


# ── extract_intent (mocked LLM) ──

class TestExtractIntent:
    @pytest.mark.asyncio
    async def test_valid_json_response(self):
        """Mock LLM returns valid JSON with known services."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": ["redis", "postgresql"],
            "unsupported": [],
            "deploy_cloud": False,
        })

        with patch("app.services.extract_intent.groq_client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await extract_intent("I need redis and postgresql")

        assert "redis" in result["services"]
        assert "postgresql" in result["services"]
        assert result["deploy_cloud"] is False

    @pytest.mark.asyncio
    async def test_cloud_deployment_detected(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": ["nodejs"],
            "unsupported": [],
            "deploy_cloud": True,
        })

        with patch("app.services.extract_intent.groq_client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await extract_intent("deploy nodejs to the cloud")

        assert result["deploy_cloud"] is True

    @pytest.mark.asyncio
    async def test_unsupported_services_extracted(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": ["redis"],
            "unsupported": ["kafka"],
            "deploy_cloud": False,
        })

        with patch("app.services.extract_intent.groq_client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await extract_intent("I need redis and kafka")

        assert "redis" in result["services"]
        assert "kafka" in result["unsupported"]

    @pytest.mark.asyncio
    async def test_non_json_raises_exception(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I'm sorry, I can't help with that"

        with patch("app.services.extract_intent.groq_client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            with pytest.raises(Exception, match="Could not parse intent"):
                await extract_intent("gibberish")

    @pytest.mark.asyncio
    async def test_non_bool_deploy_cloud_defaults_false(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": ["redis"],
            "unsupported": [],
            "deploy_cloud": "yes",
        })

        with patch("app.services.extract_intent.groq_client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await extract_intent("redis on the cloud")

        assert result["deploy_cloud"] is False

    @pytest.mark.asyncio
    async def test_fuzzy_correction_applied_to_llm_output(self):
        """LLM returns a slightly misspelled service that fuzzy_resolve can fix."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "services": ["redix"],
            "unsupported": [],
            "deploy_cloud": False,
        })

        with patch("app.services.extract_intent.groq_client") as mock_client:
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            result = await extract_intent("I need redix")

        # "redix" should be fuzzy-corrected to "redis"
        assert "redis" in result["services"]
