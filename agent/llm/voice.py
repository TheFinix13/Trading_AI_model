"""Voice service: speech-to-text (faster-whisper) and text-to-speech (edge-tts).

Designed for the dashboard chat — voice is an alternative input/output modality
alongside text. Both backends are lazy-loaded so the dashboard boots instantly
even when voice dependencies are missing or the whisper model hasn't been
downloaded yet.
"""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)


class VoiceService:
    """Handles STT (speech-to-text) and TTS (text-to-speech)."""

    def __init__(
        self,
        whisper_model_size: str = "base",
        tts_voice: str = "en-US-GuyNeural",
        tts_rate: str = "+5%",
    ):
        self._whisper_model_size = whisper_model_size
        self._tts_voice = tts_voice
        self._tts_rate = tts_rate
        self._whisper_model = None
        self._whisper_available: bool | None = None

    def _load_whisper(self):
        """Lazy-load the faster-whisper model on first transcription request."""
        if self._whisper_model is not None:
            return
        try:
            from faster_whisper import WhisperModel

            log.info("Loading faster-whisper model '%s' (first call)...", self._whisper_model_size)
            self._whisper_model = WhisperModel(
                self._whisper_model_size,
                device="cpu",
                compute_type="int8",
            )
            self._whisper_available = True
            log.info("Whisper model loaded successfully.")
        except Exception as e:
            log.warning("Failed to load whisper model: %s", e)
            self._whisper_available = False
            raise

    async def transcribe(self, audio_bytes: bytes, format: str = "webm") -> str:
        """Convert speech audio to text using faster-whisper.

        Accepts raw audio bytes (WebM/opus from browser, WAV, MP3, etc.).
        faster-whisper handles format conversion internally via ffmpeg.
        """
        self._load_whisper()
        if self._whisper_model is None:
            raise RuntimeError("Whisper model not available")

        suffix = f".{format}" if not format.startswith(".") else format
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            start = time.time()
            segments, info = self._whisper_model.transcribe(
                tmp_path,
                beam_size=5,
                language="en",
                vad_filter=True,
            )
            text_parts = [segment.text for segment in segments]
            text = " ".join(text_parts).strip()
            elapsed_ms = int((time.time() - start) * 1000)
            log.info(
                "Transcribed %.1fs audio in %dms: '%s'",
                info.duration, elapsed_ms, text[:80],
            )
            return text
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def synthesize(self, text: str) -> bytes:
        """Convert text to speech audio using edge-tts. Returns MP3 bytes."""
        import edge_tts

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            communicate = edge_tts.Communicate(
                text,
                self._tts_voice,
                rate=self._tts_rate,
            )
            await communicate.save(tmp_path)
            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def is_available(self) -> bool:
        """Check if the whisper model is loaded and ready."""
        if self._whisper_available is None:
            try:
                self._load_whisper()
            except Exception:
                return False
        return bool(self._whisper_available)

    def tts_available(self) -> bool:
        """TTS (edge-tts) is always available if the package is installed."""
        try:
            import edge_tts  # noqa: F401
            return True
        except ImportError:
            return False
