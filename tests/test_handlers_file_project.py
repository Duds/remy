import asyncio
import os
from pathlib import Path

import pytest

from drbot.bot.handlers import make_handlers
from drbot.bot.session import SessionManager
from drbot.memory.conversations import ConversationStore
from drbot.memory.database import DatabaseManager
from drbot.memory.facts import FactStore


class DummyMessage:
    def __init__(self):
        self.last_text = None
        self.chat = self

    async def reply_text(self, text, parse_mode=None):
        self.last_text = text
        return self


def make_update(user_id=12345, text=""):
    class User:
        def __init__(self, uid):
            self.id = uid
            self.username = None
            self.first_name = None
            self.last_name = None

    class Update:
        def __init__(self, uid):
            self.effective_user = User(uid)
            self.message = DummyMessage()
            self.effective_chat = User(uid)

    return Update(user_id)


def make_context(args):
    class Context:
        def __init__(self, args):
            self.args = args
    return Context(args)


def test_set_and_status_project(tmp_path):
    # All async ops must share one event loop — aiosqlite connections are loop-bound
    # and hang if used across multiple asyncio.run() calls (Python 3.14+).
    async def _run():
        db_path = str(tmp_path / "drbot.db")
        db = DatabaseManager(db_path)
        await db.init()

        class DummyEmbeds:
            async def upsert_embedding(self, *args, **kwargs):
                return 1

        fact_store = FactStore(db, DummyEmbeds())
        handlers = make_handlers(
            session_manager=None,
            router=None,
            conv_store=None,
            fact_store=fact_store,
        )
        await db.upsert_user(12345)

        import drbot.bot.handlers as handlers_module
        handlers_module._ALLOWED_BASE_DIRS = [str(tmp_path)]
        set_project_cmd = handlers["set_project"]
        project_status_cmd = handlers["project_status"]

        update = make_update(12345)
        ctx = make_context([str(tmp_path)])
        await set_project_cmd(update, ctx)
        assert "Project set" in update.message.last_text

        update2 = make_update(12345)
        ctx2 = make_context([])
        await project_status_cmd(update2, ctx2)
        assert "Tracked projects" in update2.message.last_text
        assert str(tmp_path) in update2.message.last_text

    asyncio.run(_run())


def test_read_write_ls(tmp_path):
    session_manager = SessionManager()
    conv_store = ConversationStore(str(tmp_path / "sessions"))
    handlers = make_handlers(
        session_manager=session_manager,
        router=None,
        conv_store=conv_store,
    )
    # allow tmp_path for read/write tests
    import drbot.bot.handlers as handlers_module
    handlers_module._ALLOWED_BASE_DIRS = [str(tmp_path)]
    read_cmd = handlers["read"]
    write_cmd = handlers["write"]
    ls_cmd = handlers["ls"]
    find_cmd = handlers["find"]

    # create a file
    f = tmp_path / "allowed.txt"
    f.write_text("hello")
    update = make_update(12345)
    ctx = make_context([str(f)])
    asyncio.run(read_cmd(update, ctx))
    assert "hello" in update.message.last_text

    # write command two-step
    update2 = make_update(12345)
    ctx2 = make_context([str(f)])
    asyncio.run(write_cmd(update2, ctx2))
    assert "Send me the text" in update2.message.last_text
    # simulate the user sending the content message after /write
    update2b = make_update(12345)
    update2b.message.text = "newcontent"
    # use the generic message handler to process pending write
    asyncio.run(handlers["message"](update2b, make_context([])))
    assert "Wrote" in update2b.message.last_text
    # verify file was actually written
    assert f.read_text() == "newcontent"

    # directory list
    update3 = make_update(12345)
    asyncio.run(ls_cmd(update3, make_context([str(tmp_path)])))
    assert "allowed.txt" in update3.message.last_text

    # find pattern
    update4 = make_update(12345)
    asyncio.run(find_cmd(update4, make_context(["*.txt"])))
    assert "allowed.txt" in update4.message.last_text
