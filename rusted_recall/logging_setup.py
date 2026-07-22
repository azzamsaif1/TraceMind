"""Structured JSON logging with correlation/workspace/recall/asset/job context.

Directive section 18: structured backend logs carrying request id, workspace id,
recall id, asset id, job id, provider, operation, duration, retry count, error
category, and B2 object keys — never secrets.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Context carried across a logical operation and merged into every log record.
_log_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "rusted_recall_log_context", default=None
)


def _ctx() -> dict[str, Any]:
    return _log_context.get() or {}

_STANDARD_ATTRS = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}

# Keys that must never be logged even if accidentally attached.
_SECRET_KEYS = {"b2_app_key", "b2_key_id", "api_key", "gmicloud_api_key", "authorization"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_ctx())
        # Attach any structured 'extra' fields.
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Redact anything sensitive.
        for k in list(payload.keys()):
            if k.lower() in _SECRET_KEYS:
                payload[k] = "***redacted***"
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Bind structured fields for the duration of the block."""
    current = dict(_ctx())
    current.update({k: v for k, v in fields.items() if v is not None})
    token = _log_context.set(current)
    try:
        yield
    finally:
        _log_context.reset(token)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
