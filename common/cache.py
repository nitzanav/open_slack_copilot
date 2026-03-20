import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

DEFAULT_TTL_SECONDS = 7 * 24 * 3600

T = TypeVar("T")


def cache(func: Callable[..., T] | None = None, *, ttl_seconds: float = DEFAULT_TTL_SECONDS):
    """In-memory TTL cache. Defaults: ttl of one week."""

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        store: dict[tuple[Any, ...], tuple[float, T]] = {}
        lock = threading.Lock()

        @wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            with lock:
                hit = store.get(key)
                if hit is not None:
                    expires_at, cached = hit
                    if now < expires_at:
                        return cached
                    del store[key]
            value = f(*args, **kwargs)
            with lock:
                store[key] = (now + ttl_seconds, value)
            return value

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
