import time
from unittest.mock import Mock

from common.cache import DEFAULT_TTL_SECONDS, cache


def test_cache_returns_same_value_without_calling_twice(tmp_path):
    inner = Mock(return_value=42)

    @cache(ttl_seconds=60, cache_dir=tmp_path)
    def fn(x: int) -> int:
        return inner(x)

    assert fn(1) == 42
    assert fn(1) == 42
    inner.assert_called_once_with(1)


def test_cache_expires_after_ttl(tmp_path):
    inner = Mock(return_value="a")

    @cache(ttl_seconds=0.05, cache_dir=tmp_path)
    def fn() -> str:
        return inner()

    assert fn() == "a"
    assert fn() == "a"
    inner.assert_called_once()
    time.sleep(0.08)
    assert fn() == "a"
    assert inner.call_count == 2


def test_cache_bare_decorator_uses_default_ttl(tmp_path):
    assert DEFAULT_TTL_SECONDS == 7 * 24 * 3600

    inner = Mock(return_value=0)

    @cache(cache_dir=tmp_path)
    def fn() -> int:
        return inner()

    fn()
    fn()
    inner.assert_called_once()
