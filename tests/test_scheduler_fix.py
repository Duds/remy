"""
Tests for scheduler reliability fixes.
Verifies that one-time reminders are deleted from DB before being sent to prevent double-firing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from drbot.scheduler.proactive import ProactiveScheduler

@pytest.mark.asyncio
async def test_run_automation_deletes_onetime_before_sending():
    # Setup
    automation_store = MagicMock()
    automation_store.delete = AsyncMock()
    
    bot = MagicMock()
    
    scheduler = ProactiveScheduler(
        bot=bot,
        goal_store=MagicMock(),
        fact_store=MagicMock(),
        calendar_client=None,
        contacts_client=None,
        automation_store=automation_store,
        claude_client=None,
        conversation_analyzer=None
    )
    
    # 1. Track call order explicitly
    call_order = []
    
    async def mock_delete(aid):
        call_order.append("delete")
        
    async def mock_send(cid, text):
        call_order.append("send")
        
    # Apply side effects
    automation_store.delete.side_effect = mock_delete
    
    with patch("drbot.scheduler.proactive._read_primary_chat_id", return_value=12345):
        with patch.object(scheduler, "_send", side_effect=mock_send):
            automation = {
                "id": 123,
                "user_id": 1,
                "label": "Remember milk",
                "cron": "",
                "fire_at": "2026-02-27T12:00:00",
                "last_run_at": None
            }
            
            # 2. Execution (MUST be inside the patch context)
            await scheduler._run_automation(
                automation_id=automation["id"],
                user_id=automation["user_id"],
                label=automation["label"],
                one_time=True
            )
        
    # 3. Assertions (can be outside)
    assert "delete" in call_order
    assert "send" in call_order
    assert call_order.index("delete") < call_order.index("send"), "delete MUST be called before send"
    automation_store.delete.assert_called_once_with(123)
