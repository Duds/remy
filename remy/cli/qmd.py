"""qmd — quick memory dump / search CLI.

Usage (via Makefile targets):
    make qmd-search Q="health habits"   # BM25 keyword search via Textual TUI
    make qmd-query  Q="health habits"   # Same (alias)
    make qmd        # Interactive Textual search (no args)

Or directly:
    python -m remy.cli.qmd                    # Interactive Textual search
    python -m remy.cli.qmd search "health habits"   # One-off search, display, exit
    python -m remy.cli.qmd query "health habits"    # Same

Searches facts_fts, goals_fts, and knowledge_fts via Textual DataTable.
"""

from __future__ import annotations

import sys


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    initial_query: str | None = None
    exit_after_search = False

    if args and args[0] in ("search", "query"):
        if len(args) >= 2:
            initial_query = " ".join(args[1:])
            exit_after_search = True
        # else: search/query with no query → interactive
    elif args:
        initial_query = " ".join(args)
        exit_after_search = True

    from .search_screen import QmdSearchApp

    app = QmdSearchApp(initial_query=initial_query, exit_after_search=exit_after_search)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
