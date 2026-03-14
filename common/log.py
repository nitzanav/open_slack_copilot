import functools
import json
import logging

_logger = logging.getLogger("open_slack_copilot")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _logger.addHandler(logging.StreamHandler())


def _to_json(obj):
    return json.dumps(obj, default=str)


def log(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        name = fn.__name__
        _logger.info("%s started %s", name, _to_json({"args": list(args), "kwargs": kwargs}))
        try:
            result = fn(*args, **kwargs)
            _logger.info("%s returned %s", name, _to_json(result))
            return result
        except Exception as e:
            _logger.error("%s raised %s: %s", name, type(e).__name__, e)
            raise
    return wrapper
