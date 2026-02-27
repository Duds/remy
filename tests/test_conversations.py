import os
import tempfile
import asyncio

from remy.memory.conversations import ConversationStore
from remy.models import ConversationTurn


def test_delete_session(tmp_path):
    store = ConversationStore(str(tmp_path))
    user_id = 1
    session_key = "user_1_test"
    # append a turn then delete file
    turn = ConversationTurn(role="user", content="hi")
    asyncio.run(store.append_turn(user_id, session_key, turn))
    path = os.path.join(str(tmp_path), f"{session_key}.jsonl")
    assert os.path.exists(path)
    # delete and check removal
    asyncio.run(store.delete_session(user_id, session_key))
    assert not os.path.exists(path)


def test_get_all_sessions(tmp_path):
    store = ConversationStore(str(tmp_path))
    keys = ["user_1_a", "user_1_b"]
    for k in keys:
        fpath = os.path.join(str(tmp_path), f"{k}.jsonl")
        with open(fpath, "w") as f:
            f.write("{}\n")
    result = asyncio.run(store.get_all_sessions(user_id=1))
    assert sorted(result) == sorted(keys)
