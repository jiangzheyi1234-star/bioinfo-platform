from __future__ import annotations

import hashlib
import json
from typing import Any


_SENSITIVE_KEY_PARTS = (
    "access_key",
    "accesskey",
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "private",
    "secret",
    "token",
)


def redacted_run(run: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    redacted_paths: list[str] = []
    safe_run = redact_sensitive(run, path="", redacted_paths=redacted_paths)
    if not isinstance(safe_run, dict):
        raise ValueError("RESULT_RUN_METADATA_INVALID")
    return safe_run, redacted_paths


def redact_sensitive(value: Any, *, path: str, redacted_paths: list[str]) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if _is_sensitive_key(str(key)):
                redacted[key] = "<redacted>"
                redacted_paths.append(child_path)
            else:
                redacted[key] = redact_sensitive(item, path=child_path, redacted_paths=redacted_paths)
        return redacted
    if isinstance(value, list):
        return [
            redact_sensitive(item, path=f"{path}[{index}]", redacted_paths=redacted_paths)
            for index, item in enumerate(value)
        ]
    return value


def json_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def json_bytes(value: Any, *, indent: int | None = 2) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent).encode("utf-8")


def _is_sensitive_key(key: str) -> bool:
    normalized = str(key or "").lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
