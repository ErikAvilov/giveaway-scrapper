"""Desktop Gleam enter bot bridge (Selenium via sibling Gleam-giveaway-bot/)."""

from __future__ import annotations

from app.gleam_enter.service import (
    EnterGleamResult,
    enter_gleam_queue,
    gleam_entry_url,
    mark_entered_from_bot_summary,
    parse_bot_summary,
)

__all__ = [
    "EnterGleamResult",
    "enter_gleam_queue",
    "gleam_entry_url",
    "mark_entered_from_bot_summary",
    "parse_bot_summary",
]
