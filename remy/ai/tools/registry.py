"""
Tool registry class and dispatch logic.

This module contains the ToolRegistry class which holds references to all
tool executor functions and dispatches tool calls from the Anthropic API.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .schemas import TOOL_SCHEMAS

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Holds references to all tool executor functions and dispatches tool calls
    from the Anthropic API.

    Dependencies are injected at construction time so tool executors have
    access to the correct instances (db, goal_store, fact_store, etc.).
    """

    def __init__(
        self,
        *,
        logs_dir: str,
        knowledge_store=None,
        knowledge_extractor=None,
        board_orchestrator=None,
        claude_client=None,
        ollama_base_url: str = "http://localhost:11434",
        model_complex: str = "claude-sonnet-4-6",
        calendar_client=None,
        gmail_client=None,
        contacts_client=None,
        docs_client=None,
        automation_store=None,
        scheduler_ref: dict | None = None,
        mistral_client=None,
        moonshot_client=None,
        grocery_list_file: str = "",
        conversation_analyzer=None,
        job_store=None,
        plan_store=None,
        file_indexer=None,
        fact_store=None,
        goal_store=None,
    ) -> None:
        self._logs_dir = logs_dir
        self._knowledge_store = knowledge_store
        self._knowledge_extractor = knowledge_extractor
        self._board_orchestrator = board_orchestrator
        self._claude_client = claude_client
        self._mistral_client = mistral_client
        self._moonshot_client = moonshot_client
        self._ollama_base_url = ollama_base_url
        self._model_complex = model_complex
        self._calendar = calendar_client
        self._gmail = gmail_client
        self._contacts = contacts_client
        self._docs = docs_client
        self._automation_store = automation_store
        self._scheduler_ref = scheduler_ref or {}
        self._grocery_list_file = grocery_list_file
        self._conversation_analyzer = conversation_analyzer
        self._job_store = job_store
        self._plan_store = plan_store
        self._file_indexer = file_indexer
        self._fact_store = fact_store
        self._goal_store = goal_store

    @property
    def schemas(self) -> list[dict]:
        """Return the list of Anthropic tool schemas."""
        return TOOL_SCHEMAS

    @property
    def _proactive_scheduler(self):
        """Return the proactive scheduler from the scheduler_ref dict."""
        return self._scheduler_ref.get("proactive_scheduler")

    async def dispatch(
        self, tool_name: str, tool_input: dict, user_id: int, chat_id: int | None = None
    ) -> str:
        """
        Execute the named tool with the given input.
        Returns a string result suitable for feeding back as a tool_result block.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Tool parameters
            user_id: Telegram user ID
            chat_id: Optional Telegram chat ID (for tools that need chat context)
        """
        try:
            match tool_name:
                # Time
                case "get_current_time":
                    from .time import exec_get_current_time
                    return exec_get_current_time(self)

                # Memory / status
                case "get_logs":
                    from .memory import exec_get_logs
                    return await exec_get_logs(self, tool_input)
                case "get_goals":
                    from .memory import exec_get_goals
                    return await exec_get_goals(self, tool_input, user_id)
                case "get_facts":
                    from .memory import exec_get_facts
                    return await exec_get_facts(self, tool_input, user_id)
                case "run_board":
                    from .memory import exec_run_board
                    return await exec_run_board(self, tool_input, user_id)
                case "check_status":
                    from .memory import exec_check_status
                    return await exec_check_status(self)
                case "manage_memory":
                    from .memory import exec_manage_memory
                    return await exec_manage_memory(self, tool_input, user_id)
                case "manage_goal":
                    from .memory import exec_manage_goal
                    return await exec_manage_goal(self, tool_input, user_id)
                case "get_memory_summary":
                    from .memory import exec_get_memory_summary
                    return await exec_get_memory_summary(self, user_id)

                # Calendar
                case "calendar_events":
                    from .calendar import exec_calendar_events
                    return await exec_calendar_events(self, tool_input)
                case "create_calendar_event":
                    from .calendar import exec_create_calendar_event
                    return await exec_create_calendar_event(self, tool_input)

                # Email
                case "read_emails":
                    from .email import exec_read_emails
                    return await exec_read_emails(self, tool_input)
                case "search_gmail":
                    from .email import exec_search_gmail
                    return await exec_search_gmail(self, tool_input)
                case "read_email":
                    from .email import exec_read_email
                    return await exec_read_email(self, tool_input)
                case "list_gmail_labels":
                    from .email import exec_list_gmail_labels
                    return await exec_list_gmail_labels(self, tool_input)
                case "label_emails":
                    from .email import exec_label_emails
                    return await exec_label_emails(self, tool_input)
                case "create_gmail_label":
                    from .email import exec_create_gmail_label
                    return await exec_create_gmail_label(self, tool_input)
                case "create_email_draft":
                    from .email import exec_create_email_draft
                    return await exec_create_email_draft(self, tool_input)
                case "classify_promotional_emails":
                    from .email import exec_classify_promotional_emails
                    return await exec_classify_promotional_emails(self, tool_input)

                # Contacts
                case "search_contacts":
                    from .contacts import exec_search_contacts
                    return await exec_search_contacts(self, tool_input)
                case "upcoming_birthdays":
                    from .contacts import exec_upcoming_birthdays
                    return await exec_upcoming_birthdays(self, tool_input)
                case "get_contact_details":
                    from .contacts import exec_get_contact_details
                    return await exec_get_contact_details(self, tool_input)
                case "update_contact_note":
                    from .contacts import exec_update_contact_note
                    return await exec_update_contact_note(self, tool_input)
                case "find_sparse_contacts":
                    from .contacts import exec_find_sparse_contacts
                    return await exec_find_sparse_contacts(self)

                # Files
                case "read_file":
                    from .files import exec_read_file
                    return await exec_read_file(self, tool_input)
                case "list_directory":
                    from .files import exec_list_directory
                    return await exec_list_directory(self, tool_input)
                case "write_file":
                    from .files import exec_write_file
                    return await exec_write_file(self, tool_input)
                case "append_file":
                    from .files import exec_append_file
                    return await exec_append_file(self, tool_input)
                case "find_files":
                    from .files import exec_find_files
                    return await exec_find_files(self, tool_input)
                case "scan_downloads":
                    from .files import exec_scan_downloads
                    return await exec_scan_downloads(self)
                case "organize_directory":
                    from .files import exec_organize_directory
                    return await exec_organize_directory(self, tool_input)
                case "clean_directory":
                    from .files import exec_clean_directory
                    return await exec_clean_directory(self, tool_input)
                case "search_files":
                    from .files import exec_search_files
                    return await exec_search_files(self, tool_input)
                case "index_status":
                    from .files import exec_index_status
                    return await exec_index_status(self)

                # Web
                case "web_search":
                    from .web import exec_web_search
                    return await exec_web_search(self, tool_input)
                case "price_check":
                    from .web import exec_price_check
                    return await exec_price_check(self, tool_input)

                # Automations
                case "schedule_reminder":
                    from .automations import exec_schedule_reminder
                    return await exec_schedule_reminder(self, tool_input, user_id)
                case "list_reminders":
                    from .automations import exec_list_reminders
                    return await exec_list_reminders(self, user_id)
                case "remove_reminder":
                    from .automations import exec_remove_reminder
                    return await exec_remove_reminder(self, tool_input, user_id)
                case "set_one_time_reminder":
                    from .automations import exec_set_one_time_reminder
                    return await exec_set_one_time_reminder(self, tool_input, user_id)
                case "breakdown_task":
                    from .automations import exec_breakdown_task
                    return await exec_breakdown_task(self, tool_input)
                case "grocery_list":
                    from .automations import exec_grocery_list
                    return await exec_grocery_list(self, tool_input, user_id)

                # Plans
                case "create_plan":
                    from .plans import exec_create_plan
                    return await exec_create_plan(self, tool_input, user_id)
                case "get_plan":
                    from .plans import exec_get_plan
                    return await exec_get_plan(self, tool_input, user_id)
                case "list_plans":
                    from .plans import exec_list_plans
                    return await exec_list_plans(self, tool_input, user_id)
                case "update_plan_step":
                    from .plans import exec_update_plan_step
                    return await exec_update_plan_step(self, tool_input, user_id)
                case "update_plan_status":
                    from .plans import exec_update_plan_status
                    return await exec_update_plan_status(self, tool_input, user_id)

                # Analytics
                case "get_stats":
                    from .analytics import exec_get_stats
                    return await exec_get_stats(self, tool_input, user_id)
                case "get_goal_status":
                    from .analytics import exec_get_goal_status
                    return await exec_get_goal_status(self, user_id)
                case "generate_retrospective":
                    from .analytics import exec_generate_retrospective
                    return await exec_generate_retrospective(self, tool_input, user_id)
                case "consolidate_memory":
                    from .analytics import exec_consolidate_memory
                    return await exec_consolidate_memory(self, user_id)
                case "list_background_jobs":
                    from .analytics import exec_list_background_jobs
                    return await exec_list_background_jobs(self, tool_input, user_id)
                case "get_costs":
                    from .analytics import exec_get_costs
                    return await exec_get_costs(self, tool_input, user_id)

                # Google Docs
                case "read_gdoc":
                    from .docs import exec_read_gdoc
                    return await exec_read_gdoc(self, tool_input, user_id)
                case "append_to_gdoc":
                    from .docs import exec_append_to_gdoc
                    return await exec_append_to_gdoc(self, tool_input, user_id)

                # Bookmarks
                case "save_bookmark":
                    from .bookmarks import exec_save_bookmark
                    return await exec_save_bookmark(self, tool_input, user_id)
                case "list_bookmarks":
                    from .bookmarks import exec_list_bookmarks
                    return await exec_list_bookmarks(self, tool_input, user_id)

                # Projects
                case "set_project":
                    from .projects import exec_set_project
                    return await exec_set_project(self, tool_input, user_id)
                case "get_project_status":
                    from .projects import exec_get_project_status
                    return await exec_get_project_status(self, user_id)

                # Session / Privacy
                case "compact_conversation":
                    from .session import exec_compact_conversation
                    return await exec_compact_conversation(self, user_id)
                case "delete_conversation":
                    from .session import exec_delete_conversation
                    return await exec_delete_conversation(self, user_id)
                case "set_proactive_chat":
                    from .session import exec_set_proactive_chat
                    return await exec_set_proactive_chat(self, user_id, chat_id)
                case "end_session":
                    from .session import exec_end_session
                    return await exec_end_session(self, tool_input, user_id)
                case "help":
                    from .session import exec_help
                    return await exec_help(self, tool_input, user_id)

                # Special tools
                case "trigger_reindex":
                    from .session import exec_trigger_reindex
                    return await exec_trigger_reindex(self)
                case "start_privacy_audit":
                    from .session import exec_start_privacy_audit
                    return await exec_start_privacy_audit(self)

                case _:
                    return f"Unknown tool: {tool_name}"

        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc, exc_info=True)
            return f"Tool {tool_name} encountered an error: {exc}"
