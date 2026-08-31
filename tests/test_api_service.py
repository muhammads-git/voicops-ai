# tests/test_api_service.py — tests for Deepgram speech_to_text

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestSpeechToText:
    @pytest.mark.asyncio
    async def test_successful_transcription(self, mock_deepgram_response):
        """Mocked Deepgram returns a valid transcript."""
        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(
                return_value=mock_deepgram_response
            )
            from app.services.api_service import speech_to_text
            result = await speech_to_text(b"fake audio bytes")

        assert result == "I need a nodejs app with redis and postgresql"

    @pytest.mark.asyncio
    async def test_empty_transcript_returns_empty_string(self):
        """Deepgram returns None transcript — should return empty string."""
        alternative = MagicMock()
        alternative.transcript = None
        channel = MagicMock()
        channel.alternatives = [alternative]
        results = MagicMock()
        results.channels = [channel]
        response = MagicMock()
        response.results = results

        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(return_value=response)
            from app.services.api_service import speech_to_text
            result = await speech_to_text(b"silent audio")

        assert result == ""

    @pytest.mark.asyncio
    async def test_api_error_raises_exception(self):
        """Deepgram API failure raises descriptive exception."""
        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(
                side_effect=RuntimeError("connection refused")
            )
            from app.services.api_service import speech_to_text
            with pytest.raises(Exception, match="Deepgram API error"):
                await speech_to_text(b"audio")

    @pytest.mark.asyncio
    async def test_sends_correct_model(self, mock_deepgram_response):
        """Verify Nova-3 model is used."""
        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(
                return_value=mock_deepgram_response
            )
            from app.services.api_service import speech_to_text
            await speech_to_text(b"audio")

            call_kwargs = mock_client.listen.v1.media.transcribe_file.call_args
            assert call_kwargs.kwargs["model"] == "nova-3"

    @pytest.mark.asyncio
    async def test_sends_keyterm_not_keywords(self, mock_deepgram_response):
        """Verify keyterm is used (Nova-3 doesn't support keywords)."""
        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(
                return_value=mock_deepgram_response
            )
            from app.services.api_service import speech_to_text
            await speech_to_text(b"audio")

            call_kwargs = mock_client.listen.v1.media.transcribe_file.call_args
            assert "keyterm" in call_kwargs.kwargs
            assert "keywords" not in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_smart_format_enabled(self, mock_deepgram_response):
        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(
                return_value=mock_deepgram_response
            )
            from app.services.api_service import speech_to_text
            await speech_to_text(b"audio")

            call_kwargs = mock_client.listen.v1.media.transcribe_file.call_args
            assert call_kwargs.kwargs["smart_format"] is True

    @pytest.mark.asyncio
    async def test_infrastructure_keyterms_included(self, mock_deepgram_response):
        """Verify infrastructure service names are passed as keyterms."""
        with patch("app.services.api_service.deepgram_client") as mock_client:
            mock_client.listen.v1.media.transcribe_file = AsyncMock(
                return_value=mock_deepgram_response
            )
            from app.services.api_service import speech_to_text
            await speech_to_text(b"audio")

            call_kwargs = mock_client.listen.v1.media.transcribe_file.call_args
            keyterms = call_kwargs.kwargs["keyterm"]
            assert "postgresql" in keyterms
            assert "redis" in keyterms
            assert "docker" in keyterms
            assert "nodejs" in keyterms
