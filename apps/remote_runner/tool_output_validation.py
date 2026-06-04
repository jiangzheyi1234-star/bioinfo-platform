from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any


def _validate_outputs(*, output_schema: dict[str, Any], outputs: dict[str, str]) -> dict[str, str] | None:
    artifacts = output_schema.get("artifacts") if isinstance(output_schema, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        return {"code": "OUTPUT_ARTIFACTS_REQUIRED", "message": "Output artifacts are not declared."}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return {"code": "OUTPUT_ARTIFACT_INVALID", "message": "Output artifact metadata is invalid."}
        key = str(artifact.get("key") or "").strip()
        path = Path(str(outputs.get(key) or ""))
        if not key or key not in outputs:
            return {"code": "OUTPUT_ARTIFACT_KEY_UNKNOWN", "message": f"Output artifact key is unknown: {key}"}
        directory = bool(artifact.get("directory")) or str(artifact.get("mimeType") or "") == "inode/directory"
        if directory:
            if not path.is_dir():
                return {"code": "OUTPUT_ARTIFACT_MISSING", "message": f"Output directory is missing: {key}"}
            if not any(path.iterdir()):
                return {"code": "OUTPUT_ARTIFACT_EMPTY", "message": f"Output directory is empty: {key}"}
            continue
        if not path.is_file():
            return {"code": "OUTPUT_ARTIFACT_MISSING", "message": f"Output file is missing: {key}"}
        if path.stat().st_size <= 0:
            return {"code": "OUTPUT_ARTIFACT_EMPTY", "message": f"Output file is empty: {key}"}
        if _blank_text_output(path, str(artifact.get("mimeType") or "")):
            return {"code": "OUTPUT_ARTIFACT_EMPTY", "message": f"Output file is blank: {key}"}
        parse_error = _parseable_output_error(path, str(artifact.get("mimeType") or ""))
        if parse_error:
            return {"code": "OUTPUT_ARTIFACT_FORMAT_INVALID", "message": f"{key}: {parse_error}"}
    return None


def _blank_text_output(path: Path, mime_type: str) -> bool:
    lowered = mime_type.lower()
    suffix = path.suffix.lower()
    if not (
        lowered.startswith("text/")
        or lowered == "application/json"
        or suffix in {".json", ".csv", ".tsv", ".txt", ".log", ".md", ".html", ".xml"}
    ):
        return False
    try:
        return not path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return False


def _parseable_output_error(path: Path, mime_type: str) -> str:
    lowered = mime_type.lower()
    if lowered == "application/json" or path.suffix.lower() == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return str(exc)
    if lowered == "text/tab-separated-values" or path.suffix.lower() == ".tsv":
        try:
            path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            return str(exc)
    if lowered in {"application/xml", "text/xml"} or lowered.endswith("+xml") or path.suffix.lower() == ".xml":
        try:
            ElementTree.parse(path)
        except ElementTree.ParseError as exc:
            return str(exc)
    if lowered.startswith("text/"):
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return str(exc)
    return ""


def _validated_output_summary(output_schema: dict[str, Any]) -> dict[str, str]:
    artifacts = output_schema.get("artifacts") if isinstance(output_schema, dict) else []
    names = [str(item.get("key") or "").strip() for item in artifacts if isinstance(item, dict)]
    names = [name for name in names if name]
    return {"artifactCount": str(len(names)), "artifactNames": ",".join(names)}
