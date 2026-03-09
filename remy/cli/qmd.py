"""qmd — quick memory dump / search CLI.

Usage (via Makefile targets):
    make qmd-search Q="health habits"   # BM25 keyword search over facts + knowledge
    make qmd-query  Q="health habits"   # Same (alias)

Or directly:
    python -m remy.cli.qmd search "health habits"
    python -m remy.cli.qmd query "health habits"

Searches facts_fts, goals_fts, and knowledge_fts tables and prints a
formatted table of results. Reads remy.db from the configured data_dir.
"""

from __future__ import annotations

import asyncio
import sys


async def _run_search(query: str) -> None:
    import aiosqlite

    from ..config import settings

    db_path = settings.db_path
    query = query.strip()
    if not query:
        print("Usage: qmd search <query>", file=sys.stderr)
        sys.exit(1)

    # Sanitise query for FTS5 (wrap tokens in double-quotes)
    tokens = query.split()
    fts_query = " OR ".join(f'"{t}"' for t in tokens if t)

    results: list[dict] = []

    try:
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row

            # Search knowledge_fts
            try:
                cursor = await conn.execute(
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
                )
                results += [dict(r) for r in await cursor.fetchall()]
            except Exception as e:
                print(f"  [knowledge search error: {e}]", file=sys.stderr)

            # Search facts_fts
            try:
                cursor = await conn.execute(
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
                )
                results += [dict(r) for r in await cursor.fetchall()]
            except Exception as e:
                print(f"  [facts search error: {e}]", file=sys.stderr)

            # Search goals_fts
            try:
                cursor = await conn.execute(
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
                )
                results += [dict(r) for r in await cursor.fetchall()]
            except Exception as e:
                print(f"  [goals search error: {e}]", file=sys.stderr)

    except Exception as e:
        print(f"Could not open database {db_path!r}: {e}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print(f"No results for: {query!r}")
        return

    # Print table
    col_widths = {"source": 10, "type": 16, "confidence": 6, "content": 60}
    header = (
        f"{'source':<{col_widths['source']}}  "
        f"{'type':<{col_widths['type']}}  "
        f"{'conf':<{col_widths['confidence']}}  "
        f"{'content'}"
    )
    sep = "-" * (col_widths["source"] + col_widths["type"] + col_widths["confidence"] + col_widths["content"] + 8)
    print(f"\n{header}")
    print(sep)
    for r in results:
        content_preview = str(r.get("content", ""))
        if len(content_preview) > col_widths["content"]:
            content_preview = content_preview[: col_widths["content"] - 1] + "…"
        print(
            f"{str(r.get('source','')):<{col_widths['source']}}  "
            f"{str(r.get('type','')):<{col_widths['type']}}  "
            f"{str(r.get('confidence','')):<{col_widths['confidence']}}  "
            f"{content_preview}"
        )
    print(f"\n{len(results)} result(s) for: {query!r}\n")


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    # Both 'search' and 'query' do the same BM25 search
    if args[0] in ("search", "query") and len(args) >= 2:
        query = " ".join(args[1:])
    elif args[0] not in ("search", "query"):
        # Treat first arg as the query directly
        query = " ".join(args)
    else:
        print("Usage: qmd search <query>  or  qmd query <query>", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run_search(query))


if __name__ == "__main__":
    main()
