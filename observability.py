"""Two observability layers for MCP tool calls.

- debug log: JSON lines, machine-readable, meant for grepping/monitoring.
- decision log: plain language, meant for category buyers to audit what
  the agent checked and why it did what it did.
"""

import json
import logging
import time
from functools import wraps
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "tool": getattr(record, "tool", None),
            "event": getattr(record, "event", None),
        }
        payload.update(getattr(record, "data", {}))
        return json.dumps(payload, default=str)


def _make_logger(name: str, path: Path, formatter: logging.Formatter) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


_debug_logger = _make_logger("korral.debug", LOG_DIR / "debug.jsonl", JsonLineFormatter())
_decision_logger = _make_logger(
    "korral.decisions", LOG_DIR / "decisions.log", logging.Formatter("%(asctime)s  %(message)s")
)


def log_debug(tool: str, event: str, **data) -> None:
    _debug_logger.debug("", extra={"tool": tool, "event": event, "data": data})


def log_decision(message: str) -> None:
    _decision_logger.info(message)


def log_tool_call(func):
    """Wrap an MCP tool with machine-readable debug logging.

    Buyer-facing decision logging is added separately inside each tool,
    since only the tool knows the reasoning behind its result.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        tool = func.__name__
        start = time.monotonic()
        log_debug(tool, "start", kwargs=kwargs)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            duration_ms = round((time.monotonic() - start) * 1000, 1)
            log_debug(
                tool, "error", kwargs=kwargs, duration_ms=duration_ms,
                error_type=type(exc).__name__, error=str(exc),
            )
            log_decision(f"[{tool}] failed for {kwargs}: {exc}")
            raise
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log_debug(tool, "success", kwargs=kwargs, duration_ms=duration_ms, result=result)
        return result

    return wrapper
