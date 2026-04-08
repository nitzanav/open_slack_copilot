"""Registered Slack copilot tools: LLM schema, handler, optional confirmation metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# JSON tool result when the handler showed Slack confirmation UI (Revise/Confirm), not final action.
TOOL_JSON_STATUS_CONFIRMATION_REQUESTED = "tool_confirmation_requested"

# ---------------------------------------------------------------------------
# Confirmation metadata (defined on each tool that requires user confirmation)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolConfirmationSpec:
    """How a tool that requires user confirmation is shown in the Slack confirmation UI."""

    text_param_key: str
    ephemeral_notification_text: str
    confirmation_header_markdown: str
    requires_confirmation: bool = True
    """If False, the runner may execute immediately (no registered tool uses this yet)."""
    extra_param_keys_to_display: tuple[str, ...] = ()
    """Non-text parameters to show as JSON (omit obvious / text-only tools)."""


# ---------------------------------------------------------------------------
# Registry (tools register themselves at import time)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CopilotTool:
    """One LLM-callable tool: schema, invoke handler, optional confirmation + post-confirm run."""

    name: str
    llm_schema: dict[str, Any]
    handle: Callable[[str], str]
    confirmation: ToolConfirmationSpec | None = None
    execute_after_confirm: Callable[[str, dict[str, Any]], str] | None = None


_by_name: dict[str, CopilotTool] = {}


def register_copilot_tool(tool: CopilotTool) -> None:
    if tool.name in _by_name:
        raise ValueError(f"Duplicate copilot tool registration: {tool.name!r}")
    _by_name[tool.name] = tool


def get_copilot_tool(name: str) -> CopilotTool | None:
    return _by_name.get(name)


def get_tool_confirmation_spec(tool_name: str) -> ToolConfirmationSpec | None:
    t = get_copilot_tool(tool_name)
    return t.confirmation if t else None


def dispatch_copilot_tool(name: str, arguments_json: str) -> str | None:
    t = get_copilot_tool(name)
    if not t:
        return None
    return t.handle(arguments_json)
