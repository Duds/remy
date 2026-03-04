"""
Tests for confirmation flow callbacks (inline Confirm/Cancel, snooze/done).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remy.bot.handlers.callbacks import (
    make_step_limit_keyboard,
    store_pending_archive,
    make_archive_keyboard,
    make_suggested_actions_keyboard,
    make_callback_handler,
    store_reminder_payload,
    make_reminder_keyboard,
    store_run_again_payload,
    make_run_again_keyboard,
)


class TestStorePendingArchive:
    """Test pending archive storage."""

    def test_returns_token(self):
        token = store_pending_archive(12345, ["msg1", "msg2"])
        assert isinstance(token, str)
        assert len(token) == 16  # 8 bytes hex

    def test_different_calls_different_tokens(self):
        t1 = store_pending_archive(1, ["a"])
        t2 = store_pending_archive(1, ["b"])
        assert t1 != t2


class TestMakeSuggestedActionsKeyboard:
    """Test suggested actions keyboard creation."""

    def test_returns_keyboard_for_valid_actions(self):
        actions = [
            {
                "label": "Add to calendar",
                "callback_id": "add_to_calendar",
                "payload": {"title": "Meeting", "when": "2026-03-04T10:00"},
            },
            {"label": "Dismiss", "callback_id": "dismiss"},
        ]
        kb = make_suggested_actions_keyboard(actions, 12345)
        assert kb is not None
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 2

    def test_returns_none_for_empty_actions(self):
        assert make_suggested_actions_keyboard([], 12345) is None

    def test_returns_none_for_empty_after_filter(self):
        actions = [{"label": "Bad", "callback_id": "invalid"}]
        assert make_suggested_actions_keyboard(actions, 12345) is None


class TestStoreRunAgainPayload:
    """Test run-again payload storage."""

    def test_returns_token(self):
        token = store_run_again_payload(99, "board", {"topic": "Focus"})
        assert isinstance(token, str)
        assert len(token) == 12  # 6 bytes hex

    def test_different_calls_different_tokens(self):
        t1 = store_run_again_payload(1, "board", {"topic": "A"})
        t2 = store_run_again_payload(1, "research", {"topic": "B"})
        assert t1 != t2


class TestMakeRunAgainKeyboard:
    """Test Run again / New topic keyboard."""

    def test_returns_keyboard_with_two_buttons(self):
        kb = make_run_again_keyboard("board", {"topic": "Test topic"}, 12345)
        assert kb is not None
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 2
        labels = [b.text for b in kb.inline_keyboard[0]]
        assert "Run again" in labels
        assert "New topic" in labels
        data = [b.callback_data for b in kb.inline_keyboard[0]]
        assert any(d.startswith("run_again_") for d in data)
        assert any(d.startswith("new_topic_") for d in data)


class TestMakeStepLimitKeyboard:
    """Test step-limit keyboard (Continue / Break down / Stop)."""

    def test_returns_keyboard_with_three_buttons(self):
        kb = make_step_limit_keyboard()
        assert kb is not None
        assert len(kb.inline_keyboard) == 1
        assert len(kb.inline_keyboard[0]) == 3
        labels = [b.text for b in kb.inline_keyboard[0]]
        assert "Continue" in labels
        assert "Break down" in labels
        assert "Stop" in labels
        data = [b.callback_data for b in kb.inline_keyboard[0]]
        assert "step_limit_continue" in data
        assert "step_limit_break" in data
        assert "step_limit_stop" in data


class TestMakeArchiveKeyboard:
    """Test inline keyboard creation."""

    def test_returns_keyboard(self):
        kb = make_archive_keyboard("abc123")
        assert kb is not None
        assert hasattr(kb, "inline_keyboard")
        assert len(kb.inline_keyboard) == 1
        row = kb.inline_keyboard[0]
        assert len(row) == 2
        assert row[0].text == "Confirm"
        assert row[0].callback_data == "confirm_archive_abc123"
        assert row[1].text == "Cancel"
        assert row[1].callback_data == "cancel_archive_abc123"


class TestStoreReminderPayload:
    """Test reminder payload storage for snooze/done."""

    def test_returns_token(self):
        token = store_reminder_payload(
            user_id=1, chat_id=999, label="Standup", automation_id=0, one_time=True
        )
        assert isinstance(token, str)
        assert len(token) == 12  # 6 bytes hex

    def test_different_calls_different_tokens(self):
        t1 = store_reminder_payload(1, 100, "A", one_time=True)
        t2 = store_reminder_payload(1, 100, "B", one_time=True)
        assert t1 != t2


class TestMakeReminderKeyboard:
    """Test reminder keyboard creation."""

    def test_returns_keyboard(self):
        kb = make_reminder_keyboard("xyz789")
        assert kb is not None
        assert len(kb.inline_keyboard) == 1
        row = kb.inline_keyboard[0]
        assert len(row) == 3
        assert row[0].text == "Snooze 5m"
        assert row[0].callback_data == "snooze_5_xyz789"
        assert row[1].text == "Snooze 15m"
        assert row[1].callback_data == "snooze_15_xyz789"
        assert row[2].text == "Done"
        assert row[2].callback_data == "done_xyz789"


class TestCallbackHandler:
    """Test callback query handling."""

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_confirm_archive_executes_and_edits(self, mock_is_allowed):
        mock_gmail = AsyncMock()
        mock_gmail.archive_messages.return_value = 5

        handler = make_callback_handler(google_gmail=mock_gmail)
        token = store_pending_archive(999, ["m1", "m2", "m3", "m4", "m5"])

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = f"confirm_archive_{token}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999

        context = MagicMock()

        await handler(update, context)

        mock_gmail.archive_messages.assert_called_once_with(
            ["m1", "m2", "m3", "m4", "m5"]
        )
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_with(
            "✅ Archived 5 email(s)."
        )

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_cancel_archive_edits_message(self, mock_is_allowed):
        handler = make_callback_handler(google_gmail=None)
        token = store_pending_archive(888, ["x"])

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = f"cancel_archive_{token}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 888

        context = MagicMock()

        await handler(update, context)

        update.callback_query.edit_message_text.assert_called_with("Cancelled.")

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_forward_to_cowork_calls_relay(self, mock_is_allowed):
        mock_relay = AsyncMock(return_value=True)
        handler = make_callback_handler(relay_post_message=mock_relay)
        actions = [
            {
                "label": "Send to cowork",
                "callback_id": "forward_to_cowork",
                "payload": {"text": "Gmail audit complete."},
            }
        ]
        kb = make_suggested_actions_keyboard(actions, 777)
        cb_data = kb.inline_keyboard[0][0].callback_data

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = cb_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 777

        context = MagicMock()

        await handler(update, context)

        mock_relay.assert_called_once_with(content="Gmail audit complete.")
        update.callback_query.edit_message_text.assert_called_with("✅ Sent to cowork.")

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_stale_token_shows_expired(self, mock_is_allowed):
        handler = make_callback_handler(google_gmail=MagicMock())

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = "confirm_archive_nonexistent123"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 111

        context = MagicMock()

        await handler(update, context)

        update.callback_query.edit_message_text.assert_called_with(
            "Expired. Please try again."
        )

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_snooze_5_creates_one_shot_and_edits(self, mock_is_allowed):
        mock_store = AsyncMock()
        mock_store.add.return_value = 42
        scheduler_ref = {"proactive_scheduler": MagicMock()}

        handler = make_callback_handler(
            automation_store=mock_store,
            scheduler_ref=scheduler_ref,
        )
        token = store_reminder_payload(
            user_id=777, chat_id=12345, label="Standup", one_time=True
        )

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = f"snooze_5_{token}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 777

        context = MagicMock()

        await handler(update, context)

        mock_store.add.assert_called_once()
        call_args = mock_store.add.call_args
        assert call_args.args[0] == 777  # user_id
        assert call_args.args[1] == "Standup"  # label
        assert call_args.kwargs.get("cron") == ""
        assert "fire_at" in call_args.kwargs
        scheduler_ref["proactive_scheduler"].add_automation.assert_called_once()
        update.callback_query.edit_message_text.assert_called()
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Snoozed" in text
        assert "next reminder at" in text

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_done_edits_message(self, mock_is_allowed):
        handler = make_callback_handler()
        token = store_reminder_payload(
            user_id=888, chat_id=999, label="Call mom", one_time=True
        )

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = f"done_{token}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 888

        context = MagicMock()

        await handler(update, context)

        update.callback_query.edit_message_text.assert_called_with("Done ✓")

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_done_updates_last_run_for_recurring(self, mock_is_allowed):
        mock_store = AsyncMock()
        handler = make_callback_handler(automation_store=mock_store)
        token = store_reminder_payload(
            user_id=999,
            chat_id=111,
            label="Daily standup",
            automation_id=5,
            one_time=False,
        )

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = f"done_{token}"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999

        context = MagicMock()

        await handler(update, context)

        mock_store.update_last_run.assert_called_once_with(5)
        update.callback_query.edit_message_text.assert_called_with("Done ✓")

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_run_auto_missing_automation_shows_no_longer_available(
        self, mock_is_allowed
    ):
        mock_store = AsyncMock()
        mock_store.get_by_id.return_value = None

        handler = make_callback_handler(
            automation_store=mock_store,
            claude_client=MagicMock(),
            tool_registry=MagicMock(),
            session_manager=MagicMock(),
            conv_store=MagicMock(),
        )

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = "run_auto_42"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999

        context = MagicMock()

        await handler(update, context)

        mock_store.get_by_id.assert_called_once_with(42)
        update.callback_query.edit_message_text.assert_called_with(
            "No longer available."
        )

    @pytest.mark.asyncio
    @patch("remy.bot.handlers.callbacks.is_allowed", return_value=True)
    async def test_run_auto_wrong_user_ignored(self, mock_is_allowed):
        mock_store = AsyncMock()
        mock_store.get_by_id.return_value = {
            "id": 42,
            "user_id": 111,  # different from callback user
            "label": "Gmail quick wins",
        }

        handler = make_callback_handler(
            automation_store=mock_store,
            claude_client=MagicMock(),
            tool_registry=MagicMock(),
            session_manager=MagicMock(),
            conv_store=MagicMock(),
        )

        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.data = "run_auto_42"
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 999  # not the owner

        context = MagicMock()

        await handler(update, context)

        mock_store.get_by_id.assert_called_once_with(42)
        update.callback_query.edit_message_text.assert_not_called()
