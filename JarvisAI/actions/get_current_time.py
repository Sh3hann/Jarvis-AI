"""Real-time local clock, date, and timezone action for JARVIS."""
from __future__ import annotations

from datetime import datetime


def get_current_time_action(parameters: dict | None = None, player=None, session_memory=None) -> str:
    """Returns real-time exact local time, date, day of week, and timezone."""
    now = datetime.now().astimezone()
    time_12h = now.strftime("%I:%M %p").lstrip("0")
    time_24h = now.strftime("%H:%M")
    day_name = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")
    tz_name = now.tzname() or "Local Time"
    tz_offset = now.strftime("%z")
    formatted_offset = f"UTC{tz_offset[:3]}:{tz_offset[3:]}" if len(tz_offset) >= 5 else f"UTC{tz_offset}"

    speech = f"It is currently {time_12h} ({time_24h}) on {day_name}, {date_str}. Local timezone is {tz_name} ({formatted_offset})."
    if player and hasattr(player, "write_log"):
        player.write_log(f"⏰ [clock] {time_12h} · {day_name}, {date_str} ({formatted_offset})")
    return speech


TOOL = {
    "name": "get_current_time",
    "description": (
        "Returns the exact, real-time current local time, date, day of the week, and timezone. "
        "MUST be called whenever the user asks 'what time is it?', 'what is the time?', "
        "'tell me the time', 'what date is it?', or asks about the current clock time."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
    "handler": get_current_time_action,
}
