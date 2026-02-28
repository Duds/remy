import asyncio
import os
from pathlib import Path

from remy.scheduler.briefings import MorningBriefingGenerator


def test_downloads_suggestion(tmp_path, monkeypatch):
    """Test that old files in ~/Downloads are detected."""
    downloads = Path(tmp_path) / "Downloads"
    downloads.mkdir()
    old = downloads / "old.txt"
    old.write_text("x")
    os.utime(old, (old.stat().st_atime, old.stat().st_mtime - 8 * 86400))

    generator = MorningBriefingGenerator(user_id=123)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    msg = asyncio.run(generator._build_downloads_section())
    assert "old.txt" in msg

