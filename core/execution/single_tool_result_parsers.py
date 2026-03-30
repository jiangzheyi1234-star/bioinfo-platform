"""Parsers for standard single-tool result views."""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any


def parse_fastp_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"fastp result payload must be a dict: {path}")
    return payload


def parse_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
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


def parse_key_value_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
        elif "\t" in line:
            key, value = line.split("\t", 1)
        else:
            continue
        normalized_key = str(key or "").strip().replace(" ", "_")
        normalized_value = str(value or "").strip()
        if normalized_key:
            values[normalized_key] = normalized_value
    return values


def parse_busco_summary_text(text: str) -> dict[str, str]:
    cleaned = " ".join(str(text or "").split())
    if "C:" not in cleaned or "S:" not in cleaned or "D:" not in cleaned:
        return {}
    pattern = re.compile(
        r"C:(?P<Complete>[\d.]+)%"
        r".*?S:(?P<Single>[\d.]+)%"
        r".*?D:(?P<Duplicated>[\d.]+)%"
        r".*?F:(?P<Fragmented>[\d.]+)%"
        r".*?M:(?P<Missing>[\d.]+)%"
        r".*?n:(?P<Total>\d+)"
    )
    match = pattern.search(cleaned)
    if not match:
        return {}
    return {key: str(value) for key, value in match.groupdict().items()}


def parse_gff_rows(text: str, limit: int = 200) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    columns = [
        {"key": "seqid", "label": "seqid"},
        {"key": "type", "label": "type"},
        {"key": "start", "label": "start"},
        {"key": "end", "label": "end"},
        {"key": "strand", "label": "strand"},
        {"key": "attributes", "label": "attributes"},
    ]
    rows: list[dict[str, str]] = []
    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 9:
            continue
        rows.append(
            {
                "seqid": parts[0],
                "type": parts[2],
                "start": parts[3],
                "end": parts[4],
                "strand": parts[6],
                "attributes": parts[8],
            }
        )
        if len(rows) >= limit:
            break
    return columns, rows


def build_metric_rows(values: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    columns = [
        {"key": "metric", "label": "指标"},
        {"key": "value", "label": "值"},
    ]
    rows = [{"metric": str(key), "value": str(value)} for key, value in values.items()]
    return columns, rows


def summarize_table_row(
    row: dict[str, Any],
    metric_candidates: list[tuple[str, str, str]],
) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    lowered = {str(key).lower(): value for key, value in row.items()}
    for label, key, tone in metric_candidates:
        if key.lower() not in lowered:
            continue
        value = lowered[key.lower()]
        summary.append({"label": label, "value": str(value), "tone": tone})
    return summary


def _strip_comment_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if str(line).strip() and not str(line).lstrip().startswith("#"))


def parse_delimited_rows(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    cleaned = _strip_comment_lines(text)
    if not cleaned.strip():
        return [], []
    try:
        dialect = csv.Sniffer().sniff(cleaned[:4096], delimiters=",\t;")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in cleaned else ","

    reader = csv.DictReader(io.StringIO(cleaned), delimiter=delimiter)
    if not reader.fieldnames:
        return [], []

    columns = [{"key": str(name), "label": str(name)} for name in reader.fieldnames if name is not None]
    rows: list[dict[str, str]] = []
    for row in reader:
        if row is None:
            continue
        normalized = {str(key): str(value or "").strip() for key, value in row.items() if key is not None}
        if any(value for value in normalized.values()):
            rows.append(normalized)
    return columns, rows


def parse_generic_result_table(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="ignore")

    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, list) and payload and all(isinstance(item, dict) for item in payload):
            columns = [{"key": str(key), "label": str(key)} for key in payload[0].keys()]
            return {"columns": columns, "rows": [{str(k): v for k, v in item.items()} for item in payload]}
        if isinstance(payload, dict):
            columns = [{"key": str(key), "label": str(key)} for key in payload.keys()]
            return {"columns": columns, "rows": [{str(key): value for key, value in payload.items()}]}
        raise ValueError(f"Unsupported JSON table payload: {path}")

    if suffix in {".tsv", ".csv"}:
        columns, rows = parse_delimited_rows(text)
        return {"columns": columns, "rows": rows}

    if suffix == ".gff":
        columns, rows = parse_gff_rows(text)
        return {"columns": columns, "rows": rows}

    busco = parse_busco_summary_text(text)
    if busco:
        columns, rows = build_metric_rows(busco)
        return {"columns": columns, "rows": rows, "metrics": busco}

    columns, rows = parse_delimited_rows(text)
    if columns and rows:
        return {"columns": columns, "rows": rows}

    key_values = parse_key_value_text(text)
    if key_values:
        columns, rows = build_metric_rows(key_values)
        return {"columns": columns, "rows": rows, "metrics": key_values}

    raise ValueError(f"Unsupported result table format: {path}")
