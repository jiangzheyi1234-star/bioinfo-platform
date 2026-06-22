from __future__ import annotations

from typing import Any

from .artifact_io import read_artifact_preview_text
from .config import RemoteRunnerConfig
from .errors import RemoteRunnerNotFoundError
from .storage import fetch_result

MAX_PREVIEW_BYTES = 256 * 1024
MAX_PREVIEW_TABLE_ROWS = 200


def build_result_preview_data(
    cfg: RemoteRunnerConfig,
    result_id: str,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    result = fetch_result(cfg, result_id)
    artifact = _select_preview_artifact(result["artifacts"], artifact_id)
    preview = _build_artifact_preview(artifact)
    return {
        "resultId": result_id,
        "artifactId": artifact["artifactId"],
        "artifact": artifact,
        "preview": preview,
    }


def _select_preview_artifact(artifacts: list[dict[str, Any]], artifact_id: str | None) -> dict[str, Any]:
    if artifact_id:
        selected = next((item for item in artifacts if item["artifactId"] == artifact_id), None)
    else:
        selected = artifacts[0] if artifacts else None
    if selected is None:
        raise RemoteRunnerNotFoundError("RESULT_NOT_FOUND")
    return selected


def _build_artifact_preview(artifact: dict[str, Any]) -> dict[str, Any]:
    mime_type = artifact["mimeType"]
    if mime_type == "text/tab-separated-values":
        raw, truncated = _read_preview_text(artifact)
        rows = raw.splitlines()
        columns = rows[0].split("\t") if rows else []
        preview_rows = [row.split("\t") for row in rows[1 : 1 + MAX_PREVIEW_TABLE_ROWS]]
        return {
            "kind": "table",
            "columns": columns,
            "rows": preview_rows,
            "truncated": truncated or max(0, len(rows) - 1) > MAX_PREVIEW_TABLE_ROWS,
        }
    if mime_type.startswith("text/html"):
        content, truncated = _read_preview_text(artifact)
        return {"kind": "html", "content": content, "truncated": truncated}
    content, truncated = _read_preview_text(artifact)
    return {"kind": "text", "content": content, "truncated": truncated}


def _read_preview_text(artifact: dict[str, Any], *, limit: int = MAX_PREVIEW_BYTES) -> tuple[str, bool]:
    return read_artifact_preview_text(artifact, limit=limit)
