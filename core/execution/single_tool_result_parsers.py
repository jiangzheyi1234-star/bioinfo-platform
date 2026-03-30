"""Parsers for standard single-tool result views."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_fastp_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fastp result payload must be a dict: {path}")
    return payload


def parse_prokka_stats_text(text: str) -> dict[str, str]:
    stats: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if ":" in line:
            key, value = line.split(":", 1)
        elif "\t" in line:
            key, value = line.split("\t", 1)
        else:
            continue
        normalized_key = str(key or "").strip().lower().replace(" ", "_")
        normalized_value = str(value or "").strip()
        if normalized_key:
            stats[normalized_key] = normalized_value
    return stats
