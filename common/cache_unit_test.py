import time
from unittest.mock import Mock

from common.cache import DEFAULT_TTL_SECONDS, cache


def test_cache_returns_same_value_without_calling_twice():
    inner = Mock(return_value=42)

    @cache(ttl_seconds=60)
    def fn(x: int) -> int:
        return inner(x)

    assert fn(1) == 42
    assert fn(1) == 42
    inner.assert_called_once_with(1)


def test_cache_expires_after_ttl():
    inner = Mock(return_value="a")

    @cache(ttl_seconds=0.05)
    def fn() -> str:
        return inner()

    assert fn() == "a"
    assert fn() == "a"
    inner.assert_called_once()
    time.sleep(0.08)
    assert fn() == "a"
    assert inner.call_count == 2


def test_cache_bare_decorator_uses_default_ttl():
    assert DEFAULT_TTL_SECONDS == 7 * 24 * 3600

    inner = Mock(return_value=0)

    @cache
    def fn() -> int:
        return inner()

    fn()
    fn()
    inner.assert_called_once()
