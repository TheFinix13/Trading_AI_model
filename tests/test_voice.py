"""Tests for the voice service (STT + TTS)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


@pytest.fixture
def voice_service():
    """Create a VoiceService with mocked whisper model."""
    from agent.llm.voice import VoiceService
    svc = VoiceService(whisper_model_size="base", tts_voice="en-US-GuyNeural")
    return svc


class TestVoiceServiceInit:
    def test_creates_with_defaults(self):
        from agent.llm.voice import VoiceService
        svc = VoiceService()
        assert svc._whisper_model_size == "base"
        assert svc._tts_voice == "en-US-GuyNeural"
        assert svc._tts_rate == "+5%"
        assert svc._whisper_model is None

    def test_custom_params(self):
        from agent.llm.voice import VoiceService
        svc = VoiceService(
            whisper_model_size="small",
            tts_voice="en-US-JennyNeural",
            tts_rate="+10%",
        )
        assert svc._whisper_model_size == "small"
        assert svc._tts_voice == "en-US-JennyNeural"
        assert svc._tts_rate == "+10%"


class TestSTT:
    def test_transcribe_calls_whisper(self, voice_service):
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "what's the bias on EURUSD"
        mock_info = MagicMock()
        mock_info.duration = 2.5
        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        voice_service._whisper_model = mock_model
        voice_service._whisper_available = True

        result = asyncio.run(voice_service.transcribe(b"fake audio data", format="webm"))
        assert result == "what's the bias on EURUSD"
        mock_model.transcribe.assert_called_once()

    def test_transcribe_fails_gracefully_when_model_not_loaded(self, voice_service):
        voice_service._whisper_available = False
        voice_service._whisper_model = None

        with patch("agent.llm.voice.VoiceService._load_whisper", side_effect=RuntimeError("no model")):
            with pytest.raises(RuntimeError):
                asyncio.run(voice_service.transcribe(b"fake audio"))

    def test_is_available_false_when_no_model(self, voice_service):
        voice_service._whisper_available = False
        voice_service._whisper_model = None
        with patch("agent.llm.voice.VoiceService._load_whisper", side_effect=Exception("fail")):
            assert voice_service.is_available() is False


class TestTTS:
    def test_tts_available_when_edge_tts_installed(self, voice_service):
        assert voice_service.tts_available() is True

    def test_synthesize_produces_bytes(self, voice_service):
        fake_audio = b"\xff\xfb\x90\x00" * 100  # fake MP3 header bytes

        async def mock_save(path):
            from pathlib import Path
            Path(path).write_bytes(fake_audio)

        with patch("edge_tts.Communicate") as mock_comm_cls:
            mock_instance = MagicMock()
            mock_instance.save = mock_save
            mock_comm_cls.return_value = mock_instance

            result = asyncio.run(voice_service.synthesize("hello trader"))
            assert result == fake_audio
            mock_comm_cls.assert_called_once_with(
                "hello trader", "en-US-GuyNeural", rate="+5%"
            )


class TestVoiceEndpoints:
    """Integration-style tests for the FastAPI voice endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from agent.dashboard.app import app
        return TestClient(app)

    def test_voice_status_endpoint(self, client):
        resp = client.get("/api/voice/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "stt_available" in data
        assert "tts_available" in data
        assert data["whisper_model"] == "base"
        assert data["tts_voice"] == "en-US-GuyNeural"

    def test_transcribe_empty_file_returns_400(self, client):
        from io import BytesIO
        resp = client.post(
            "/api/voice/transcribe",
            files={"audio": ("test.webm", BytesIO(b""), "audio/webm")},
        )
        assert resp.status_code == 400

    def test_speak_empty_text_returns_400(self, client):
        resp = client.post(
            "/api/voice/speak",
            json={"text": ""},
        )
        assert resp.status_code == 400

    def test_voice_audio_invalid_filename(self, client):
        # Path traversal with ../ gets a 404 from the router (never reaches our handler)
        resp = client.get("/api/voice/audio/../etc/passwd")
        assert resp.status_code in (400, 404)

    def test_voice_audio_non_mp3_returns_400(self, client):
        resp = client.get("/api/voice/audio/malicious.exe")
        assert resp.status_code == 400

    def test_voice_audio_missing_file(self, client):
        resp = client.get("/api/voice/audio/nonexistent123.mp3")
        assert resp.status_code == 404
