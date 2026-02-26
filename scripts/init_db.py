"""
One-shot script to initialise the drbot SQLite database.
Run this before `make db` if drbot hasn't started yet.

Usage:
    python3 scripts/init_db.py
"""

import asyncio
import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "placeholder")
os.environ.setdefault("ANTHROPIC_API_KEY", "placeholder")
os.environ.setdefault("TELEGRAM_ALLOWED_USERS_RAW", "")

from drbot.memory.database import DatabaseManager  # noqa: E402


async def main() -> None:
    db = DatabaseManager()
    await db.init()
    await db.close()
    print(f"Database initialised at: {db.db_path}")


if __name__ == "__main__":
    asyncio.run(main())
