import hashlib
import inspect
import json
import re
import threading
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from config.config import settings

DEFAULT_TTL_SECONDS = 7 * 24 * 3600

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

T = TypeVar("T")

_CACHE_CONFIG = settings.cache
_FILENAME_MAX = _CACHE_CONFIG.get("filename_max", 200)
_VALUE_SEGMENT_MAX = _CACHE_CONFIG.get("value_segment_max", 120)
_BAD_PATH_CHARS = re.compile(r'[/\\:*?"<>|\n\r\x00]')


def _unwrap(f: Callable[..., Any]) -> Callable[..., Any]:
    cur: Any = f
    while hasattr(cur, "__wrapped__"):
        cur = cur.__wrapped__
    return cur


def _safe_segment(s: str, max_len: int = _VALUE_SEGMENT_MAX) -> str:
    t = _BAD_PATH_CHARS.sub("_", s).strip()
    if not t:
        return "_"
    if len(t) > max_len:
        h = hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()[:10]
        t = t[: max_len - 11] + "_" + h
    return t


def _value_slug(v: Any) -> str:
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return _safe_segment(v, _VALUE_SEGMENT_MAX)
    try:
        raw = json.dumps(v, sort_keys=True, default=str, separators=(",", ":"))
    except TypeError:
        raw = repr(v)
    return _safe_segment(raw, _VALUE_SEGMENT_MAX)


def _args_key_filename(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    unwrapped = _unwrap(func)
    parts: list[tuple[str, str]] = []
    try:
        sig = inspect.signature(unwrapped)
        bound = sig.bind_partial(*args, **kwargs)
        for name, val in bound.arguments.items():
            if name in ("self", "cls"):
                continue
            parts.append((name, _value_slug(val)))
    except (TypeError, ValueError):
        for i, val in enumerate(args):
            parts.append((f"arg{i}", _value_slug(val)))
        for k in sorted(kwargs):
            parts.append((str(k), _value_slug(kwargs[k])))

    if not parts:
        body = "no_args"
    else:
        body = "__".join(f"{_safe_segment(k, 48)}_{v}" for k, v in parts)

    if len(body) > _FILENAME_MAX:
        h = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()[:16]
        body = body[: _FILENAME_MAX - 18] + "__" + h

    return _safe_segment(body, _FILENAME_MAX) + ".json"


def _class_and_func_dirs(func: Callable[..., Any]) -> tuple[str, str]:
    unwrapped = _unwrap(func)
    q = getattr(unwrapped, "__qualname__", "") or unwrapped.__name__
    q = _BAD_PATH_CHARS.sub("_", q)
    if "." in q:
        cls_part, name = q.rsplit(".", 1)
        return _safe_segment(cls_part, 80), _safe_segment(name, 80)
    return "_", _safe_segment(q, 80)


def _cache_file_path(
    cache_dir: Path,
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Path:
    cls_dir, fn_dir = _class_and_func_dirs(func)
    name = _args_key_filename(func, args, kwargs)
    return cache_dir / cls_dir / fn_dir / name


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, default=str) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _read_cache_entry(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None


def cache(
    func: Callable[..., T] | None = None,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    cache_dir: Path | None = None,
):
    """File-backed TTL cache under ``cache_dir`` (default: project ``.cache``).

    Layout: ``{cache_dir}/{class_qualname}/{function_name}/{args...}.json``
    Each file is JSON with ``timestamp``, ``expiry_time`` (Unix wall time), and ``output``.
    """

    base = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        lock = threading.Lock()

        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            path = _cache_file_path(base, f, args, kwargs)
            now = time.time()
            with lock:
                entry = _read_cache_entry(path)
                if entry is not None:
                    try:
                        exp = float(entry["expiry_time"])
                        if now < exp:
                            return entry["output"]
                    except (KeyError, TypeError, ValueError):
                        pass
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

            value = f(*args, **kwargs)
            payload = {
                "timestamp": now,
                "expiry_time": now + ttl_seconds,
                "output": _json_normalize(value),
            }
            with lock:
                _atomic_write_json(path, payload)
            return value

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def _json_normalize(value: Any) -> Any:
    """Round-trip via JSON; non-JSON types become strings."""
    return json.loads(json.dumps(value, default=str))
