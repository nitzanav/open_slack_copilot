"""Persistent Slack copilot conversations (messages + multi-step skill state).

The on-disk record is just a serialized :class:`Conversation` dataclass. All
reads go through typed fields; the JSON shape is an implementation detail of
this module. ``Conversation`` carries its own ordered ``steps`` dict (name ->
instruction) so callers can write ``conversation.steps[step_name]`` directly.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from common.data_layer import data_layer
from common.slack import agent_log

COLLECTION = "conversations"


def _collection():
    return data_layer.get_collection(COLLECTION)


def make_conversation_id() -> str:
    """Generate a fresh, opaque conversation id."""
    return uuid.uuid4().hex


@dataclass
class Conversation:
    """In-memory view of a persisted conversation row.

    Every field is typed and has a sensible default, so callers read attributes
    directly (``conversation.last_final_text``, ``conversation.steps[name]``)
    without `.get` / `.strip` boilerplate.
    """

    id: str = ""
    skill_id: str | None = None
    channel_id: str = ""
    thread_ts: str = ""
    action_ts: str = ""
    requester_user_id: str = ""
    prepare_user_id: str = ""
    channel_name: str | None = None
    context_kind: str = "thread"
    steps: dict[str, str] = field(default_factory=dict)
    current_step: str = ""
    is_waiting_for_confirmation: bool = False
    is_end: bool = False
    last_final_text: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)

    @property
    def first_step_name(self) -> str:
        return next(iter(self.steps), "main")

    @property
    def current_or_first_step(self) -> str:
        """Current step name, falling back to the first defined step."""
        return self.current_step or self.first_step_name

    def next_step_after(self, completed_step_name: str) -> str | None:
        """Name of the step after ``completed_step_name``, or None if last."""
        names = list(self.steps.keys())
        try:
            idx = names.index(completed_step_name)
        except ValueError:
            return None
        return names[idx + 1] if idx + 1 < len(names) else None

    def copy_messages_for_llm(self) -> list[dict[str, Any]]:
        """Deep copy of messages for the completion backend (may mutate)."""
        return copy.deepcopy(self.messages)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Conversation":
        return cls(
            id=data["conversation_id"],
            skill_id=data["skill_id"],
            channel_id=data["channel_id"],
            thread_ts=data["thread_ts"],
            action_ts=data["action_ts"],
            requester_user_id=data["requester_user_id"],
            prepare_user_id=data["prepare_user_id"],
            channel_name=data["channel_name"],
            context_kind=data["context_kind"],
            steps=dict(data["steps"]),
            current_step=data["current_step"],
            is_waiting_for_confirmation=data["is_waiting_for_confirmation"],
            is_end=data["is_end"],
            last_final_text=data.get("last_final_text", ""),
            messages=list(data["messages"]),
            tool_trace=list(data["tool_trace"]),
            tool_errors=list(data["tool_errors"]),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "conversation_id": self.id,
            "skill_id": self.skill_id,
            "channel_id": self.channel_id,
            "thread_ts": self.thread_ts,
            "action_ts": self.action_ts,
            "requester_user_id": self.requester_user_id,
            "prepare_user_id": self.prepare_user_id,
            "channel_name": self.channel_name,
            "context_kind": self.context_kind,
            "steps": dict(self.steps),
            "current_step": self.current_step,
            "is_waiting_for_confirmation": self.is_waiting_for_confirmation,
            "is_end": self.is_end,
            "last_final_text": self.last_final_text,
            "messages": list(self.messages),
            "tool_trace": list(self.tool_trace),
            "tool_errors": list(self.tool_errors),
        }


def create(
    *,
    conversation_id: str,
    skill_id: str | None,
    channel_id: str,
    thread_ts: str,
    action_ts: str,
    requester_user_id: str,
    prepare_user_id: str,
    channel_name: str | None,
    context_kind: str,
    steps: dict[str, str],
    messages: list[dict[str, Any]],
) -> Conversation:
    conversation = Conversation(
        id=conversation_id,
        skill_id=skill_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
        action_ts=action_ts,
        requester_user_id=requester_user_id,
        prepare_user_id=prepare_user_id,
        channel_name=channel_name,
        context_kind=context_kind or "thread",
        steps=dict(steps),
        messages=list(messages),
    )
    save(conversation)
    return conversation


def get(conversation_id: str) -> Conversation | None:
    data = _collection().get((conversation_id or "").strip())
    return Conversation.from_json(data) if isinstance(data, dict) else None


def save(conversation: Conversation) -> None:
    if not conversation.id:
        raise ValueError("conversation missing id")
    _collection().set(conversation.id, conversation.to_json())


def append_message(
    conversation_id: str,
    role: str,
    content: str,
    **extra: Any,
) -> None:
    conversation = get(conversation_id)
    if not conversation:
        return
    msg: dict[str, Any] = {"role": role, "content": content or ""}
    msg.update(extra)
    conversation.messages.append(msg)
    save(conversation)


def set_current_step(conversation_id: str, step_name: str) -> None:
    conversation = get(conversation_id)
    if not conversation:
        return
    conversation.current_step = step_name
    save(conversation)


def mark_waiting_for_confirmation(conversation_id: str, value: bool) -> None:
    conversation = get(conversation_id)
    if not conversation:
        return
    conversation.is_waiting_for_confirmation = value
    save(conversation)


def mark_end(conversation_id: str) -> None:
    conversation = get(conversation_id)
    if not conversation:
        return
    conversation.is_end = True
    conversation.current_step = "END"
    save(conversation)


def merge_loop_result(
    conversation_id: str,
    *,
    tool_trace: list[Any],
    tool_errors: list[str],
    final_text: str,
) -> None:
    conversation = get(conversation_id)
    if not conversation:
        return
    conversation.tool_trace.extend(agent_log.tool_trace_for_record(tool_trace))
    conversation.tool_errors.extend(tool_errors)
    if final_text.strip():
        conversation.last_final_text = final_text.strip()
    save(conversation)


def replace_messages(conversation_id: str, messages: list[dict[str, Any]]) -> None:
    conversation = get(conversation_id)
    if not conversation:
        return
    conversation.messages = copy.deepcopy(messages)
    save(conversation)
