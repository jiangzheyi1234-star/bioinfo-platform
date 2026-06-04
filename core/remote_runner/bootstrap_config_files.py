from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BootstrapConfigTempFiles:
    previous_config_path: Path | None
    config_path: Path


def write_bootstrap_config_temp_files(
    *,
    previous_config_payload: dict[str, Any] | None,
    config_payload: dict[str, Any],
) -> BootstrapConfigTempFiles:
    return BootstrapConfigTempFiles(
        previous_config_path=_write_json_temp_file(previous_config_payload)
        if previous_config_payload is not None
        else None,
        config_path=_write_json_temp_file(config_payload),
    )


def cleanup_bootstrap_config_temp_files(temp_files: BootstrapConfigTempFiles) -> None:
    for temp_path in (temp_files.config_path, temp_files.previous_config_path):
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _write_json_temp_file(payload: dict[str, Any]) -> Path:
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        return Path(handle.name)
