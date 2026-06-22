from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from snakemake_interface_logger_plugins.base import LogHandlerBase
    from snakemake_interface_logger_plugins.settings import LogHandlerSettingsBase
except ModuleNotFoundError:

    class LogHandlerSettingsBase:
        pass

    class LogHandlerBase(logging.Handler):
        def __post_init__(self) -> None:
            return None


SCHEMA_VERSION = "h2ometa.snakemake.event.v1"


@dataclass
class LogHandlerSettings(LogHandlerSettingsBase):
    event_path: str = field(
        default="",
        metadata={
            "help": "Path to the H2OMeta Snakemake JSONL event file.",
            "required": True,
        },
    )


class LogHandler(LogHandlerBase):
    def __post_init__(self) -> None:
        parent_post_init = getattr(super(), "__post_init__", None)
        if callable(parent_post_init):
            parent_post_init()
        settings = getattr(self, "settings", None)
        raw_path = str(getattr(settings, "event_path", "") or "").strip()
        if not raw_path:
            raise ValueError("H2OMETA_SNAKEMAKE_EVENT_PATH_REQUIRED")
        self._event_path = Path(raw_path)
        self._event_path.parent.mkdir(parents=True, exist_ok=True)
        self.baseFilename = str(self._event_path)

    @property
    def writes_to_stream(self) -> bool:
        return False

    @property
    def writes_to_file(self) -> bool:
        return True

    @property
    def has_filter(self) -> bool:
        return False

    @property
    def has_formatter(self) -> bool:
        return True

    @property
    def needs_rulegraph(self) -> bool:
        return False

    def emit(self, record: logging.LogRecord) -> None:
        payload = _event_payload(record)
        with self._event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
            handle.write("\n")


def _event_payload(record: logging.LogRecord) -> dict[str, Any]:
    raw_event = getattr(record, "event", "")
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "event": _event_name(raw_event),
        "level": str(getattr(record, "levelname", "") or ""),
        "message": str(record.getMessage() if hasattr(record, "getMessage") else ""),
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    for source, target in (
        ("jobid", "jobId"),
        ("job_id", "jobId"),
        ("job_ids", "jobIds"),
        ("rule_name", "ruleName"),
        ("name", "ruleName"),
        ("rule", "ruleName"),
        ("input", "input"),
        ("output", "output"),
        ("log", "log"),
        ("wildcards", "wildcards"),
        ("shellcmd", "shellcmd"),
        ("resources", "resources"),
        ("reason", "reason"),
        ("done", "done"),
        ("total", "total"),
        ("exception", "exception"),
        ("location", "location"),
        ("traceback", "traceback"),
        ("file", "file"),
        ("line", "line"),
    ):
        if hasattr(record, source):
            payload[target] = _jsonable(getattr(record, source))
    return payload


def _event_name(value: Any) -> str:
    if hasattr(value, "name"):
        return str(getattr(value, "name") or "")
    if hasattr(value, "value"):
        return str(getattr(value, "value") or "")
    return str(value or "")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | set):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return str(value)
