"""Runtime hook: FunASR reads class source at import time, which frozen builds lack."""
import inspect

_getsourcelines = inspect.getsourcelines
_getsource = inspect.getsource


def _safe_getsourcelines(obj):
    try:
        return _getsourcelines(obj)
    except (OSError, IOError, TypeError):
        return ([""], 0)


def _safe_getsource(obj):
    try:
        return _getsource(obj)
    except (OSError, IOError, TypeError):
        return ""


inspect.getsourcelines = _safe_getsourcelines
inspect.getsource = _safe_getsource
