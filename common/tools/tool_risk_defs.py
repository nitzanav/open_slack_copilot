"""Definitions for tools that require user confirmation before execution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolRiskSpec:
    """How a risky tool is presented in the generic confirmation UI."""

    tool_name: str
    text_param_key: str
    ephemeral_notification_text: str
    confirmation_header_markdown: str
    requires_confirmation: bool = True
    """If False, the runner may execute immediately (no registry entry uses this yet)."""
    extra_param_keys_to_display: tuple[str, ...] = ()
    """Non-text parameters to show as JSON (omit obvious / text-only tools)."""


TOOL_RISK_SPECS: dict[str, ToolRiskSpec] = {
    "send_slack_pm": ToolRiskSpec(
        tool_name="send_slack_pm",
        text_param_key="message",
        ephemeral_notification_text="Confirm pending action",
        confirmation_header_markdown=(
            "*Direct message*\n"
            "This will be sent as a private Slack message to the selected member."
        ),
        extra_param_keys_to_display=(),
    ),
}


def get_tool_risk_spec(tool_name: str) -> ToolRiskSpec | None:
    return TOOL_RISK_SPECS.get(tool_name)
