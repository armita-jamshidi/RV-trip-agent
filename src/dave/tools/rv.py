"""Tool: identify the traveler's RV from how they describe it."""

from claude_agent_sdk import tool

from dave.rv_catalog import identify_rv


@tool(
    "identify_rv",
    "Identify the traveler's RV (make, model line, floorplan, year, class) from their own words, "
    "e.g. 'our 2023 Minnie Winnie 31'. Returns one match, or candidates to ask the traveler "
    "about, or neither if the RV isn't in the catalog.",
    {"text": str},
)
async def identify_rv_tool(args: dict) -> dict:
    result = identify_rv(args["text"])
    return {"content": [{"type": "text", "text": result.model_dump_json(exclude_none=True)}]}
