"""
Voice transcription using faster-whisper.

Downloads a Telegram voice/audio file to a temp path, runs faster-whisper
in a thread executor (non-blocking), and returns the transcript string.

Model is lazy-loaded on first use and cached for the lifetime of the process.
"""

import asyncio
import logging
import os
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import File as TelegramFile

logger = logging.getLogger(__name__)

# Module-level model cache (None until first transcription)
_model = None
_model_lock = asyncio.Lock()

# Whisper model to use — "tiny" is fast and accurate enough for personal use.
# Override via WHISPER_MODEL env var (tiny / base / small / medium / large-v3)
_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "tiny")
_WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
_WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")


def _load_model():
    """Load the faster-whisper model synchronously (called in executor)."""
    from faster_whisper import WhisperModel  # type: ignore[import]
    logger.info(
        "Loading Whisper model '%s' on %s (%s)…",
        _WHISPER_MODEL, _WHISPER_DEVICE, _WHISPER_COMPUTE,
    )
    return WhisperModel(
        _WHISPER_MODEL,
        device=_WHISPER_DEVICE,
        compute_type=_WHISPER_COMPUTE,
    )


def _transcribe_sync(model, audio_path: str) -> str:
    """Run transcription synchronously (called in executor)."""
    segments, info = model.transcribe(audio_path, beam_size=5)
    logger.debug(
        "Detected language '%s' (%.0f%% confidence)",
        info.language, info.language_probability * 100,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()


class VoiceTranscriber:
    """
    Transcribes Telegram voice messages using faster-whisper.

    Usage:
        transcriber = VoiceTranscriber()
        text = await transcriber.transcribe(telegram_file_object)
    """

    async def _get_model(self):
        """Return the cached model, loading it on first call."""
        global _model
        if _model is not None:
            return _model
        async with _model_lock:
            # Double-checked locking
            if _model is None:
                loop = asyncio.get_event_loop()
                _model = await loop.run_in_executor(None, _load_model)
        return _model

    async def transcribe(self, telegram_file: "TelegramFile") -> str:
        """
        Download a Telegram file and return the transcript.
        Returns empty string on any error.
        """
        tmp_path = None
        try:
            # Download to a temp file with correct extension for ffmpeg
            suffix = ".ogg"  # Telegram voice messages are Opus/OGG
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                tmp_path = f.name

            await telegram_file.download_to_drive(tmp_path)
            logger.debug("Downloaded voice file to %s", tmp_path)

            model = await self._get_model()
            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(
                None, _transcribe_sync, model, tmp_path
            )
            logger.info("Transcribed %d chars", len(transcript))
            return transcript

        except Exception as e:
            logger.error("Transcription failed: %s", e)
            return ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    async def transcribe_path(self, audio_path: str) -> str:
        """
        Transcribe a local audio file directly (useful for testing).
        Returns empty string on any error.
        """
        try:
            model = await self._get_model()
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, _transcribe_sync, model, audio_path
            )
        except Exception as e:
            logger.error("Transcription from path failed: %s", e)
            return ""
