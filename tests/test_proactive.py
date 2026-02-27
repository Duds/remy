import asyncio
import os
from pathlib import Path

from remy.scheduler.proactive import ProactiveScheduler


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append((chat_id, text))


class DummyGoalStore:
    async def get_active(self, user_id, limit=10):
        return []


def test_downloads_suggestion(tmp_path, monkeypatch):
    # create some old files
    downloads = Path(tmp_path) / "Downloads"
    downloads.mkdir()
    old = downloads / "old.txt"
    old.write_text("x")
    # set modification time to 8 days ago
    os.utime(old, (old.stat().st_atime, old.stat().st_mtime - 8 * 86400))

    scheduler = ProactiveScheduler(DummyBot(), DummyGoalStore())
    # monkeypatch home directory to tmp_path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    msg = asyncio.run(scheduler._downloads_suggestion())
    assert "old.txt" in msg

