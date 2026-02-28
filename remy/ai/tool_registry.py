"""
Tool registry for native Anthropic tool use (function calling).

DEPRECATED: This module is a compatibility shim. Import from remy.ai.tools instead.

All slash-command functionality is exposed here so Claude can invoke it from
natural language without the user needing to type slash commands.

Tools available:
  Time
    get_current_time      → current date/time in Australia/Canberra

  Memory / status
    get_logs              → diagnostics
    get_goals             → active goals
    get_facts             → stored facts
    run_board             → Board of Directors analysis
    check_status          → backend availability
    manage_memory         → add/update/delete memory facts
    manage_goal           → add/update/complete/abandon goals
    get_memory_summary    → summary of stored memories

  Calendar
    calendar_events       → list upcoming events
    create_calendar_event → create a new event

  Gmail
    read_emails               → unread email summary
    search_gmail              → search all Gmail
    read_email                → read full email body
    list_gmail_labels         → list all labels
    label_emails              → apply/remove labels
    create_gmail_label        → create a new label
    create_email_draft        → create a draft email
    classify_promotional_emails → find promotional/newsletter emails

  Contacts
    search_contacts       → find a contact by name/email
    upcoming_birthdays    → birthdays in the next N days
    get_contact_details   → full contact card
    update_contact_note   → add/update contact note
    find_sparse_contacts  → find contacts missing email/phone

  Web / research
    web_search            → DuckDuckGo search (+ optional Claude synthesis)
    price_check           → search for current prices

  Files
    read_file             → read a text file from allowed directories
    list_directory        → list files in a directory
    write_file            → write to a file
    append_file           → append to a file
    find_files            → search filenames by glob pattern
    scan_downloads        → analyse ~/Downloads folder
    organize_directory    → Claude suggests folder organisation
    clean_directory       → Claude suggests DELETE/ARCHIVE/KEEP
    search_files          → semantic search file contents (RAG)
    index_status          → file index status

  Documents
    read_gdoc             → read a Google Doc by URL or ID
    append_to_gdoc        → append text to a Google Doc

  Grocery list
    grocery_list          → show / add / remove / clear items

  Bookmarks
    save_bookmark         → save a URL with optional note
    list_bookmarks        → list saved bookmarks

  Projects
    set_project           → mark a directory as current project
    get_project_status    → show tracked projects

  Automations (Phase 5)
    schedule_reminder     → create a daily or weekly reminder
    set_one_time_reminder → create a one-time reminder at a specific datetime
    list_reminders        → show all scheduled reminders
    remove_reminder       → remove a reminder by ID
    breakdown_task        → break a task into 5 actionable steps

  Plans
    create_plan           → create a multi-step plan
    get_plan              → get plan details
    list_plans            → list active plans
    update_plan_step      → update step status/log attempt
    update_plan_status    → mark plan complete/abandoned

  Analytics (Phase 6)
    get_stats             → conversation usage statistics
    get_goal_status       → goal tracking dashboard with age/staleness
    generate_retrospective → Claude-written monthly retrospective
    get_costs             → AI costs by provider and model
    consolidate_memory    → extract memories from conversations
    list_background_jobs  → list recent background jobs

  Session / Privacy
    compact_conversation  → summarise and compress conversation
    delete_conversation   → clear conversation history
    set_proactive_chat    → set chat for morning/evening messages

  Special
    trigger_reindex       → manually trigger file reindexing
    start_privacy_audit   → begin guided privacy audit
"""

from __future__ import annotations

import warnings

from .tools import TOOL_SCHEMAS, ToolRegistry

warnings.warn(
    "remy.ai.tool_registry is deprecated. Import from remy.ai.tools instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ToolRegistry", "TOOL_SCHEMAS"]
