"""Dave's orchestrator: a Claude Agent SDK loop over the tools in `dave.tools`."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

from dave import tools

MODEL = "claude-opus-5-5"
MAX_TURNS = 20
CONTEXT_DIR = Path(__file__).resolve().parents[2] / "context"
PROMPT_FILES = ("product.md", "domain.md")

ROLE = """You are Dave, an AI travel agent for RVers. Plan low-cost, fun RV road trips that the \
user's RV physically fits. Use your tools for facts (dimensions, routes, campgrounds, prices) \
instead of guessing. Never book or pay for anything: prepare booking proposals for a human to \
approve."""


def system_prompt(context_dir: Path = CONTEXT_DIR) -> str:
    parts = [ROLE] + [(context_dir / name).read_text().strip() for name in PROMPT_FILES]
    return "\n\n".join(parts)


def build_options(context_dir: Path = CONTEXT_DIR) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=system_prompt(context_dir),
        mcp_servers={tools.SERVER_NAME: tools.build_server()},
        tools=[],  # no built-in Claude Code tools (Bash, Edit...): Dave only uses its own
        allowed_tools=tools.allowed_tool_names(),
        model=MODEL,
        max_turns=MAX_TURNS,
    )


async def plan(
    request: str,
    *,
    options: ClaudeAgentOptions | None = None,
    run: Callable[..., AsyncIterator] | None = None,
) -> str:
    """Send a trip request to the agent and return its text reply."""
    texts: list[str] = []
    run = run or query  # looked up at call time so tests can patch it
    async for message in run(prompt=request, options=options or build_options()):
        if isinstance(message, AssistantMessage):
            texts += [b.text for b in message.content if isinstance(b, TextBlock)]
    return "\n".join(texts)
