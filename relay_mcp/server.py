#!/usr/bin/env python3
"""
relay_mcp — Inter-agent communication server for Claude agents.

Provides a shared message and task bus so agents (e.g. "cowork", "remy")
can delegate work, report results, and exchange notes without being
in the same conversation.

Usage:
    python server.py                  # runs on http://127.0.0.1:8765
    python server.py --port 9000      # custom port
    python server.py --db /path/to/relay.db  # custom DB location
"""

import argparse
import json
import sqlite3
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_PORT = 8765
DEFAULT_DB   = Path(__file__).parent / "relay.db"

KNOWN_AGENTS = ["cowork", "remy"]   # informational only — not enforced

TASK_STATUSES  = {"pending", "in_progress", "done", "failed", "needs_clarification"}
VALID_STATUSES = ", ".join(sorted(TASK_STATUSES))

# ── Database ───────────────────────────────────────────────────────────────────

def get_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            from_agent  TEXT NOT NULL,
            to_agent    TEXT NOT NULL,
            content     TEXT NOT NULL,
            thread_id   TEXT,
            read        INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            from_agent  TEXT NOT NULL,
            to_agent    TEXT NOT NULL,
            task_type   TEXT NOT NULL,
            description TEXT NOT NULL,
            params      TEXT NOT NULL DEFAULT '{}',
            status      TEXT NOT NULL DEFAULT 'pending',
            result      TEXT,
            notes       TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS shared_notes (
            id          TEXT PRIMARY KEY,
            from_agent  TEXT NOT NULL,
            content     TEXT NOT NULL,
            tags        TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_to    ON messages(to_agent, read);
        CREATE INDEX IF NOT EXISTS idx_tasks_to       ON tasks(to_agent, status);
        CREATE INDEX IF NOT EXISTS idx_tasks_from     ON tasks(from_agent);
        CREATE INDEX IF NOT EXISTS idx_notes_tags     ON shared_notes(tags);
    """)
    conn.commit()


# DB connection lives for the server lifetime, injected via lifespan state
_db_path: Path = DEFAULT_DB


@asynccontextmanager
async def lifespan(app):
    conn = get_db(_db_path)
    init_db(conn)
    yield {"db": conn}
    conn.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())[:8]


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ── FastMCP server ─────────────────────────────────────────────────────────────

mcp = FastMCP("relay_mcp", lifespan=lifespan)


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGING TOOLS
# ══════════════════════════════════════════════════════════════════════════════

class PostMessageInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    from_agent: str = Field(..., description="Name of the sending agent (e.g. 'cowork', 'remy')", min_length=1, max_length=50)
    to_agent:   str = Field(..., description="Name of the receiving agent (e.g. 'remy', 'cowork')", min_length=1, max_length=50)
    content:    str = Field(..., description="Message body — plain text or markdown", min_length=1, max_length=8000)
    thread_id:  Optional[str] = Field(default=None, description="Thread ID to group related messages. Omit to start a new thread.")


@mcp.tool(
    name="relay_post_message",
    annotations={
        "title": "Post a message to another agent",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def relay_post_message(params: PostMessageInput, ctx) -> str:
    """Send a message from one agent to another.

    Use this to communicate across agent boundaries — ask questions, share
    observations, request clarification, or send a brief update.
    Messages persist until explicitly deleted. The recipient can retrieve them
    with relay_get_messages.

    Args:
        params (PostMessageInput):
            - from_agent (str): Your agent name, e.g. 'cowork'
            - to_agent (str): Recipient agent name, e.g. 'remy'
            - content (str): Message body (plain text or markdown)
            - thread_id (Optional[str]): Group replies under a thread ID

    Returns:
        str: JSON with the new message id and thread_id.

    Examples:
        - Use when: telling Remy "label all Radford emails as 4-Personal & Family"
        - Use when: asking Remy "how many emails were trashed in the last run?"
        - Use when: Remy needs to ask cowork "should I also delete read AusTender?"
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]
    msg_id    = new_id()
    thread_id = params.thread_id or msg_id   # new thread if none given

    db.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?,0,?)",
        (msg_id, params.from_agent, params.to_agent,
         params.content, thread_id, now_iso()),
    )
    db.commit()

    return json.dumps({"message_id": msg_id, "thread_id": thread_id, "status": "sent"})


# ─────────────────────────────────────────────────────────────────────────────

class GetMessagesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent:       str  = Field(..., description="Agent name to fetch messages for (e.g. 'remy')", min_length=1, max_length=50)
    unread_only: bool = Field(default=True,  description="If true, only return unread messages (default: true)")
    limit:       int  = Field(default=20,    description="Maximum messages to return (1–100)", ge=1, le=100)
    mark_read:   bool = Field(default=True,  description="Automatically mark returned messages as read (default: true)")


@mcp.tool(
    name="relay_get_messages",
    annotations={
        "title": "Get messages for an agent",
        "readOnlyHint": False,   # may mark as read
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def relay_get_messages(params: GetMessagesInput, ctx) -> str:
    """Retrieve messages sent to this agent, optionally marking them as read.

    Call this at the start of a session to check for new instructions or
    updates from the other agent.

    Args:
        params (GetMessagesInput):
            - agent (str): Your agent name
            - unread_only (bool): Only unread messages (default: true)
            - limit (int): Max messages to return (default: 20)
            - mark_read (bool): Auto-mark returned messages as read (default: true)

    Returns:
        str: JSON with list of messages and unread count.

        {
            "agent": str,
            "unread_count": int,
            "messages": [
                {
                    "id": str,
                    "from_agent": str,
                    "content": str,
                    "thread_id": str,
                    "read": bool,
                    "created_at": str  (ISO 8601 UTC)
                }
            ]
        }
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]

    where = "to_agent = ?"
    args: list[Any] = [params.agent]
    if params.unread_only:
        where += " AND read = 0"

    rows = db.execute(
        f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
        args + [params.limit],
    ).fetchall()

    messages = [row_to_dict(r) for r in rows]
    for m in messages:
        m["read"] = bool(m["read"])

    if params.mark_read and messages:
        ids = [m["id"] for m in messages]
        db.execute(
            f"UPDATE messages SET read = 1 WHERE id IN ({','.join('?'*len(ids))})",
            ids,
        )
        db.commit()

    total_unread = db.execute(
        "SELECT COUNT(*) FROM messages WHERE to_agent = ? AND read = 0",
        (params.agent,),
    ).fetchone()[0]

    return json.dumps({
        "agent": params.agent,
        "unread_count": total_unread,
        "messages": messages,
    }, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# TASK TOOLS
# ══════════════════════════════════════════════════════════════════════════════

class PostTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    from_agent:  str            = Field(..., description="Agent delegating the task (e.g. 'cowork')", min_length=1, max_length=50)
    to_agent:    str            = Field(..., description="Agent who should execute the task (e.g. 'remy')", min_length=1, max_length=50)
    task_type:   str            = Field(..., description="Short type identifier, e.g. 'gmail_label', 'gmail_delete', 'web_search'", min_length=1, max_length=100)
    description: str            = Field(..., description="Human-readable description of what needs to be done", min_length=1, max_length=2000)
    params:      dict[str, Any] = Field(default_factory=dict, description="Structured parameters for the task (free-form JSON object)")


@mcp.tool(
    name="relay_post_task",
    annotations={
        "title": "Delegate a task to another agent",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def relay_post_task(params: PostTaskInput, ctx) -> str:
    """Delegate a structured task to another agent for async execution.

    Use this when you want another agent to do something and report back.
    The task is stored with 'pending' status. The receiving agent claims it,
    executes it, and marks it done via relay_update_task.

    Args:
        params (PostTaskInput):
            - from_agent (str): Your agent name
            - to_agent (str): Agent to execute the task
            - task_type (str): Short type key (e.g. 'gmail_label', 'calendar_check')
            - description (str): What needs to be done, in plain English
            - params (dict): Any structured data the executing agent needs

    Returns:
        str: JSON with the new task id.

    Examples:
        - Use when: delegating "label all Radford emails as 4-Personal & Family"
          → task_type='gmail_label', params={'query': 'from:nexus@radford.act.edu.au', 'label': '4-Personal & Family'}
        - Use when: asking Remy to search for something and return findings
          → task_type='research', params={'topic': '...'}
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]
    task_id = new_id()
    ts      = now_iso()

    db.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, params.from_agent, params.to_agent,
         params.task_type, params.description,
         json.dumps(params.params), "pending",
         None, None, ts, ts),
    )
    db.commit()

    return json.dumps({"task_id": task_id, "status": "pending"})


# ─────────────────────────────────────────────────────────────────────────────

class GetTasksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent:  str           = Field(..., description="Agent name — returns tasks assigned TO this agent", min_length=1, max_length=50)
    status: Optional[str] = Field(default=None, description=f"Filter by status. One of: {VALID_STATUSES}. Omit for all.")
    limit:  int           = Field(default=20, description="Max tasks to return (1–100)", ge=1, le=100)


@mcp.tool(
    name="relay_get_tasks",
    annotations={
        "title": "Get tasks assigned to an agent",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def relay_get_tasks(params: GetTasksInput, ctx) -> str:
    """Retrieve tasks assigned to this agent, with optional status filter.

    Call this to discover what work has been delegated to you. Tasks are
    returned newest-first. Use relay_update_task to claim and complete them.

    Args:
        params (GetTasksInput):
            - agent (str): Your agent name
            - status (Optional[str]): Filter — 'pending', 'in_progress', 'done', 'failed', 'needs_clarification'
            - limit (int): Max results (default 20)

    Returns:
        str: JSON with task list.

        {
            "agent": str,
            "pending_count": int,
            "tasks": [
                {
                    "id": str,
                    "from_agent": str,
                    "task_type": str,
                    "description": str,
                    "params": object,
                    "status": str,
                    "result": str | null,
                    "notes": str | null,
                    "created_at": str,
                    "updated_at": str
                }
            ]
        }
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]

    if params.status and params.status not in TASK_STATUSES:
        return f"Error: Invalid status '{params.status}'. Valid values: {VALID_STATUSES}"

    where = "to_agent = ?"
    args: list[Any] = [params.agent]
    if params.status:
        where += " AND status = ?"
        args.append(params.status)

    rows = db.execute(
        f"SELECT * FROM tasks WHERE {where} ORDER BY created_at DESC LIMIT ?",
        args + [params.limit],
    ).fetchall()

    tasks = []
    for r in rows:
        t = row_to_dict(r)
        t["params"] = json.loads(t["params"])
        tasks.append(t)

    pending_count = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE to_agent = ? AND status = 'pending'",
        (params.agent,),
    ).fetchone()[0]

    return json.dumps({
        "agent": params.agent,
        "pending_count": pending_count,
        "tasks": tasks,
    }, indent=2)


# ─────────────────────────────────────────────────────────────────────────────

class UpdateTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str           = Field(..., description="Task ID to update (from relay_get_tasks)", min_length=1, max_length=20)
    status:  str           = Field(..., description=f"New status. One of: {VALID_STATUSES}")
    result:  Optional[str] = Field(default=None, description="Result or output of the task (set when status='done' or 'failed')")
    notes:   Optional[str] = Field(default=None, description="Any additional context, errors, or questions for the delegating agent")


@mcp.tool(
    name="relay_update_task",
    annotations={
        "title": "Update task status and result",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def relay_update_task(params: UpdateTaskInput, ctx) -> str:
    """Update the status and result of a task you're executing.

    Use this to claim a task ('in_progress'), complete it ('done'),
    report failure ('failed'), or ask for clarification ('needs_clarification').
    The delegating agent can then check via relay_get_task_status.

    Args:
        params (UpdateTaskInput):
            - task_id (str): Task ID from relay_get_tasks
            - status (str): New status
            - result (Optional[str]): Summary of what was done / output
            - notes (Optional[str]): Context, errors, or questions

    Returns:
        str: JSON confirming the update.

    Examples:
        - Claim a task before starting: status='in_progress'
        - Report success: status='done', result='Labelled 32 emails as 4-Personal & Family'
        - Report a problem: status='failed', result='Label not found', notes='The label "4-Personal & Family" does not exist in the account'
        - Ask for guidance: status='needs_clarification', notes='Should I include emails older than 2025?'
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]

    if params.status not in TASK_STATUSES:
        return f"Error: Invalid status '{params.status}'. Valid values: {VALID_STATUSES}"

    row = db.execute("SELECT id FROM tasks WHERE id = ?", (params.task_id,)).fetchone()
    if not row:
        return f"Error: Task '{params.task_id}' not found."

    db.execute(
        "UPDATE tasks SET status=?, result=?, notes=?, updated_at=? WHERE id=?",
        (params.status, params.result, params.notes, now_iso(), params.task_id),
    )
    db.commit()

    return json.dumps({
        "task_id": params.task_id,
        "status": params.status,
        "updated": True,
    })


# ─────────────────────────────────────────────────────────────────────────────

class GetTaskStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str = Field(..., description="Task ID to check", min_length=1, max_length=20)


@mcp.tool(
    name="relay_get_task_status",
    annotations={
        "title": "Check the status of a specific task",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def relay_get_task_status(params: GetTaskStatusInput, ctx) -> str:
    """Get the current status and result of a specific task by ID.

    Use this to check whether a task you delegated has been completed,
    and to read the result or any questions the executing agent raised.

    Args:
        params (GetTaskStatusInput):
            - task_id (str): The task ID returned when you called relay_post_task

    Returns:
        str: JSON with full task details including status, result, and notes.
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]

    row = db.execute("SELECT * FROM tasks WHERE id = ?", (params.task_id,)).fetchone()
    if not row:
        return f"Error: Task '{params.task_id}' not found."

    t = row_to_dict(row)
    t["params"] = json.loads(t["params"])
    return json.dumps(t, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED NOTES
# ══════════════════════════════════════════════════════════════════════════════

class PostNoteInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    from_agent: str       = Field(..., description="Agent posting the note", min_length=1, max_length=50)
    content:    str       = Field(..., description="Note content — markdown supported", min_length=1, max_length=8000)
    tags:       list[str] = Field(default_factory=list, description="Tags for categorisation, e.g. ['gmail', 'audit']", max_length=10)


@mcp.tool(
    name="relay_post_note",
    annotations={
        "title": "Post a shared note visible to all agents",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def relay_post_note(params: PostNoteInput, ctx) -> str:
    """Post a shared note that any agent can read.

    Use this for observations, findings, or context that both agents
    should know about — e.g. 'Completed Gmail audit. 312 emails trashed,
    87 labelled. Label 4-Personal & Family now has 94 emails.'

    Args:
        params (PostNoteInput):
            - from_agent (str): Your agent name
            - content (str): Note content
            - tags (list[str]): Optional tags for filtering later

    Returns:
        str: JSON with the new note id.
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]
    note_id = new_id()

    db.execute(
        "INSERT INTO shared_notes VALUES (?,?,?,?,?)",
        (note_id, params.from_agent, params.content,
         json.dumps(params.tags), now_iso()),
    )
    db.commit()

    return json.dumps({"note_id": note_id, "status": "posted"})


# ─────────────────────────────────────────────────────────────────────────────

class GetNotesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tags:  list[str] = Field(default_factory=list, description="Filter by tag (any match). Omit for all notes.")
    limit: int       = Field(default=20, description="Max notes to return (1–100)", ge=1, le=100)


@mcp.tool(
    name="relay_get_notes",
    annotations={
        "title": "Read shared notes from the relay",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def relay_get_notes(params: GetNotesInput, ctx) -> str:
    """Read shared notes posted by any agent.

    Use this to catch up on context, findings, or observations left by
    the other agent between sessions.

    Args:
        params (GetNotesInput):
            - tags (list[str]): Filter by tags (returns notes matching ANY tag)
            - limit (int): Max results (default 20)

    Returns:
        str: JSON list of notes, newest first.
    """
    db: sqlite3.Connection = ctx.request_context.lifespan_state["db"]

    if params.tags:
        # SQLite JSON — match any tag using LIKE
        conditions = " OR ".join(["tags LIKE ?" for _ in params.tags])
        args: list[Any] = [f'%"{t}"%' for t in params.tags] + [params.limit]
        rows = db.execute(
            f"SELECT * FROM shared_notes WHERE {conditions} ORDER BY created_at DESC LIMIT ?",
            args,
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM shared_notes ORDER BY created_at DESC LIMIT ?",
            (params.limit,),
        ).fetchall()

    notes = []
    for r in rows:
        n = row_to_dict(r)
        n["tags"] = json.loads(n["tags"])
        notes.append(n)

    return json.dumps({"count": len(notes), "notes": notes}, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="relay_mcp — inter-agent communication server")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port (default: {DEFAULT_PORT})")
    p.add_argument("--host", type=str, default="127.0.0.1",  help="Bind host (default: 127.0.0.1)")
    p.add_argument("--db",   type=str, default=str(DEFAULT_DB), help="Path to SQLite database file")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    _db_path = Path(args.db)
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"relay_mcp starting on http://{args.host}:{args.port}", file=sys.stderr)
    print(f"Database: {_db_path}", file=sys.stderr)
    print(f"Known agents: {', '.join(KNOWN_AGENTS)}", file=sys.stderr)

    # FastMCP run() on streamable-http typically picks up configuration 
    # from the environment or uses defaults; additional kwargs may cause errors
    # in some SDK versions.
    mcp.run(transport="streamable-http")
