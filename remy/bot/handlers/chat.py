"""
Chat and message handlers.

Contains the main message handler, voice/photo/document handlers, and streaming logic.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import time
from datetime import datetime
from typing import TYPE_CHECKING

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from .base import (
    reject_unauthorized,
    _build_message_from_turn,
    _trim_messages_to_budget,
    _get_working_msg,
    MessageRotator,
    _rate_limiter,
    _task_start_times,
    _pending_writes,
    _user_active_requests,
    _user_request_lock,
    TASK_TIMEOUT_SECONDS,
    _TOOL_TURN_PREFIX,
    _sanitize_messages_for_claude,
    apply_completion_reaction,
)
from .callbacks import make_step_limit_keyboard, make_suggested_actions_keyboard
from ..session import SessionManager
from ..streaming import stream_to_telegram
from ...ai.claude_client import (
    AnthropicOverloadFallbackAvailable,
    StepLimitReached,
    TextChunk,
    ToolResultChunk,
    ToolStatusChunk,
    ToolTurnComplete,
)
from ...ai.input_validator import (
    validate_message_input,
    sanitize_memory_injection,
    sanitize_file_path,
)
from ...analytics.timing import RequestTiming, PhaseTimer
from ...config import get_settings, settings
from ...constants import SHOPPING_KEYWORDS, DEADLINE_KEYWORDS
from ...diagnostics import is_diagnostics_trigger
from ...exceptions import ServiceUnavailableError
from ...hooks import HookEvents, hook_manager
from ...memory.compaction import get_compaction_service
from ...memory.facts import extract_and_store_facts
from ...memory.goals import extract_and_store_goals
from ...models import ConversationTurn
from ...utils.concurrency import get_extraction_runner
from ...utils.telegram_formatting import format_telegram_message

if TYPE_CHECKING:
    from ...ai.router import ModelRouter
    from ...ai.tool_registry import ToolRegistry
    from ...memory.conversations import ConversationStore
    from ...memory.facts import FactExtractor, FactStore
    from ...memory.goals import GoalExtractor, GoalStore
    from ...memory.injector import MemoryInjector
    from ...memory.database import DatabaseManager
    from ...voice.transcriber import VoiceTranscriber
    from ...google.gmail import GmailClient
    from ...diagnostics import DiagnosticsRunner

logger = logging.getLogger(__name__)


def make_chat_handlers(
    *,
    session_manager: SessionManager,
    router: "ModelRouter",
    conv_store: "ConversationStore",
    claude_client=None,
    fact_extractor: "FactExtractor | None" = None,
    fact_store: "FactStore | None" = None,
    goal_extractor: "GoalExtractor | None" = None,
    goal_store: "GoalStore | None" = None,
    memory_injector: "MemoryInjector | None" = None,
    voice_transcriber: "VoiceTranscriber | None" = None,
    db: "DatabaseManager | None" = None,
    tool_registry: "ToolRegistry | None" = None,
    google_gmail: "GmailClient | None" = None,
    diagnostics_runner: "DiagnosticsRunner | None" = None,
    scheduler_ref: dict | None = None,
    proactive_scheduler=None,
):
    """
    Factory that returns chat and message handlers.

    Returns a dict of handler_name -> handler_function.
    """

    async def _ensure_user(user) -> None:
        """Upsert the Telegram user into the users table (satisfies FK constraint)."""
        if db is None:
            return
        try:
            await db.upsert_user(
                user.id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
            )
        except Exception as exc:
            logger.warning("upsert_user failed: %s", exc)

    async def _run_diagnostics(update: Update) -> None:
        """Run self-diagnostics: check_status + get_logs (Feature 34)."""
        if update.message is None or update.effective_user is None:
            return
        await update.message.chat.send_action(ChatAction.TYPING)

        user_id = update.effective_user.id

        try:
            if tool_registry is not None:
                # Lightweight path: check_status + get_logs (Bug 34 spec)
                status = await tool_registry.dispatch("check_status", {}, user_id)
                logs = await tool_registry.dispatch(
                    "get_logs",
                    {"mode": "errors", "since": "startup"},
                    user_id,
                )
                output = f"*Self-diagnostics*\n\n{status}\n\n{logs}"
            else:
                # Fallback: full DiagnosticsRunner when tool_registry unavailable
                from ...diagnostics import DiagnosticsRunner, format_diagnostics_output

                scheduler = (
                    scheduler_ref.get("proactive_scheduler")
                    if scheduler_ref
                    else proactive_scheduler
                )
                runner = DiagnosticsRunner(
                    db=db,
                    embeddings=None,
                    knowledge_store=None,
                    conv_store=conv_store,
                    claude_client=claude_client,
                    mistral_client=None,
                    moonshot_client=None,
                    ollama_client=None,
                    tool_registry=tool_registry,
                    scheduler=scheduler,
                    settings=get_settings(),
                )
                if diagnostics_runner is not None:
                    runner = diagnostics_runner
                result = await runner.run_all()
                output = format_diagnostics_output(result, settings.scheduler_timezone)
                logger.info(
                    "Diagnostics complete: %s (%d checks, %.0fms)",
                    result.overall_status.value,
                    len(result.checks),
                    result.total_duration_ms,
                )

            if len(output) > 4000:
                output = output[:4000] + "\n\n_(truncated)_"

            await update.message.reply_text(output, parse_mode="Markdown")

        except Exception as e:
            logger.exception("Diagnostics failed")
            await update.message.reply_text(
                f"❌ Diagnostics failed: {type(e).__name__}: {e}"
            )

    async def _stream_with_tools_path(
        user_id: int,
        text: str,
        messages: list[dict],
        system_prompt: str,
        session_key: str,
        sent,
        chat_id: int | None = None,
        message_id: int | None = None,
        bot=None,
        timing: RequestTiming | None = None,
    ) -> None:
        """Tool-aware streaming path using native Anthropic function calling."""
        current_display: list[str] = []
        tool_turns: list[tuple[list[dict], list[dict]]] = []
        step_limit_reached = False

        in_tool_turn = False
        last_edit_len = 0
        rotator = MessageRotator(sent, user_id)
        rotator_stopped = False

        async def _flush_display(final: bool = False, reply_markup=None) -> None:
            nonlocal last_edit_len
            full = "".join(current_display)
            suffix = "" if final else " …"
            candidate = full + suffix

            if not candidate.strip() and not (final and reply_markup):
                return

            if len(full) > last_edit_len + 50 or final:
                truncated = candidate[:4000] if candidate.strip() else "✓"
                kwargs = {}
                if final and reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                try:
                    await sent.edit_text(
                        format_telegram_message(truncated),
                        parse_mode="MarkdownV2",
                        **kwargs,
                    )
                    last_edit_len = len(full)
                except BadRequest as e:
                    if "message is not modified" in str(e).lower():
                        return  # already up to date — don't overwrite with plain text
                    # Real MarkdownV2 parse error — fall back to plain text
                    try:
                        await sent.edit_text(truncated, **kwargs)
                        last_edit_len = len(full)
                    except Exception as e2:
                        logger.debug("Message edit failed (flood control): %s", e2)
                except Exception as e:
                    logger.debug("Message edit failed (flood control): %s", e)

        def _is_transient_stream_exc(exc: Exception) -> bool:
            txt = str(exc).lower()
            return any(
                c in txt
                for c in (
                    "incomplete chunked read",
                    "peer closed connection",
                    "connection reset by peer",
                    "remote end closed connection",
                    "unexpected eof",
                )
            )

        rotator.start()
        from ...models import TokenUsage
        from ...analytics.call_log import log_api_call

        stream_model = None  # None = default; set on AnthropicOverloadFallbackAvailable
        for _attempt in range(2):
            try:
                usage = TokenUsage()
                t0 = time.monotonic()
                # Reset streaming state so a retry starts clean (Bug 13)
                current_display = []
                tool_turns = []
                step_limit_reached = False
                in_tool_turn = False
                last_edit_len = 0

                ttft_recorded = False
                ttft_timer = PhaseTimer()
                ttft_timer.start()
                tool_exec_total_ms = 0
                tool_exec_start: float | None = None

                await hook_manager.emit(
                    HookEvents.LLM_INPUT,
                    {
                        "user_id": user_id,
                        "message_count": len(messages),
                        "system_prompt_length": len(system_prompt),
                    },
                )

                # Sanitize to prevent orphaned tool_use_id (Bug 36)
                safe_messages = _sanitize_messages_for_claude(messages)

                async for event in claude_client.stream_with_tools(
                    messages=safe_messages,
                    tool_registry=tool_registry,
                    user_id=user_id,
                    system=system_prompt,
                    usage_out=usage,
                    chat_id=chat_id,
                    message_id=message_id,
                    model=stream_model,
                ):
                    if not ttft_recorded:
                        ttft_timer.stop()
                        ttft_recorded = True

                    if not rotator_stopped:
                        await rotator.stop()
                        rotator_stopped = True
                    if session_manager.is_cancelled(user_id):
                        shown = "".join(current_display)
                        try:
                            await sent.edit_text(
                                (shown + "\n\n_[cancelled]_").strip(),
                                parse_mode="Markdown",
                            )
                        except Exception as e:
                            logger.debug("Failed to edit cancelled message: %s", e)
                        return

                    if isinstance(event, TextChunk):
                        if in_tool_turn:
                            logger.debug(
                                "Suppressing in-tool TextChunk (%d chars) for user %d",
                                len(event.text),
                                user_id,
                            )
                        else:
                            current_display.append(event.text)
                            if len("".join(current_display)) - last_edit_len >= 200:
                                await _flush_display()

                    elif isinstance(event, ToolStatusChunk):
                        in_tool_turn = True
                        tool_exec_start = time.monotonic()
                        await hook_manager.emit(
                            HookEvents.BEFORE_TOOL_CALL,
                            {"user_id": user_id, "tool_name": event.tool_name},
                        )
                        try:
                            await sent.edit_text(
                                f"_⚙️ Using {event.tool_name}…_",
                                parse_mode="Markdown",
                            )
                        except Exception as e:
                            logger.debug("Failed to update tool status message: %s", e)

                    elif isinstance(event, ToolResultChunk):
                        pass

                    elif isinstance(event, ToolTurnComplete):
                        in_tool_turn = False
                        tool_duration_ms = 0
                        if tool_exec_start is not None:
                            tool_duration_ms = int(
                                (time.monotonic() - tool_exec_start) * 1000
                            )
                            tool_exec_total_ms += tool_duration_ms
                            tool_exec_start = None
                        await hook_manager.emit(
                            HookEvents.AFTER_TOOL_CALL,
                            {"user_id": user_id, "duration_ms": tool_duration_ms},
                        )
                        tool_turns.append(
                            (event.assistant_blocks, event.tool_result_blocks)
                        )
                        current_display = []
                        last_edit_len = 0

                    elif isinstance(event, StepLimitReached):
                        step_limit_reached = True

                break  # stream completed successfully

            except AnthropicOverloadFallbackAvailable as e:
                # Retry once with fallback model (US-anthropic-overload-fallback)
                stream_model = e.fallback_model
                logger.info(
                    "anthropic_overload_fallback: retrying with %s for user %d",
                    stream_model,
                    user_id,
                )
                continue

            except Exception as exc:
                if _attempt == 0 and _is_transient_stream_exc(exc):
                    logger.warning(
                        "Transient stream error for user %d (attempt 1), retrying: %s",
                        user_id,
                        exc,
                    )
                    await asyncio.sleep(1.0)
                    continue
                if not rotator_stopped:
                    await rotator.stop()
                err_str = str(exc)
                if "overloaded_error" in err_str or "overloaded" in err_str.lower():
                    logger.warning(
                        "stream_with_tools overloaded for user %d: %s", user_id, exc
                    )
                    user_msg = "Anthropic's API is busy right now. I'll keep trying, or you can try again in a few minutes."
                else:
                    logger.error(
                        "stream_with_tools error for user %d: %s", user_id, exc
                    )
                    user_msg = f"Sorry, something went wrong: {exc}"
                try:
                    await sent.edit_text(user_msg)
                except Exception:
                    pass
                return

        await hook_manager.emit(
            HookEvents.LLM_OUTPUT,
            {
                "user_id": user_id,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "tool_turns_count": len(tool_turns),
            },
        )

        final_text_preview = "".join(current_display).strip()[:100]
        await hook_manager.emit(
            HookEvents.MESSAGE_SENDING,
            {"user_id": user_id, "text_preview": final_text_preview},
        )

        # Extract suggested_actions from any suggest_actions tool call in tool_turns
        suggested_actions = None
        for assistant_blocks, _ in tool_turns:
            for block in assistant_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if block.get("name") == "suggest_actions":
                        actions = (block.get("input") or {}).get("actions")
                        if isinstance(actions, list) and actions:
                            suggested_actions = actions
                            break

        # Step-limit keyboard takes precedence when max_iterations was hit (US-step-limit-buttons)
        reply_markup: InlineKeyboardMarkup | None
        if step_limit_reached:
            reply_markup = make_step_limit_keyboard()
        elif suggested_actions:
            reply_markup = make_suggested_actions_keyboard(suggested_actions, user_id)
        else:
            reply_markup = None

        # US-emoji-reactions-feedback: apply 🤩 on user's message when allowlisted tool completes
        if bot is not None and tool_turns:
            await apply_completion_reaction(bot, chat_id, message_id, tool_turns)

        # Bug 35/42: When the only tool is react_to_message and there's no text,
        # delete the status message — the emoji reaction is the complete response.
        # Do this BEFORE _flush_display to avoid any "✓" edit (Bug 42 regression).
        _REACTION_ONLY_TOOLS = frozenset({"react_to_message"})
        tool_names = set()
        for assistant_blocks, _ in tool_turns:
            for block in assistant_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_names.add(block.get("name"))
        final_text_accum = "".join(current_display).strip()
        if tool_turns and not final_text_accum and tool_names == _REACTION_ONLY_TOOLS:
            try:
                await sent.delete()
            except BadRequest as e:
                logger.debug("Could not delete react_to_message status message: %s", e)
            except Exception as e:
                logger.debug("Could not delete react_to_message status message: %s", e)
        else:
            await _flush_display(final=True, reply_markup=reply_markup)
            # Retry once if there's text to display — the first attempt may have failed
            # due to a transient Telegram disconnect, leaving the " …" suffix showing.
            if final_text_accum:
                await asyncio.sleep(0.3)
                await _flush_display(final=True, reply_markup=reply_markup)
            elif tool_turns:
                try:
                    await sent.edit_text("✓", reply_markup=reply_markup)
                except Exception:
                    pass

        streaming_ms = (
            int((time.monotonic() - t0) * 1000)
            - ttft_timer.elapsed_ms
            - tool_exec_total_ms
        )

        persistence_start = time.monotonic()
        for assistant_blocks, result_blocks in tool_turns:
            asst_serialised = _TOOL_TURN_PREFIX + json.dumps(assistant_blocks)
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(
                    role="assistant",
                    content=asst_serialised,
                    model_used=f"anthropic:{settings.model_complex}",
                ),
            )
            usr_serialised = _TOOL_TURN_PREFIX + json.dumps(result_blocks)
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(role="user", content=usr_serialised),
            )

        final_text = "".join(current_display).strip()
        if final_text:
            await conv_store.append_turn(
                user_id,
                session_key,
                ConversationTurn(
                    role="assistant",
                    content=final_text,
                    model_used=f"anthropic:{settings.model_complex}",
                ),
            )

        persistence_ms = int((time.monotonic() - persistence_start) * 1000)

        if timing is not None:
            timing.ttft_ms = ttft_timer.elapsed_ms
            timing.tool_execution_ms = tool_exec_total_ms
            timing.streaming_ms = max(0, streaming_ms)
            timing.persistence_ms = persistence_ms

        latency_ms = int((time.monotonic() - t0) * 1000)
        if db is not None:
            from ...analytics.call_log import log_api_call

            asyncio.create_task(
                log_api_call(
                    db,
                    user_id=user_id,
                    session_key=session_key,
                    provider="anthropic",
                    model=settings.model_complex,
                    category="tool_use",
                    call_site="tool_use",
                    usage=usage,
                    latency_ms=latency_ms,
                    fallback=False,
                    timing=timing,
                )
            )

    async def _process_text_input(
        user_id: int,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ):
        """Process text input (from message or transcribed voice) and generate response."""
        if update.message is None or update.effective_user is None:
            return
        if not text.strip():
            return

        thread_id: int | None = getattr(update.message, "message_thread_id", None)

        async with _user_request_lock:
            current_count = _user_active_requests.get(user_id, 0)
            if current_count >= settings.max_concurrent_per_user:
                await update.message.reply_text(
                    "⏳ Please wait — I'm still processing your previous message."
                )
                return
            _user_active_requests[user_id] = current_count + 1

        try:
            await _process_text_input_inner(user_id, text, update, context, thread_id)
        finally:
            async with _user_request_lock:
                _user_active_requests[user_id] = (
                    _user_active_requests.get(user_id, 1) - 1
                )
                if _user_active_requests[user_id] <= 0:
                    _user_active_requests.pop(user_id, None)

    async def _process_text_input_inner(
        user_id: int,
        text: str,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        thread_id: int | None,
    ):
        """Inner implementation of text processing after concurrency check."""
        if update.message is None or update.effective_user is None:
            return
        allowed, rate_limit_reason = _rate_limiter.is_allowed(user_id)
        if not allowed:
            await update.message.reply_text(f"⏱️ {rate_limit_reason}")
            return

        valid, validation_reason = validate_message_input(text)
        if not valid:
            await update.message.reply_text(f"❌ {validation_reason}")
            return

        if is_diagnostics_trigger(text):
            await _run_diagnostics(update)
            return

        if user_id in _task_start_times:
            elapsed = time.time() - _task_start_times[user_id]
            if elapsed > TASK_TIMEOUT_SECONDS:
                _task_start_times.pop(user_id, None)
                session_manager.request_cancel(user_id)
                await update.message.reply_text(
                    "⏰ Previous task exceeded 2-hour limit and was cancelled. Starting fresh."
                )

        _task_start_times[user_id] = time.time()

        await hook_manager.emit(
            HookEvents.SESSION_START,
            {"user_id": user_id, "text": text, "timestamp": time.time()},
        )

        await _ensure_user(update.effective_user)
        async with session_manager.get_lock(user_id):
            session_manager.clear_cancel(user_id)
            session_key = SessionManager.get_session_key(user_id, thread_id)

            if user_id in _pending_writes:
                pending_path = _pending_writes.pop(user_id)
                sanitized, err = sanitize_file_path(
                    pending_path, settings.allowed_base_dirs
                )
                if err or sanitized is None:
                    await update.message.reply_text(f"❌ Write cancelled: {err}")
                else:
                    try:
                        backup_msg = ""
                        if os.path.exists(sanitized):
                            backup_path = sanitized + ".bak"
                            shutil.copy2(sanitized, backup_path)
                            backup_msg = f"\n_(Backup saved as `{backup_path}`)_"
                        with open(sanitized, "w", encoding="utf-8") as f:
                            f.write(text)
                        await update.message.reply_text(
                            f"✅ Wrote {len(text)} characters to `{sanitized}`{backup_msg}",
                            parse_mode="Markdown",
                        )
                    except Exception as e:
                        await update.message.reply_text(f"❌ Failed to write file: {e}")
                _task_start_times.pop(user_id, None)
                return

            await update.message.chat.send_action(ChatAction.TYPING)

            req_timing = RequestTiming()

            history_start = time.monotonic()
            recent = await conv_store.get_recent_turns(
                user_id, session_key, limit=settings.compaction_keep_recent_messages
            )
            messages = [_build_message_from_turn(t) for t in recent]
            while messages:
                first = messages[0]
                if first["role"] == "user" and isinstance(first["content"], str):
                    break
                messages.pop(0)
            messages = _trim_messages_to_budget(messages)
            messages.append({"role": "user", "content": text})
            req_timing.history_load_ms = int((time.monotonic() - history_start) * 1000)

            user_turn = ConversationTurn(role="user", content=text)
            await conv_store.append_turn(user_id, session_key, user_turn)

            local_hour: int | None = None
            try:
                import zoneinfo

                tz = zoneinfo.ZoneInfo(settings.scheduler_timezone)
                local_hour = datetime.now(tz).hour
            except Exception as e:
                logger.debug("Timezone detection failed, using None: %s", e)

            await hook_manager.emit(
                HookEvents.BEFORE_PROMPT_BUILD,
                {"user_id": user_id, "text": text, "messages": messages},
            )

            memory_start = time.monotonic()
            system_prompt = settings.soul_md
            if memory_injector is not None:
                try:
                    system_prompt = await memory_injector.build_system_prompt(
                        user_id, text, settings.soul_md, local_hour=local_hour
                    )
                    system_prompt = sanitize_memory_injection(system_prompt)
                except Exception as e:
                    logger.error("Memory injection failed, using base prompt: %s", e)
            req_timing.memory_injection_ms = int(
                (time.monotonic() - memory_start) * 1000
            )

            text_lower = text.lower()
            if any(kw in text_lower for kw in SHOPPING_KEYWORDS):
                try:
                    grocery_file = settings.grocery_list_file
                    if os.path.exists(grocery_file):
                        with open(grocery_file) as _gf:
                            items = [ln.strip() for ln in _gf if ln.strip()]
                        if items:
                            item_list = "\n".join(f"- {i}" for i in items)
                            system_prompt += (
                                f"\n\n<hint>The user mentioned shopping. "
                                f"Their current grocery list:\n{item_list}\n"
                                f"Offer to reference or update it if helpful.</hint>"
                            )
                except Exception as e:
                    logger.debug("Failed to inject grocery list hint: %s", e)
            if any(kw in text_lower for kw in DEADLINE_KEYWORDS):
                system_prompt += (
                    "\n\n<hint>The user may be mentioning a deadline or time-sensitive task. "
                    "If relevant, offer to create a calendar event using /schedule.</hint>"
                )

            sent = await update.message.reply_text(_get_working_msg())

            await hook_manager.emit(
                HookEvents.BEFORE_MODEL_RESOLVE,
                {
                    "user_id": user_id,
                    "text": text,
                    "has_tool_registry": tool_registry is not None,
                },
            )

            if tool_registry is not None and claude_client is not None:
                await _stream_with_tools_path(
                    user_id=user_id,
                    text=text,
                    messages=messages,
                    system_prompt=system_prompt,
                    session_key=session_key,
                    sent=sent,
                    chat_id=update.effective_chat.id if update.effective_chat else None,
                    message_id=update.message.message_id if update.message else None,
                    bot=context.bot,
                    timing=req_timing,
                )
                logger.debug(
                    "Request timing for user %d: history=%dms, memory=%dms, ttft=%dms, "
                    "tools=%dms, stream=%dms, persist=%dms, total=%dms",
                    user_id,
                    req_timing.history_load_ms,
                    req_timing.memory_injection_ms,
                    req_timing.ttft_ms,
                    req_timing.tool_execution_ms,
                    req_timing.streaming_ms,
                    req_timing.persistence_ms,
                    req_timing.total_ms(),
                )
                _task_start_times.pop(user_id, None)
                extraction_runner = get_extraction_runner()
                if fact_extractor is not None and fact_store is not None:
                    extraction_runner.run_background(
                        extract_and_store_facts(
                            user_id, text, fact_extractor, fact_store
                        )
                    )
                if goal_extractor is not None and goal_store is not None:
                    extraction_runner.run_background(
                        extract_and_store_goals(
                            user_id, text, goal_extractor, goal_store
                        )
                    )
                await hook_manager.emit(
                    HookEvents.SESSION_END,
                    {"user_id": user_id, "path": "tool_use", "timing": req_timing},
                )
                compaction_service = get_compaction_service(conv_store, claude_client)
                if compaction_service is not None:
                    extraction_runner.run_background(
                        compaction_service.check_and_compact(user_id, session_key)
                    )
                return

            rotator = MessageRotator(sent, user_id)
            rotator.start()
            rotator_stopped = False

            async def wrapper_stream():
                nonlocal rotator_stopped
                async for chunk in router.stream(
                    text, messages, user_id, system=system_prompt
                ):
                    if not rotator_stopped:
                        await rotator.stop()
                        rotator_stopped = True
                    yield chunk

            try:
                response_text = await stream_to_telegram(
                    chunks=wrapper_stream(),
                    initial_message=sent,
                    session_manager=session_manager,
                    user_id=user_id,
                    thread_id=thread_id,
                )
            except ServiceUnavailableError as e:
                _task_start_times.pop(user_id, None)
                await sent.edit_text(
                    f"❌ Service unavailable: {e}\n\nFallback: Check /status or try again in a moment."
                )
                return
            except Exception as e:
                _task_start_times.pop(user_id, None)
                logger.error("Error processing message for user %d: %s", user_id, e)
                await sent.edit_text(f"❌ Sorry, something went wrong: {e}")
                return
            finally:
                if not rotator_stopped:
                    await rotator.stop()

            model_name = router.last_model
            assistant_turn = ConversationTurn(
                role="assistant", content=response_text, model_used=model_name
            )
            await conv_store.append_turn(user_id, session_key, assistant_turn)

            _task_start_times.pop(user_id, None)

            extraction_runner = get_extraction_runner()
            if fact_extractor is not None and fact_store is not None:
                extraction_runner.run_background(
                    extract_and_store_facts(user_id, text, fact_extractor, fact_store)
                )
            if goal_extractor is not None and goal_store is not None:
                extraction_runner.run_background(
                    extract_and_store_goals(user_id, text, goal_extractor, goal_store)
                )
            await hook_manager.emit(
                HookEvents.SESSION_END,
                {"user_id": user_id, "path": "router_fallback"},
            )
            compaction_service = get_compaction_service(conv_store, claude_client)
            if compaction_service is not None:
                extraction_runner.run_background(
                    compaction_service.check_and_compact(user_id, session_key)
                )

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        # Ignore messages generated by the bot itself to prevent re-ingestion loops (Bug 18)
        try:
            if (
                update.effective_user
                and context.bot
                and update.effective_user.id == context.bot.id
            ):
                logger.debug(
                    "Ignoring message from bot itself (chat handler): %s", update
                )
                return
        except AttributeError:
            logger.warning(
                "Bug 18 guard: unexpected context shape, proceeding", exc_info=True
            )

        user = update.effective_user
        user_id = user.id
        text = update.message.text or ""

        await _process_text_input(user_id, text, update, context)

    async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Transcribe voice messages and process as text."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        if voice_transcriber is None:
            await update.message.reply_text(
                "Voice transcription not available. Install faster-whisper."
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)
        if update.message.voice is None:
            await update.message.reply_text("[No voice in message]")
            return
        voice_file = await update.message.voice.get_file()

        transcript = await voice_transcriber.transcribe(voice_file)
        if not transcript:
            await update.message.reply_text("[Could not transcribe voice message]")
            return

        await update.message.reply_text(f"🎙 _{transcript}_", parse_mode="Markdown")

        user_id = update.effective_user.id
        await _process_text_input(user_id, transcript, update, context)

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process photo messages — download, encode to base64, analyse with Claude vision."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        if claude_client is None:
            await update.message.reply_text(
                "Image analysis not available (Claude not configured)."
            )
            return

        user_id = update.effective_user.id
        thread_id: int | None = getattr(update.message, "message_thread_id", None)

        allowed, rate_limit_reason = _rate_limiter.is_allowed(user_id)
        if not allowed:
            await update.message.reply_text(f"⏱️ {rate_limit_reason}")
            return

        if user_id in _task_start_times:
            elapsed = time.time() - _task_start_times[user_id]
            if elapsed > TASK_TIMEOUT_SECONDS:
                _task_start_times.pop(user_id, None)
                session_manager.request_cancel(user_id)
                await update.message.reply_text(
                    "⏰ Previous task exceeded 2-hour limit and was cancelled. Starting fresh."
                )
        _task_start_times[user_id] = time.time()

        await update.message.chat.send_action(ChatAction.TYPING)

        photo = update.message.photo[-1]
        caption = update.message.caption or ""
        user_text = caption if caption else "What is this image?"

        try:
            photo_file = await photo.get_file()
            bio = io.BytesIO()
            await photo_file.download_to_memory(bio)
            image_bytes = bio.getvalue()
        except Exception as exc:
            logger.error("Failed to download photo for user %d: %s", user_id, exc)
            await update.message.reply_text("❌ Could not download photo.")
            _task_start_times.pop(user_id, None)
            return

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        await _ensure_user(update.effective_user)
        async with session_manager.get_lock(user_id):
            session_manager.clear_cancel(user_id)
            session_key = SessionManager.get_session_key(user_id, thread_id)

            recent = await conv_store.get_recent_turns(
                user_id, session_key, limit=settings.compaction_keep_recent_messages
            )
            messages = [_build_message_from_turn(t) for t in recent]
            while messages:
                first = messages[0]
                if first["role"] == "user" and isinstance(first["content"], str):
                    break
                messages.pop(0)
            messages = _trim_messages_to_budget(messages)

            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            )

            history_text = f"[photo] {caption}" if caption else "[photo]"
            user_turn = ConversationTurn(role="user", content=history_text)
            await conv_store.append_turn(user_id, session_key, user_turn)

            system_prompt = settings.soul_md
            if memory_injector is not None:
                try:
                    system_prompt = await memory_injector.build_system_prompt(
                        user_id, user_text, settings.soul_md
                    )
                    system_prompt = sanitize_memory_injection(system_prompt)
                except Exception as e:
                    logger.error("Memory injection failed, using base prompt: %s", e)

            sent = await update.message.reply_text("…")

            if tool_registry is not None and claude_client is not None:
                await _stream_with_tools_path(
                    user_id=user_id,
                    text=user_text,
                    messages=messages,
                    system_prompt=system_prompt,
                    session_key=session_key,
                    sent=sent,
                    chat_id=update.effective_chat.id if update.effective_chat else None,
                    message_id=update.message.message_id if update.message else None,
                    bot=context.bot,
                )
            else:
                try:
                    await stream_to_telegram(
                        chunks=router.stream(
                            user_text, messages, user_id, system=system_prompt
                        ),
                        initial_message=sent,
                        session_manager=session_manager,
                        user_id=user_id,
                        thread_id=thread_id,
                    )
                except Exception as exc:
                    logger.error("Error processing photo for user %d: %s", user_id, exc)
                    await sent.edit_text(f"❌ Sorry, something went wrong: {exc}")

            _task_start_times.pop(user_id, None)

    ALLOWED_DOC_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    MAX_DOC_SIZE = 5 * 1024 * 1024

    async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process document messages — handle images sent as files (uncompressed)."""
        if update.message is None or update.effective_user is None:
            return
        if await reject_unauthorized(update):
            return

        if claude_client is None:
            await update.message.reply_text(
                "Image analysis not available (Claude not configured)."
            )
            return

        doc = update.message.document
        if doc is None:
            return

        if not doc.mime_type or doc.mime_type not in ALLOWED_DOC_MIMES:
            await update.message.reply_text(
                "I can only analyse image files (JPEG, PNG, GIF, WebP). "
                "For other documents, try copying and pasting the text."
            )
            return

        if doc.file_size and doc.file_size > MAX_DOC_SIZE:
            await update.message.reply_text("❌ Image too large (max 5 MB).")
            return

        user_id = update.effective_user.id
        thread_id: int | None = getattr(update.message, "message_thread_id", None)

        allowed, rate_limit_reason = _rate_limiter.is_allowed(user_id)
        if not allowed:
            await update.message.reply_text(f"⏱️ {rate_limit_reason}")
            return

        if user_id in _task_start_times:
            elapsed = time.time() - _task_start_times[user_id]
            if elapsed > TASK_TIMEOUT_SECONDS:
                _task_start_times.pop(user_id, None)
                session_manager.request_cancel(user_id)
                await update.message.reply_text(
                    "⏰ Previous task exceeded 2-hour limit and was cancelled. Starting fresh."
                )
        _task_start_times[user_id] = time.time()

        await update.message.chat.send_action(ChatAction.TYPING)

        caption = update.message.caption or ""
        user_text = caption if caption else "What is this image?"
        filename = doc.file_name or "image"

        try:
            doc_file = await doc.get_file()
            bio = io.BytesIO()
            await doc_file.download_to_memory(bio)
            image_bytes = bio.getvalue()
        except Exception as exc:
            logger.error("Failed to download document for user %d: %s", user_id, exc)
            await update.message.reply_text("❌ Could not download file.")
            _task_start_times.pop(user_id, None)
            return

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        await _ensure_user(update.effective_user)
        async with session_manager.get_lock(user_id):
            session_manager.clear_cancel(user_id)
            session_key = SessionManager.get_session_key(user_id, thread_id)

            recent = await conv_store.get_recent_turns(
                user_id, session_key, limit=settings.compaction_keep_recent_messages
            )
            messages = [_build_message_from_turn(t) for t in recent]
            while messages:
                first = messages[0]
                if first["role"] == "user" and isinstance(first["content"], str):
                    break
                messages.pop(0)
            messages = _trim_messages_to_budget(messages)

            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": doc.mime_type,
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            )

            history_text = (
                f"[document: {filename}] {caption}"
                if caption
                else f"[document: {filename}]"
            )
            user_turn = ConversationTurn(role="user", content=history_text)
            await conv_store.append_turn(user_id, session_key, user_turn)

            system_prompt = settings.soul_md
            if memory_injector is not None:
                try:
                    system_prompt = await memory_injector.build_system_prompt(
                        user_id, user_text, settings.soul_md
                    )
                    system_prompt = sanitize_memory_injection(system_prompt)
                except Exception as e:
                    logger.error("Memory injection failed, using base prompt: %s", e)

            sent = await update.message.reply_text("…")

            if tool_registry is not None and claude_client is not None:
                await _stream_with_tools_path(
                    user_id=user_id,
                    text=user_text,
                    messages=messages,
                    system_prompt=system_prompt,
                    session_key=session_key,
                    sent=sent,
                    chat_id=update.effective_chat.id if update.effective_chat else None,
                    message_id=update.message.message_id if update.message else None,
                    bot=context.bot,
                )
            else:
                try:
                    await stream_to_telegram(
                        chunks=router.stream(
                            user_text, messages, user_id, system=system_prompt
                        ),
                        initial_message=sent,
                        session_manager=session_manager,
                        user_id=user_id,
                        thread_id=thread_id,
                    )
                except Exception as exc:
                    logger.error(
                        "Error processing document for user %d: %s", user_id, exc
                    )
                    await sent.edit_text(f"❌ Sorry, something went wrong: {exc}")

            _task_start_times.pop(user_id, None)

    return {
        "message": handle_message,
        "voice": handle_voice,
        "photo": handle_photo,
        "document": handle_document,
    }
