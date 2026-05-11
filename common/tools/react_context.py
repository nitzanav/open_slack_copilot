"""Invocation context for tool handlers during the ReAct (reason + act) loop."""

from contextvars import ContextVar

_invocation: ContextVar[dict | None] = ContextVar("copilot_invocation", default=None)


class react_invocation_context:
    """Holds channel_id, thread_ts, user_id, context_kind, skill_id, action_ts for tool handlers."""

    def __init__(
        self,
        channel_id: str,
        thread_ts: str,
        user_id: str,
        *,
        context_kind: str = "thread",
        skill_id: str | None = None,
        action_ts: str | None = None,
    ):
        self._data = {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "context_kind": (context_kind or "thread").strip() or "thread",
            "skill_id": (skill_id or "").strip() or None,
            "action_ts": (action_ts or "").strip() or None,
        }
        self._token = None

    def __enter__(self) -> dict:
        self._token = _invocation.set(self._data)
        return self._data

    def __exit__(self, *args):
        _invocation.reset(self._token)


def get_invocation() -> dict | None:
    return _invocation.get()
