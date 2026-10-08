"""Placeholder tool: reports the trip defaults Dave applies when the user doesn't say otherwise."""

import json

from claude_agent_sdk import tool

from dave.models import ConstraintSpec


@tool(
    "trip_defaults",
    "Default trip constraints (max driving hours per day, required hookups, interest weights) "
    "applied when the user doesn't specify them.",
    {},
)
async def trip_defaults(args: dict) -> dict:
    fields = ConstraintSpec.model_fields
    defaults = {
        "max_drive_hours_per_day": fields["max_drive_hours_per_day"].default,
        "hookups_required": sorted(
            fields["hookups_required"].get_default(call_default_factory=True)
        ),
        "travelers": fields["travelers"].default,
        "interests": fields["interests"].get_default(call_default_factory=True).model_dump(),
    }
    return {"content": [{"type": "text", "text": json.dumps(defaults)}]}
