import asyncio
import json

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from dave import agent, tools
from dave.cli import main
from dave.tools.defaults import trip_defaults


def test_registry_exposes_every_tool():
    assert [t.name for t in tools.TOOLS] == ["trip_defaults"]
    assert tools.allowed_tool_names() == ["mcp__dave__trip_defaults"]


def test_server_registers_tools():
    server = tools.build_server()
    assert server["type"] == "sdk"
    assert server["name"] == tools.SERVER_NAME


def test_trip_defaults_tool():
    result = asyncio.run(trip_defaults.handler({}))
    data = json.loads(result["content"][0]["text"])
    assert data["max_drive_hours_per_day"] == 5
    assert data["hookups_required"] == ["electric", "water"]


def test_system_prompt_includes_context(tmp_path):
    (tmp_path / "product.md").write_text("PRODUCT RULES")
    (tmp_path / "domain.md").write_text("DOMAIN RULES")
    prompt = agent.system_prompt(tmp_path)
    assert prompt.startswith("You are Dave")
    assert "PRODUCT RULES" in prompt and "DOMAIN RULES" in prompt


def test_options_only_allow_dave_tools():
    options = agent.build_options()
    assert options.tools == []
    assert options.allowed_tools == tools.allowed_tool_names()
    assert set(options.mcp_servers) == {tools.SERVER_NAME}
    assert options.model == agent.MODEL


def fake_query(*replies):
    calls = []

    async def run(*, prompt, options):
        calls.append(prompt)
        yield AssistantMessage(
            content=[ToolUseBlock(id="t1", name="mcp__dave__trip_defaults", input={})],
            model=agent.MODEL,
        )
        for text in replies:
            yield AssistantMessage(content=[TextBlock(text=text)], model=agent.MODEL)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
        )

    return run, calls


def test_plan_collects_assistant_text():
    run, calls = fake_query("Day 1: Denver", "Day 2: Moab")
    reply = asyncio.run(agent.plan("5 nights from Denver", options=agent.build_options(), run=run))
    assert reply == "Day 1: Denver\nDay 2: Moab"
    assert calls == ["5 nights from Denver"]


def test_cli_plan(monkeypatch, capsys):
    run, calls = fake_query("Here is your trip.")
    monkeypatch.setattr(agent, "query", run)
    assert main(["plan", "weekend near Austin"]) == 0
    assert "Here is your trip." in capsys.readouterr().out
    assert calls == ["weekend near Austin"]
