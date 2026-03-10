"""
Chat screen for Remy TUI.
Scrollable history, input line, and status line for tool use (US-terminal-ui).
"""

from __future__ import annotations

import asyncio
import signal

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Footer, Input, RichLog, Static

from ..bot.session import SessionManager

from ..ai.claude_client import (
    TextChunk,
    ToolStatusChunk,
    ToolTurnComplete,
)
from .runner import (
    TUI_USER_ID,
    TUIDeps,
    build_tui_deps,
    run_chat_turn,
)


class RemyTUIApp(App[None]):
    """Terminal UI for chatting with Remy. Uses same pipeline as Telegram (no bot)."""

    CSS = """
    #history_container {
        height: 1fr;
        padding: 1 2;
        border: solid $border;
        background: $surface;
    }

    #history {
        height: auto;
        min-height: 100%;
        padding: 0 1;
        scrollbar-gutter: stable;
    }

    #status_line {
        height: 1;
        padding: 0 2;
        background: $primary;
        color: $text;
    }

    #input_container {
        height: auto;
        min-height: 3;
        max-height: 5;
        padding: 1 2;
        border-top: solid $primary;
    }

    Input {
        width: 100%;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "cancel", "Cancel"),
        ("tab", "focus_input", "Focus input"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._streaming = False
        self._deps: TUIDeps | None = None
        self._stream_started = False
        self._stream_buffer = (
            ""  # Accumulate chunks; write line-by-line (RichLog has no end="")
        )

    def compose(self) -> ComposeResult:
        yield Container(
            VerticalScroll(
                RichLog(markup=True, highlight=True, id="history"),
                id="history_container",
            ),
            Static("", id="status_line"),
            Container(
                Input(
                    placeholder="Message (Enter to send, Shift+Enter newline)",
                    id="input",
                ),
                id="input_container",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Remy"
        self.sub_title = "Terminal UI"
        # Keep focus on input: history area is not focusable so keys go to Input
        self.query_one("#history_container", VerticalScroll).can_focus = False
        self.query_one("#history", RichLog).can_focus = False
        self.query_one("#input", Input).focus()
        self._install_signal_handlers()

    def _install_signal_handlers(self) -> None:
        """Handle SIGINT/SIGTERM so Ctrl+C exits cleanly without thread-shutdown traceback."""

        def do_exit() -> None:
            self.exit(0)

        try:
            loop = asyncio.get_running_loop()
            if getattr(loop, "add_signal_handler", None) is not None:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    try:
                        loop.add_signal_handler(sig, do_exit)
                    except (OSError, RuntimeError):
                        pass
                return
        except RuntimeError:
            pass
        # Fallback when add_signal_handler not available (e.g. Windows)
        try:
            signal.signal(signal.SIGINT, lambda s, f: do_exit())
        except (ValueError, OSError):
            pass
        try:
            signal.signal(signal.SIGTERM, lambda s, f: do_exit())
        except (ValueError, OSError, AttributeError):
            pass

    def set_status(self, text: str) -> None:
        """Update the status line (e.g. 'Using get_current_time…')."""
        self.query_one("#status_line", Static).update(text)

    def append_history(self, text: str, *, role: str = "info") -> None:
        """Append a line to the conversation history. role: 'user' | 'assistant' | 'info'."""
        log = self.query_one("#history", RichLog)
        if role == "user":
            log.write(f"[bold blue]You:[/] {text}")
        elif role == "assistant":
            log.write(f"[bold green]Remy:[/] {text}")
        else:
            log.write(text)

    def append_stream_chunk(self, chunk: str) -> None:
        """Append a streaming text chunk; flush complete lines (RichLog.write has no end=)."""
        self._stream_buffer += chunk
        log = self.query_one("#history", RichLog)
        while "\n" in self._stream_buffer:
            line, _, self._stream_buffer = self._stream_buffer.partition("\n")
            if self._stream_started:
                log.write(line)
            else:
                log.write(f"[bold green]Remy:[/] {line}")
                self._stream_started = True

    def finalize_stream(self) -> None:
        """Flush any remaining buffer and end the assistant reply."""
        if self._stream_buffer:
            log = self.query_one("#history", RichLog)
            if self._stream_started:
                log.write(self._stream_buffer)
            else:
                log.write(f"[bold green]Remy:[/] {self._stream_buffer}")
            self._stream_buffer = ""
        self._stream_started = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter: send message. Shift+Enter is newline (Input default)."""
        value = event.value
        if not value.strip():
            return
        self.append_history(value, role="user")
        self.query_one("#input", Input).clear()
        self._streaming = True
        self.set_status("Thinking…")
        self.run_worker(self._handle_send(value), exclusive=True)

    def _apply_stream_event(self, ev: object) -> None:
        """Apply one stream event to the UI (worker runs on app thread — update directly)."""
        if isinstance(ev, TextChunk):
            self.append_stream_chunk(ev.text)
        elif isinstance(ev, ToolStatusChunk):
            self.set_status(f"Using {ev.tool_name}…")
        elif isinstance(ev, ToolTurnComplete):
            pass  # status stays until next tool or final text

    def _end_reply(self) -> None:
        """End streaming reply and reset state."""
        self.finalize_stream()
        self._streaming = False
        self.set_status("")
        self.query_one("#input", Input).focus()

    async def _handle_send(self, text: str) -> None:
        """Run pipeline: build deps, run_chat_turn, feed events to TUI."""
        if self._deps is None:
            self.set_status("Loading…")
            try:
                self._deps = await build_tui_deps()
            except Exception as exc:
                self._show_error(str(exc))
                self._end_reply()
                return
        session_key = SessionManager.get_session_key(TUI_USER_ID, None)
        assert self._deps is not None

        async def on_event(ev: object) -> None:
            self._apply_stream_event(ev)
            await asyncio.sleep(0)  # Yield so the UI can refresh during streaming

        try:
            self.set_status("Thinking…")
            self._stream_started = False
            self._stream_buffer = ""
            await run_chat_turn(
                self._deps,
                TUI_USER_ID,
                session_key,
                text,
                on_event=on_event,
            )
        except Exception as exc:
            self._show_error(f"Sorry, something went wrong: {exc}")
        finally:
            self._end_reply()

    def _show_error(self, message: str) -> None:
        """Show error in history and reset state."""
        self.append_history(f"[red]{message}[/]", role="info")
        self._stream_started = False
        self._streaming = False
        self.set_status("")
        self.query_one("#input", Input).focus()

    def action_cancel(self) -> None:
        """Cancel in-flight request via SessionManager.request_cancel."""
        if self._streaming:
            self.set_status("Cancelling…")
            if self._deps is not None:
                self._deps.session_manager.request_cancel(TUI_USER_ID)
        self._streaming = False
        self.set_status("")
        self.query_one("#input", Input).focus()

    def action_focus_input(self) -> None:
        """Move focus to the message input."""
        self.query_one("#input", Input).focus()

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()
