"""
Entry point for Remy TUI.
Run with: python -m remy.tui  or  make tui
"""

import sys

from .screen import RemyTUIApp


def main() -> None:
    app = RemyTUIApp()
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
