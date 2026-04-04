import functools
import json
import logging
from typing import Any

from config.config import settings

_logger = logging.getLogger("open_slack_copilot")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _logger.addHandler(logging.StreamHandler())

_REDACT_KEYS = frozenset(
    {
        "token",
        "response_url",
        "trigger_id",
        "client_secret",
        "access_token",
        "refresh_token",
        "password",
        "app_password",
    }
)

_LOG_SANITIZE_CONFIG = settings.log_sanitize
_DEFAULT_MAX_STR = _LOG_SANITIZE_CONFIG.get("max_str", 500)
_DEFAULT_MAX_LIST = _LOG_SANITIZE_CONFIG.get("max_list", 8)
_DEFAULT_MAX_DEPTH = _LOG_SANITIZE_CONFIG.get("max_depth", 12)


def _to_json(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _sanitize(
    obj: Any,
    *,
    depth: int = 0,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_str: int = _DEFAULT_MAX_STR,
    max_list: int = _DEFAULT_MAX_LIST,
) -> Any:
    """Copy-safe shrink + redact for log output (Slack payloads, LLM prompts, etc.)."""
    if depth > max_depth:
        return "<max depth>"
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    if isinstance(obj, str):
        if len(obj) > max_str:
            return f"{obj[:max_str]}... [truncated, {len(obj)} chars total]"
        return obj
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            ks = k.lower() if isinstance(k, str) else ""
            if isinstance(k, str) and (
                ks in _REDACT_KEYS or ks.endswith("_token") or "secret" in ks
            ):
                out[k] = "<redacted>"
            elif isinstance(k, str) and ks == "blocks":
                bl = v if isinstance(v, list) else []
                out[k] = f"<{len(bl)} blocks>"
            else:
                out[k] = _sanitize(
                    v, depth=depth + 1, max_depth=max_depth, max_str=max_str, max_list=max_list
                )
        return out
    if isinstance(obj, (list, tuple)):
        n = len(obj)
        if n > max_list:
            head = [
                _sanitize(x, depth=depth + 1, max_depth=max_depth, max_str=max_str, max_list=max_list)
                for x in obj[:max_list]
            ]
            return [*head, f"... and {n - max_list} more items"]
        return [
            _sanitize(x, depth=depth + 1, max_depth=max_depth, max_str=max_str, max_list=max_list)
            for x in obj
        ]
    return str(obj)


def log(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        name = fn.__name__
        safe = {
            "args": _sanitize(list(args)),
            "kwargs": _sanitize(dict(kwargs)),
        }
        _logger.info("%s started %s", name, _to_json(safe))
        try:
            result = fn(*args, **kwargs)
            _logger.info("%s returned %s", name, _to_json(_sanitize(result)))
            return result
        except Exception as e:
            _logger.error("%s raised %s: %s", name, type(e).__name__, e)
            raise

    return wrapper
