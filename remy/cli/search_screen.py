"""Textual search screen for qmd memory search."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import DataTable, Footer, Input, Static


async def run_qmd_search(query: str) -> list[dict[str, Any]]:
    """
    Run BM25 search over facts_fts, goals_fts, knowledge_fts.
    Returns list of dicts with source, type, confidence, content.
    """
    import aiosqlite

    from ..config import settings

    query = query.strip()
    if not query:
        return []

    tokens = query.split()
    fts_query = " OR ".join(f'"{t}"' for t in tokens if t)
    results: list[dict[str, Any]] = []

    db_path = settings.db_path
    try:
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row

            for stmt, params in [
                (
                    """
                    SELECT k.id, k.entity_type AS type, k.content,
                           ROUND(k.confidence, 2) AS confidence,
                           'knowledge' AS source
                    FROM knowledge_fts
                    JOIN knowledge k ON k.id = knowledge_fts.rowid
                    WHERE knowledge_fts MATCH ?
                      AND k.superseded_by IS NULL
                    ORDER BY bm25(knowledge_fts)
                    LIMIT 10
                    """,
                    (fts_query,),
                ),
                (
                    """
                    SELECT f.id, f.category AS type, f.content,
                           ROUND(f.confidence, 2) AS confidence,
                           'fact' AS source
                    FROM facts_fts
                    JOIN facts f ON f.id = facts_fts.rowid
                    WHERE facts_fts MATCH ?
                    ORDER BY bm25(facts_fts)
                    LIMIT 10
                    """,
                    (fts_query,),
                ),
                (
                    """
                    SELECT g.id, g.status AS type, g.title AS content,
                           1.0 AS confidence,
                           'goal' AS source
                    FROM goals_fts
                    JOIN goals g ON g.id = goals_fts.rowid
                    WHERE goals_fts MATCH ?
                    ORDER BY bm25(goals_fts)
                    LIMIT 5
                    """,
                    (fts_query,),
                ),
            ]:
                try:
                    cursor = await conn.execute(stmt, params)
                    results += [dict(r) for r in await cursor.fetchall()]
                except Exception:
                    pass
    except Exception:
        raise
    return results


class QmdSearchApp(App[None]):
    """Textual app for qmd memory search."""

    CSS = """
    #input_container {
        height: auto;
        padding: 1 2;
        border: solid $border;
    }
    #status {
        height: 1;
        padding: 0 2;
    }
    #table_container {
        height: 1fr;
        padding: 1 2;
        border: solid $border;
    }
    DataTable {
        height: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, initial_query: str | None = None, exit_after_search: bool = False):
        super().__init__()
        self._initial_query = initial_query
        self._exit_after_search = exit_after_search

    def compose(self) -> ComposeResult:
        yield Container(
            Vertical(
                Input(
                    placeholder="Search query (Enter to search)",
                    id="search_input",
                ),
                Static("", id="status"),
                id="input_container",
            ),
            Container(
                DataTable(id="results_table"),
                id="table_container",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Remy Memory Search (qmd)"
        table = self.query_one("#results_table", DataTable)
        table.add_columns("source", "type", "conf", "content")
        table.cursor_type = "row"
        if self._initial_query:
            inp = self.query_one("#search_input", Input)
            inp.value = self._initial_query
            coro = self._do_search(self._initial_query)()
            self.run_worker(coro, exclusive=True)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        await self._do_search(query)()

    async def _do_search(self, query: str):
        async def run():
            status = self.query_one("#status", Static)
            status.update("Searching…")
            try:
                results = await run_qmd_search(query)
                table = self.query_one("#results_table", DataTable)
                table.clear()
                for r in results:
                    content = str(r.get("content", ""))
                    if len(content) > 80:
                        content = content[:77] + "…"
                    table.add_row(
                        str(r.get("source", "")),
                        str(r.get("type", "")),
                        str(r.get("confidence", "")),
                        content,
                    )
                status.update(f"{len(results)} result(s) for: {query!r}")
                if self._exit_after_search:
                    await asyncio.sleep(0.5)
                    self.exit(0)
            except Exception as e:
                status.update(f"[red]Error: {e}[/]")
                if self._exit_after_search:
                    self.exit(1)

        return run
