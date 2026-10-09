"""Tools: identify the traveler's RV from how they describe it, then look up its size."""

import anthropic
from claude_agent_sdk import tool

from dave.config import load_settings
from dave.http import CachedClient
from dave.rv_catalog import identify_rv
from dave.rv_specs import lookup_rv


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


@tool(
    "rv_dimensions",
    "Look up the traveler's RV size and specs (length, height with AC, width, GVWR, fuel type "
    "and tank, 30/50 A service) from the manufacturer's spec page. `estimated: true` means "
    "class averages: ask the traveler for their real length and height and pass them back as "
    "overrides. Asks which RV when the description matches several.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The RV as the traveler described it"},
            "length_ft": {"type": "number", "description": "Override from the traveler"},
            "height_ft": {"type": "number", "description": "Override from the traveler"},
        },
        "required": ["text"],
    },
)
async def rv_dimensions_tool(args: dict) -> dict:
    found = identify_rv(args["text"])
    if found.match is None or found.match.rv_class is None:
        options = [f"{c.make} {c.model}" for c in found.candidates]
        text = "Which RV is it? " + (", ".join(options) if options else "It isn't in the catalog.")
        if found.match:
            text = f"Is the {found.match.make} {found.match.model} a travel trailer or fifth wheel?"
        return {"content": [{"type": "text", "text": text}]}

    settings = load_settings()
    overrides = {k: args.get(k) for k in ("length_ft", "height_ft")}
    claude = anthropic.Anthropic() if "ANTHROPIC_API_KEY" in settings.keys else None
    with CachedClient(settings.cache_dir / "http", offline=settings.offline) as http:
        profile = lookup_rv(
            found.match, http, overrides=overrides, claude=claude, cache_dir=settings.cache_dir
        )
    return {"content": [{"type": "text", "text": profile.model_dump_json(exclude_none=True)}]}
