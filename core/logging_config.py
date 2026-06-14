from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any


request_id_var: ContextVar[str] = ContextVar("request_id", default="")
command_id_var: ContextVar[str] = ContextVar("command_id", default="")
run_id_var: ContextVar[str] = ContextVar("run_id", default="")
attempt_id_var: ContextVar[str] = ContextVar("attempt_id", default="")
slot_id_var: ContextVar[str] = ContextVar("slot_id", default="")
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _format_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            payload["exception"] = self.formatException(record.exc_info)
        ctx: dict[str, str] = {}
        for name, var in (
            ("requestId", request_id_var),
            ("commandId", command_id_var),
            ("runId", run_id_var),
            ("attemptId", attempt_id_var),
            ("slotId", slot_id_var),
            ("correlationId", correlation_id_var),
        ):
            value = var.get("")
            if value:
                ctx[name] = value
        if ctx:
            payload["context"] = ctx
        extra_keys = set(record.__dict__) - set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
        for key in extra_keys:
            if not key.startswith("_"):
                payload[key] = record.__dict__[key]
        return json.dumps(payload, ensure_ascii=False, default=str)


def _format_timestamp(created: float) -> str:
    return datetime.fromtimestamp(created, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def configure_structured_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def set_log_context(
    *,
    request_id: str = "",
    command_id: str = "",
    run_id: str = "",
    attempt_id: str = "",
    slot_id: str = "",
    correlation_id: str = "",
) -> None:
    if request_id:
        request_id_var.set(request_id)
    if command_id:
        command_id_var.set(command_id)
    if run_id:
        run_id_var.set(run_id)
    if attempt_id:
        attempt_id_var.set(attempt_id)
    if slot_id:
        slot_id_var.set(slot_id)
    if correlation_id:
        correlation_id_var.set(correlation_id)


def clear_log_context() -> None:
    request_id_var.set("")
    command_id_var.set("")
    run_id_var.set("")
    attempt_id_var.set("")
    slot_id_var.set("")
    correlation_id_var.set("")
