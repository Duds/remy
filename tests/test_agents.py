"""
Tests for remy/agents/ — Board of Directors sub-agents and orchestrator.

All Claude calls are mocked — no real API calls are made.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remy.agents.base_agent import SubAgent
from remy.agents.strategy import StrategyAgent
from remy.agents.content import ContentAgent
from remy.agents.finance import FinanceAgent
from remy.agents.researcher import ResearcherAgent
from remy.agents.critic import CriticAgent
from remy.agents.orchestrator import BoardOrchestrator


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def make_claude_client(response: str = "Mock analysis response") -> MagicMock:
    """Return a mock ClaudeClient whose complete() returns a fixed string."""
    client = MagicMock()
    client.complete = AsyncMock(return_value=response)
    return client


# --------------------------------------------------------------------------- #
# SubAgent base class                                                          #
# --------------------------------------------------------------------------- #

def test_sub_agent_is_abstract():
    """SubAgent cannot be instantiated directly."""
    client = make_claude_client()
    with pytest.raises(TypeError):
        SubAgent(client)  # type: ignore[abstract]


def test_build_context_block_empty():
    """_build_context_block returns empty string with no thread and no context."""
    client = make_claude_client()
    agent = StrategyAgent(client)
    result = agent._build_context_block([], "")
    assert result == ""


def test_build_context_block_with_user_context():
    """User context appears wrapped in <user_context> tags."""
    client = make_claude_client()
    agent = StrategyAgent(client)
    result = agent._build_context_block([], "<goals>my goal</goals>")
    assert "<user_context>" in result
    assert "my goal" in result


def test_build_context_block_with_thread():
    """Prior thread analyses appear in <prior_analyses>."""
    client = make_claude_client()
    agent = StrategyAgent(client)
    thread = [{"role": "assistant", "content": "Strategy: focus on X"}]
    result = agent._build_context_block(thread, "")
    assert "<prior_analyses>" in result
    assert "focus on X" in result


def test_build_context_block_with_both():
    """Both user context and prior thread appear when provided."""
    client = make_claude_client()
    agent = StrategyAgent(client)
    thread = [{"role": "assistant", "content": "Some prior analysis"}]
    result = agent._build_context_block(thread, "user context here")
    assert "<user_context>" in result
    assert "<prior_analyses>" in result
    assert "user context here" in result
    assert "Some prior analysis" in result


# --------------------------------------------------------------------------- #
# Individual agent metadata                                                    #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("AgentClass,expected_name", [
    (StrategyAgent, "Strategy"),
    (ContentAgent, "Content"),
    (FinanceAgent, "Finance"),
    (ResearcherAgent, "Researcher"),
    (CriticAgent, "Critic"),
])
def test_agent_has_name(AgentClass, expected_name):
    """Each agent has the expected name attribute."""
    client = make_claude_client()
    agent = AgentClass(client)
    assert agent.name == expected_name


@pytest.mark.parametrize("AgentClass", [
    StrategyAgent, ContentAgent, FinanceAgent, ResearcherAgent, CriticAgent,
])
def test_agent_has_non_empty_role_description(AgentClass):
    """Each agent has a non-empty role_description."""
    client = make_claude_client()
    agent = AgentClass(client)
    assert agent.role_description.strip()


@pytest.mark.parametrize("AgentClass", [
    StrategyAgent, ContentAgent, FinanceAgent, ResearcherAgent, CriticAgent,
])
def test_agent_has_system_prompt(AgentClass):
    """Each agent has a non-empty system_prompt."""
    client = make_claude_client()
    agent = AgentClass(client)
    assert len(agent.system_prompt) > 50  # must be a real prompt, not a placeholder


# --------------------------------------------------------------------------- #
# Individual agent analyze() calls                                             #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_strategy_agent_calls_claude():
    """StrategyAgent.analyze() calls claude_client.complete() with the topic."""
    client = make_claude_client("Focus on product-market fit.")
    agent = StrategyAgent(client)
    result = await agent.analyze("How do I grow my SaaS?", [], "")
    assert result == "Focus on product-market fit."
    client.complete.assert_called_once()
    call_kwargs = client.complete.call_args
    assert "How do I grow my SaaS?" in str(call_kwargs)


@pytest.mark.asyncio
async def test_content_agent_includes_prior_thread():
    """ContentAgent passes prior thread into its prompt."""
    client = make_claude_client("Write a compelling newsletter.")
    agent = ContentAgent(client)
    thread = [{"role": "assistant", "content": "Strategy: prioritise email"}]
    result = await agent.analyze("Grow audience", thread, "")
    assert result == "Write a compelling newsletter."
    call_kwargs = client.complete.call_args
    # The prior analysis should appear in the user content
    assert "prioritise email" in str(call_kwargs)


@pytest.mark.asyncio
async def test_finance_agent_returns_analysis():
    """FinanceAgent.analyze() returns the claude response."""
    client = make_claude_client("Monthly burn: $5k. Break-even in 6 months.")
    agent = FinanceAgent(client)
    result = await agent.analyze("Launch a new product", [], "")
    assert "burn" in result


@pytest.mark.asyncio
async def test_researcher_agent_returns_research_actions():
    """ResearcherAgent.analyze() returns from claude."""
    client = make_claude_client("1. Interview 5 users. 2. Check competitor pricing.")
    agent = ResearcherAgent(client)
    result = await agent.analyze("Market entry strategy", [], "")
    assert "Interview" in result


@pytest.mark.asyncio
async def test_critic_agent_returns_verdict():
    """CriticAgent.analyze() calls claude and returns response."""
    client = make_claude_client("## Challenges\nYou're too optimistic.\n## Board Verdict\nFocus on one thing.")
    agent = CriticAgent(client)
    result = await agent.analyze("Quarterly focus", [], "")
    assert "Board Verdict" in result


@pytest.mark.asyncio
async def test_agent_gracefully_handles_claude_error():
    """If claude_client.complete() raises, _call_claude returns an error string."""
    client = MagicMock()
    client.complete = AsyncMock(side_effect=RuntimeError("API down"))
    agent = StrategyAgent(client)
    result = await agent._call_claude("Some prompt")
    assert "unavailable" in result.lower() or "API down" in result


# --------------------------------------------------------------------------- #
# BoardOrchestrator                                                            #
# --------------------------------------------------------------------------- #

def test_orchestrator_agent_order():
    """Critic must be the last agent in the board."""
    client = make_claude_client()
    orchestrator = BoardOrchestrator(client)
    last_agent = orchestrator._agents[-1]
    assert isinstance(last_agent, CriticAgent)


def test_orchestrator_has_five_agents():
    """Board has exactly 5 agents."""
    client = make_claude_client()
    orchestrator = BoardOrchestrator(client)
    assert len(orchestrator._agents) == 5


@pytest.mark.asyncio
async def test_run_board_returns_formatted_report():
    """run_board() returns a report containing all agent names."""
    client = make_claude_client("Analysis complete.")
    orchestrator = BoardOrchestrator(client)

    report = await orchestrator.run_board("What should I focus on?")

    assert "Strategy" in report
    assert "Content" in report
    assert "Finance" in report
    assert "Researcher" in report
    assert "Critic" in report
    assert "Board of Directors Report" in report


@pytest.mark.asyncio
async def test_run_board_topic_in_report():
    """The topic appears in the board report header."""
    client = make_claude_client("Mock response.")
    orchestrator = BoardOrchestrator(client)

    report = await orchestrator.run_board("My quarterly focus")
    assert "My quarterly focus" in report


@pytest.mark.asyncio
async def test_run_board_agents_called_in_order():
    """Agents are called sequentially — claude.complete is called 5 times."""
    client = make_claude_client("response")
    orchestrator = BoardOrchestrator(client)

    await orchestrator.run_board("Test topic")

    # One call per agent
    assert client.complete.call_count == 5


@pytest.mark.asyncio
async def test_run_board_thread_grows_with_each_agent():
    """Each agent receives the accumulated thread from all prior agents."""
    call_prompts: list[str] = []

    async def mock_complete(messages, system, model, max_tokens, usage_out=None):
        call_prompts.append(messages[0]["content"])
        return f"Agent {len(call_prompts)} response"

    client = MagicMock()
    client.complete = AsyncMock(side_effect=mock_complete)
    orchestrator = BoardOrchestrator(client)

    await orchestrator.run_board("Thread test topic")

    # Agent 1 (Strategy) has no prior analyses
    assert "prior_analyses" not in call_prompts[0]
    # Agent 2 (Content) has Strategy's response in the thread
    assert "Agent 1 response" in call_prompts[1]
    # Agent 5 (Critic) has all prior responses
    assert "Agent 1 response" in call_prompts[4]
    assert "Agent 4 response" in call_prompts[4]


@pytest.mark.asyncio
async def test_run_board_swallows_agent_error():
    """If an agent raises, the report includes an error note but doesn't crash."""
    client = MagicMock()
    call_count = 0

    async def mock_complete(messages, system, model, max_tokens, usage_out=None):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # Content agent fails
            raise RuntimeError("Claude overloaded")
        return f"Response {call_count}"

    client.complete = AsyncMock(side_effect=mock_complete)
    orchestrator = BoardOrchestrator(client)

    report = await orchestrator.run_board("Test resilience")
    # Report should still be produced
    assert "Strategy" in report
    # The error should be noted somewhere
    assert "unavailable" in report.lower() or "Claude overloaded" in report


@pytest.mark.asyncio
async def test_run_board_streaming_yields_progress_updates():
    """run_board_streaming yields progress lines and section content."""
    client = make_claude_client("Analysis done.")
    orchestrator = BoardOrchestrator(client)

    chunks: list[str] = []
    async for chunk in orchestrator.run_board_streaming("Test topic"):
        chunks.append(chunk)

    full = "".join(chunks)
    # Should contain progress indicators
    assert "Strategy" in full
    assert "Critic" in full
    # Should contain agent section markers
    assert "📋" in full


@pytest.mark.asyncio
async def test_run_board_streaming_five_progress_then_five_sections():
    """Streaming yields alternating progress+section for each of 5 agents."""
    client = make_claude_client("section content")
    orchestrator = BoardOrchestrator(client)

    progress_chunks = []
    section_chunks = []
    toggle = True

    async for chunk in orchestrator.run_board_streaming("Test topic"):
        # Progress lines end with \n and contain an emoji+agent name
        if toggle:
            progress_chunks.append(chunk)
        else:
            section_chunks.append(chunk)
        toggle = not toggle

    assert len(progress_chunks) == 5
    assert len(section_chunks) == 5


@pytest.mark.asyncio
async def test_run_board_streaming_cancelled_early():
    """run_board_streaming respects cancellation (just that it's an async generator)."""
    client = make_claude_client("response")
    orchestrator = BoardOrchestrator(client)

    chunks = []
    gen = orchestrator.run_board_streaming("test")
    # Consume only first 2 items
    async for chunk in gen:
        chunks.append(chunk)
        if len(chunks) >= 2:
            break

    # Should have received at least 2 chunks without crashing
    assert len(chunks) >= 2


# --------------------------------------------------------------------------- #
# split_for_telegram                                                           #
# --------------------------------------------------------------------------- #

def test_split_for_telegram_short_text():
    """Short text is returned as a single-element list."""
    text = "Hello, world!"
    result = BoardOrchestrator.split_for_telegram(text)
    assert result == ["Hello, world!"]


def test_split_for_telegram_long_text():
    """Text longer than 4096 chars is split into multiple chunks."""
    text = ("A" * 4000 + "\n\n") * 3  # 3 paragraphs, each > limit
    result = BoardOrchestrator.split_for_telegram(text)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 4096


def test_split_for_telegram_preserves_content():
    """All content survives splitting (no characters dropped)."""
    text = "Para one.\n\nPara two.\n\nPara three."
    result = BoardOrchestrator.split_for_telegram(text)
    combined = "".join(result)
    # All original paragraphs should be present
    assert "Para one." in combined
    assert "Para two." in combined
    assert "Para three." in combined


def test_split_for_telegram_exact_limit():
    """Text exactly at 4096 chars returns a single chunk."""
    text = "X" * 4096
    result = BoardOrchestrator.split_for_telegram(text)
    assert len(result) == 1
    assert result[0] == text
