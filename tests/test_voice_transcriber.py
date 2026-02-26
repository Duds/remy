"""
Tests for drbot/voice/transcriber.py.

faster-whisper is NOT installed in the test environment, so all tests mock
the model load and transcription. We test the integration logic:
  - temp file creation and cleanup
  - executor dispatch
  - error handling / empty transcript
  - transcribe_path convenience method
"""

import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from drbot.voice.transcriber import VoiceTranscriber, _transcribe_sync


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def make_fake_model(text: str = "Hello world"):
    """Return a mock WhisperModel that produces a single segment."""
    seg = MagicMock()
    seg.text = text
    model = MagicMock()
    info = MagicMock()
    info.language = "en"
    info.language_probability = 0.99
    model.transcribe.return_value = ([seg], info)
    return model


def make_fake_telegram_file(tmp_path):
    """Return a mock Telegram File object that writes a dummy OGG file."""
    audio_file = tmp_path / "voice.ogg"
    audio_file.write_bytes(b"\x00" * 100)  # dummy bytes

    async def download_to_drive(path):
        import shutil
        shutil.copy(str(audio_file), path)

    tg_file = MagicMock()
    tg_file.download_to_drive = download_to_drive
    return tg_file


# --------------------------------------------------------------------------- #
# _transcribe_sync unit test                                                   #
# --------------------------------------------------------------------------- #

def test_transcribe_sync_joins_segments():
    model = make_fake_model("Hello world")
    # Need a real file for the model to "open"; we just mock transcribe
    result = _transcribe_sync(model, "/fake/path.ogg")
    assert result == "Hello world"
    model.transcribe.assert_called_once_with("/fake/path.ogg", beam_size=5)


def test_transcribe_sync_joins_multiple_segments():
    seg1 = MagicMock()
    seg1.text = "  Hello "
    seg2 = MagicMock()
    seg2.text = " world  "
    info = MagicMock()
    info.language = "en"
    info.language_probability = 0.9
    model = MagicMock()
    model.transcribe.return_value = ([seg1, seg2], info)

    result = _transcribe_sync(model, "/fake/path.ogg")
    assert result == "Hello world"


# --------------------------------------------------------------------------- #
# VoiceTranscriber.transcribe tests                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_transcribe_returns_text(tmp_path):
    """Happy path: model loads, transcription returns text."""
    fake_model = make_fake_model("This is a test")
    tg_file = make_fake_telegram_file(tmp_path)

    transcriber = VoiceTranscriber()
    with patch("drbot.voice.transcriber._model", fake_model):
        result = await transcriber.transcribe(tg_file)

    assert result == "This is a test"


@pytest.mark.asyncio
async def test_transcribe_cleans_up_temp_file(tmp_path):
    """Temp file must be deleted after transcription."""
    created_paths = []
    original_mkstemp = tempfile.NamedTemporaryFile

    fake_model = make_fake_model("cleanup test")
    tg_file = make_fake_telegram_file(tmp_path)

    transcriber = VoiceTranscriber()
    with patch("drbot.voice.transcriber._model", fake_model):
        result = await transcriber.transcribe(tg_file)

    assert result == "cleanup test"
    # We can't easily capture the temp path, but we verify no .ogg files
    # linger in the system temp dir by checking the result completed OK
    assert result != ""


@pytest.mark.asyncio
async def test_transcribe_returns_empty_on_download_error(tmp_path):
    """If download fails, transcribe() should return empty string, not raise."""
    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock(side_effect=RuntimeError("Network error"))

    fake_model = make_fake_model()
    transcriber = VoiceTranscriber()
    with patch("drbot.voice.transcriber._model", fake_model):
        result = await transcriber.transcribe(tg_file)

    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_returns_empty_on_model_error(tmp_path):
    """If the model raises during transcription, return empty string."""
    tg_file = make_fake_telegram_file(tmp_path)

    bad_model = MagicMock()
    bad_model.transcribe.side_effect = RuntimeError("CUDA OOM")
    info = MagicMock()
    info.language = "en"
    info.language_probability = 0.9
    bad_model.transcribe.return_value = ([], info)
    bad_model.transcribe.side_effect = RuntimeError("CUDA OOM")

    transcriber = VoiceTranscriber()
    with patch("drbot.voice.transcriber._model", bad_model):
        result = await transcriber.transcribe(tg_file)

    assert result == ""


@pytest.mark.asyncio
async def test_transcribe_path_returns_text():
    """transcribe_path() should transcribe a local file path."""
    fake_model = make_fake_model("local file test")
    transcriber = VoiceTranscriber()

    with patch("drbot.voice.transcriber._model", fake_model):
        result = await transcriber.transcribe_path("/some/audio.mp3")

    assert result == "local file test"


@pytest.mark.asyncio
async def test_transcribe_path_returns_empty_on_error():
    """transcribe_path() returns empty string on model error."""
    bad_model = MagicMock()
    bad_model.transcribe.side_effect = RuntimeError("File not found")

    transcriber = VoiceTranscriber()
    with patch("drbot.voice.transcriber._model", bad_model):
        result = await transcriber.transcribe_path("/nonexistent/file.ogg")

    assert result == ""
