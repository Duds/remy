"""
Claude Agent SDK subagents (US-claude-agent-sdk-migration).

Defines three subagents (quick-assistant, board-analyst, deep-researcher) and
runners that use the Claude Agent SDK when available. Board and research run
via SDK; quick-assistant can stream via run_quick_assistant_streaming when
stream_with_tools delegates to the SDK.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ..ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Quick-assistant uses registry.schemas so full registry = all tools, FilteredToolRegistry = subset

# Read-only tools for board-analyst: no run_board, hand_off_to_researcher, or write/delete
BOARD_ANALYST_TOOL_NAMES = [
    "get_current_time",
    "get_logs",
    "get_goals",
    "get_facts",
    "check_status",
    "calendar_events",
    "read_emails",
    "search_gmail",
    "read_email",
    "list_gmail_labels",
    "read_file",
    "list_directory",
    "get_file_download_link",
    "find_files",
    "search_files",
    "index_status",
    "git_log",
    "git_show_commit",
    "git_diff",
    "git_status",
    "get_memory_summary",
    "get_counter",
    "get_plan",
    "list_plans",
    "get_stats",
    "get_goal_status",
    "list_background_jobs",
    "get_costs",
    "read_gdoc",
    "search_contacts",
    "upcoming_birthdays",
    "get_contact_details",
    "find_sparse_contacts",
    "list_bookmarks",
    "get_project_status",
    "price_check",
    "get_sms_messages",
    "get_wallet_transactions",
]

# deep-researcher: web search + file read (and read-only tools needed for research)
DEEP_RESEARCHER_TOOL_NAMES = [
    "get_current_time",
    "web_search",
    "read_file",
    "list_directory",
    "find_files",
    "search_files",
    "read_gdoc",
    "price_check",
]

BOARD_SYSTEM_PROMPT = """You are the Board of Directors — a single advisor that combines five perspectives in one response.

For the user's topic you must provide:

1. **Strategy** — Big-picture thinking, prioritisation, highest-leverage opportunities, risks, and a clear prioritised roadmap. Be direct and specific. ~250 words.

2. **Content** — Creative and content strategy: messaging, narrative, and how to communicate the strategy. ~200 words.

3. **Finance** — Resource and cost implications, ROI, trade-offs. ~150 words.

4. **Researcher** — Key facts, sources, and what to verify. Use tools (get_facts, get_goals, web_search, read_file) as needed. ~150 words.

5. **Critic** — Steelman the strongest counter-arguments, then a short **Board Verdict**: 3–5 sentences with the key action, biggest risk, and most important open question. Use headers: ## Challenges and ## Board Verdict. ~300 words.

Format the reply with clear section headers (e.g. *Strategy*, *Content*, *Finance*, *Researcher*, *Critic*). Use the user context (goals/facts) if provided. Output Markdown suitable for Telegram (bold via *text*)."""

RESEARCH_SYSTEM_PROMPT = """You are a research assistant. Use web_search and read_file/list_directory as needed to research the topic. Synthesise key findings into a clear, concise summary. Cite sources. Be factual and concise. Do not use tools that modify data or hand off to other agents."""


def is_sdk_available() -> bool:
    """Return True if claude-agent-sdk is installed and usable."""
    try:
        import claude_agent_sdk  # noqa: F401

        return True
    except ImportError:
        return False


def _mcp_server_from_registry(
    registry: "ToolRegistry",
    allowed_tool_names: list[str],
    user_id: int,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> Any:
    """Build an SDK MCP server that wraps the tool registry for the allowed tools."""
    from ..ai.tools.schemas import TOOL_SCHEMAS

    try:
        from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server
    except ImportError:
        return None

    schema_by_name = {
        s["name"]: s for s in TOOL_SCHEMAS if s["name"] in allowed_tool_names
    }
    tools: list[Any] = []

    for name in allowed_tool_names:
        schema = schema_by_name.get(name)
        if not schema:
            continue

        async def _handler(
            args: dict,
            _name: str = name,
            _reg: "ToolRegistry" = registry,
            _uid: int = user_id,
            _cid: int | None = chat_id,
            _mid: int | None = message_id,
        ) -> dict:
            logger.info("mcp_handler_invoke: tool=%s user_id=%d", _name, _uid)
            result = await _reg.dispatch(_name, args, _uid, _cid, _mid)
            logger.info("mcp_handler_return: tool=%s user_id=%d", _name, _uid)
            return {"content": [{"type": "text", "text": result}]}

        tools.append(
            SdkMcpTool(
                name=schema["name"],
                description=schema["description"],
                input_schema=schema["input_schema"],
                handler=_handler,
            )
        )

    if not tools:
        return None
    return create_sdk_mcp_server("remy", "1.0.0", tools=tools)


async def run_board_analyst(
    topic: str,
    user_context: str,
    user_id: int,
    session_key: str,
    registry: "ToolRegistry",
    *,
    model: str | None = None,
) -> str:
    """
    Run the board-analyst subagent via the Claude Agent SDK.
    Returns the full Board report text. Used by /board when SDK is available.
    """
    if not is_sdk_available():
        return ""

    from ..config import settings

    mcp = _mcp_server_from_registry(
        registry, BOARD_ANALYST_TOOL_NAMES, user_id, None, None
    )
    if mcp is None:
        return ""

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return ""

    prompt = f"Topic: {topic}\n\n"
    if user_context:
        prompt += f"User context (goals/facts):\n{user_context}\n\n"
    prompt += "Provide the full Board of Directors analysis as specified in your instructions."

    model = (
        model
        or getattr(settings, "model_board_analyst", None)
        or settings.model_complex
    )
    options = ClaudeAgentOptions(
        system_prompt=BOARD_SYSTEM_PROMPT,
        model=model,
        mcp_servers={"remy": mcp},
        allowed_tools=BOARD_ANALYST_TOOL_NAMES,
        include_partial_messages=False,
    )

    chunks: list[str] = []
    try:
        async for message in query(prompt=prompt, options=options):
            if getattr(message, "content", None):
                if isinstance(message.content, str):
                    chunks.append(message.content)
                elif isinstance(message.content, list):
                    for block in message.content:
                        if getattr(block, "text", None):
                            chunks.append(block.text)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            chunks.append(block.get("text", ""))
    except Exception as e:
        logger.warning("SDK board-analyst failed: %s", e)
        return ""

    body = "".join(chunks).strip()
    if not body:
        return ""
    return f"🏛 *Board of Directors: {topic}*\n\n{body}"


async def run_deep_researcher(
    topic: str,
    user_id: int,
    registry: "ToolRegistry",
    *,
    model: str | None = None,
) -> str:
    """
    Run the deep-researcher subagent via the Claude Agent SDK.
    Returns the research summary. Used by /research when SDK is available.
    """
    if not is_sdk_available():
        return ""

    from ..config import settings

    mcp = _mcp_server_from_registry(
        registry, DEEP_RESEARCHER_TOOL_NAMES, user_id, None, None
    )
    if mcp is None:
        return ""

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return ""

    prompt = (
        f"Research the following topic and synthesise key findings into a clear, "
        f"concise summary. Cite sources. Topic: {topic}"
    )
    model = (
        model
        or getattr(settings, "model_deep_researcher", None)
        or settings.model_complex
    )
    options = ClaudeAgentOptions(
        system_prompt=RESEARCH_SYSTEM_PROMPT,
        model=model,
        mcp_servers={"remy": mcp},
        allowed_tools=DEEP_RESEARCHER_TOOL_NAMES,
        include_partial_messages=False,
    )

    chunks: list[str] = []
    try:
        async for message in query(prompt=prompt, options=options):
            if getattr(message, "content", None):
                if isinstance(message.content, str):
                    chunks.append(message.content)
                elif isinstance(message.content, list):
                    for block in message.content:
                        if getattr(block, "text", None):
                            chunks.append(block.text)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            chunks.append(block.get("text", ""))
    except Exception as e:
        logger.warning("SDK deep-researcher failed: %s", e)
        return ""

    result = "".join(chunks).strip()
    if not result:
        return ""
    return f"📚 *Research: {topic}*\n\n{result}"


def _format_messages_for_prompt(
    messages: list[dict], max_turns: int = 10
) -> tuple[str, str]:
    """Convert message list to (context_string, last_user_prompt). Last message must be user."""
    if not messages:
        return "", ""
    # Last message is the main prompt
    last = messages[-1]
    if last.get("role") != "user":
        return "", ""
    last_content = last.get("content", "")
    if isinstance(last_content, str):
        prompt = last_content.strip()
    else:
        prompt = ""
        if isinstance(last_content, list):
            for block in last_content:
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt += block.get("text", "")
    # Prior messages as context (truncate to max_turns)
    prior = messages[:-1][-max_turns * 2 :]  # rough turn count
    context_parts = []
    for m in prior:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, str):
            context_parts.append(f"{role}: {content[:800]}")
        else:
            context_parts.append(f"{role}: [blocks]")
    context = "\n".join(context_parts) if context_parts else ""
    return context, prompt.strip() or "Continue."


async def run_quick_assistant_streaming(
    messages: list[dict],
    registry: "ToolRegistry",
    user_id: int,
    *,
    system_prompt: str,
    model: str | None = None,
    usage_out: Any = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    max_iterations: int | None = None,
) -> AsyncIterator[Any]:
    """
    Stream quick-assistant response via Claude Agent SDK, yielding StreamEvent-like objects.

    Maps SDK stream events to TextChunk, ToolStatusChunk, ToolResultChunk, ToolTurnComplete.
    Used when stream_with_tools delegates to the SDK path.
    """
    if not is_sdk_available():
        return

    from ..ai.claude_client import (
        TextChunk,
        ToolStatusChunk,
        ToolResultChunk,
        ToolTurnComplete,
    )
    from ..config import settings

    tool_names = [s["name"] for s in registry.schemas]
    if not tool_names:
        return
    mcp = _mcp_server_from_registry(registry, tool_names, user_id, chat_id, message_id)
    if mcp is None:
        return

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return

    context, prompt = _format_messages_for_prompt(messages)
    system = system_prompt
    if context:
        system = system_prompt + "\n\nRecent conversation:\n" + context

    model = model or getattr(settings, "model_complex", None) or settings.model_complex
    options = ClaudeAgentOptions(
        system_prompt=system,
        model=model,
        mcp_servers={"remy": mcp},
        allowed_tools=tool_names,
        include_partial_messages=True,
    )

    assistant_blocks: list[dict] = []
    tool_result_blocks: list[dict] = []
    current_tool_use_id: str | None = None
    current_tool_name: str | None = None
    current_tool_input: dict = {}

    async for message in query(prompt=prompt, options=options):
        if getattr(message, "event", None) is not None:
            # StreamEvent
            event = message.event
            if not isinstance(event, dict):
                continue
            ev_type = event.get("type")
            if ev_type == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield TextChunk(text=text)
            elif ev_type == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "tool_use":
                    current_tool_name = block.get("name", "")
                    current_tool_use_id = block.get("id", "")
                    current_tool_input = block.get("input") or {}
                    yield ToolStatusChunk(
                        tool_name=current_tool_name,
                        tool_use_id=current_tool_use_id,
                        tool_input=current_tool_input,
                    )
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": current_tool_use_id,
                            "name": current_tool_name,
                            "input": current_tool_input,
                        }
                    )
            elif ev_type == "content_block_stop":
                pass
        elif getattr(message, "content", None) is not None:
            # AssistantMessage: may contain full blocks including tool_result
            content = message.content
            if isinstance(content, list):
                for block in content:
                    if getattr(block, "type", None) == "tool_result":
                        tool_use_id = (
                            getattr(block, "tool_use_id", "") or current_tool_use_id
                        )
                        result_text = ""
                        if getattr(block, "content", None):
                            for c in (
                                block.content if isinstance(block.content, list) else []
                            ):
                                if getattr(c, "text", None):
                                    result_text += c.text
                        tool_result_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result_text,
                            }
                        )
                        if current_tool_name:
                            yield ToolResultChunk(
                                tool_name=current_tool_name,
                                tool_use_id=tool_use_id or "",
                                result=result_text,
                            )
                if assistant_blocks and tool_result_blocks:
                    yield ToolTurnComplete(
                        assistant_blocks=assistant_blocks,
                        tool_result_blocks=tool_result_blocks,
                    )
                    assistant_blocks = []
                    tool_result_blocks = []
                    current_tool_use_id = None
                    current_tool_name = None
        if getattr(message, "usage", None) is not None and usage_out is not None:
            u = message.usage
            if hasattr(usage_out, "input_tokens"):
                usage_out.input_tokens = getattr(u, "input_tokens", 0) or 0
            if hasattr(usage_out, "output_tokens"):
                usage_out.output_tokens = getattr(u, "output_tokens", 0) or 0


RETROSPECTIVE_SYSTEM_PROMPT = (
    "You are Dale's personal AI assistant writing a monthly retrospective. "
    "Be warm, direct, and encouraging."
)


async def run_retrospective_via_sdk(
    user_id: int,
    period: str,
    conversation_analyzer: Any,
    *,
    model: str | None = None,
) -> str:
    """
    Run a retrospective via the Claude Agent SDK (single completion, no tools).
    Uses conversation_analyzer to gather stats and goals; builds prompt and calls SDK query().
    Returns the retrospective text. Used by /retrospective when SDK is available.
    Returns empty string if SDK unavailable so caller can use ConversationAnalyzer.generate_retrospective.
    """
    if not is_sdk_available():
        return ""

    from ..analytics.analyzer import _parse_period
    from ..config import settings

    start, _end = _parse_period(period)
    stats = await conversation_analyzer.get_stats(user_id, period)
    active_goals = await conversation_analyzer.get_active_goals_with_age(user_id)
    completed_goals = await conversation_analyzer.get_completed_goals_since(
        user_id, start
    )

    month_name = (
        start.strftime("%B %Y") if period in ("month", "30d") else stats["period_label"]
    )

    stats_block = (
        f"Period: {stats['period_label']}\n"
        f"Messages from user: {stats['user_messages']}\n"
        f"Active days: {stats['active_days']} / {stats['period_days']}\n"
    )
    if active_goals:
        active_lines = [
            f"- {g['title']} (active for {g.get('created_at_age', 'unknown')}, "
            f"last update {g.get('updated_at_age', 'unknown')})"
            for g in active_goals[:10]
        ]
        active_block = "Active goals:\n" + "\n".join(active_lines)
    else:
        active_block = "Active goals: none"
    if completed_goals:
        completed_lines = [f"- {g['title']}" for g in completed_goals[:10]]
        completed_block = "Completed this period:\n" + "\n".join(completed_lines)
    else:
        completed_block = "Completed this period: none"

    prompt = (
        f"Write a personal retrospective for Dale for {month_name}.\n\n"
        f"Data:\n{stats_block}\n{active_block}\n\n{completed_block}\n\n"
        "Format as a Telegram message with Markdown. Include:\n"
        "1. A brief headline (1 sentence — celebrate a win or acknowledge a quiet period)\n"
        "2. Highlights / wins (from completed goals, or conversation activity)\n"
        "3. Still in progress (active goals, gently call out any stale ones)\n"
        "4. Suggested focus for next period (1–3 items based on active goals)\n"
        "5. One encouraging closing sentence\n\n"
        "Tone: warm, honest, ADHD-friendly. No corporate jargon. Max 300 words."
    )

    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError:
        return ""

    model = model or getattr(settings, "model_complex", None) or settings.model_complex
    options = ClaudeAgentOptions(
        system_prompt=RETROSPECTIVE_SYSTEM_PROMPT,
        model=model,
        mcp_servers={},
        allowed_tools=[],
        include_partial_messages=False,
    )

    chunks: list[str] = []
    try:
        async for message in query(prompt=prompt, options=options):
            if getattr(message, "content", None):
                if isinstance(message.content, str):
                    chunks.append(message.content)
                elif isinstance(message.content, list):
                    for block in message.content:
                        if getattr(block, "text", None):
                            chunks.append(block.text)
                        elif isinstance(block, dict) and block.get("type") == "text":
                            chunks.append(block.get("text", ""))
    except Exception as e:
        logger.warning("SDK retrospective failed: %s", e)
        return (
            f"📅 *Monthly Retrospective — {month_name}*\n\n"
            "_(Claude unavailable — stats summary)_\n\n"
            + conversation_analyzer.format_stats_message(stats)
        )

    body = "".join(chunks).strip()
    header = f"📅 *Monthly Retrospective — {month_name}*\n\n"
    return header + (
        body if body else conversation_analyzer.format_stats_message(stats)
    )
