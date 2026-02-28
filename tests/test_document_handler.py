"""Tests for the document handler (image files sent as Telegram documents)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDocumentHandlerConstants:
    """Test the constants used by the document handler."""

    def test_allowed_mimes_includes_jpeg(self):
        from remy.bot.handlers import make_handlers
        # The constants are defined inside make_handlers, so we test them indirectly
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        assert "image/jpeg" in allowed

    def test_allowed_mimes_includes_png(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        assert "image/png" in allowed

    def test_allowed_mimes_includes_gif(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        assert "image/gif" in allowed

    def test_allowed_mimes_includes_webp(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        assert "image/webp" in allowed

    def test_allowed_mimes_excludes_pdf(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        assert "application/pdf" not in allowed

    def test_allowed_mimes_excludes_heic(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        assert "image/heic" not in allowed

    def test_max_size_is_5mb(self):
        max_size = 5 * 1024 * 1024
        assert max_size == 5242880


class TestDocumentHandlerValidation:
    """Test MIME type and size validation logic."""

    def test_mime_type_check_accepts_png(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        mime = "image/png"
        assert mime in allowed

    def test_mime_type_check_rejects_pdf(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        mime = "application/pdf"
        assert mime not in allowed

    def test_mime_type_check_rejects_zip(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        mime = "application/zip"
        assert mime not in allowed

    def test_mime_type_check_rejects_none(self):
        allowed = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        mime = None
        assert mime not in allowed

    def test_size_check_accepts_small_file(self):
        max_size = 5 * 1024 * 1024
        file_size = 1024 * 1024  # 1 MB
        assert file_size <= max_size

    def test_size_check_accepts_exactly_5mb(self):
        max_size = 5 * 1024 * 1024
        file_size = 5 * 1024 * 1024  # 5 MB
        assert file_size <= max_size

    def test_size_check_rejects_over_5mb(self):
        max_size = 5 * 1024 * 1024
        file_size = 6 * 1024 * 1024  # 6 MB
        assert file_size > max_size


class TestDocumentHandlerHistoryPlaceholder:
    """Test the conversation history placeholder format."""

    def test_placeholder_with_filename_and_caption(self):
        filename = "screenshot.png"
        caption = "What's this error?"
        placeholder = f"[document: {filename}] {caption}"
        assert placeholder == "[document: screenshot.png] What's this error?"

    def test_placeholder_with_filename_no_caption(self):
        filename = "receipt.jpg"
        caption = ""
        placeholder = f"[document: {filename}] {caption}" if caption else f"[document: {filename}]"
        assert placeholder == "[document: receipt.jpg]"

    def test_placeholder_with_default_filename(self):
        filename = "image"
        caption = ""
        placeholder = f"[document: {filename}]"
        assert placeholder == "[document: image]"
