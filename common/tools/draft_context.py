from contextvars import ContextVar

_invocation: ContextVar[dict | None] = ContextVar("copilot_invocation", default=None)


class draft_invocation_context:
    """Holds channel_id, thread_ts, user_id for tool handlers during draft generation."""

    def __init__(self, channel_id: str, thread_ts: str, user_id: str):
        self._data = {"channel_id": channel_id, "thread_ts": thread_ts, "user_id": user_id}
        self._token = None

    def __enter__(self) -> dict:
        self._token = _invocation.set(self._data)
        return self._data

    def __exit__(self, *args):
        _invocation.reset(self._token)


def get_invocation() -> dict | None:
    return _invocation.get()

