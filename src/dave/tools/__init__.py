"""Tool registry: every tool Dave can call, exposed to the agent as one in-process MCP server."""

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

from dave.tools.defaults import trip_defaults
from dave.tools.rv import identify_rv_tool, rv_dimensions_tool

SERVER_NAME = "dave"
TOOLS: list[SdkMcpTool] = [trip_defaults, identify_rv_tool, rv_dimensions_tool]


def allowed_tool_names(tools: list[SdkMcpTool] = TOOLS) -> list[str]:
    """Names the agent may call, in the SDK's `mcp__<server>__<tool>` form."""
    return [f"mcp__{SERVER_NAME}__{t.name}" for t in tools]


def build_server(tools: list[SdkMcpTool] = TOOLS):
    return create_sdk_mcp_server(name=SERVER_NAME, tools=tools)
