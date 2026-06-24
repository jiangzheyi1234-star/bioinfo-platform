from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_io import restore_artifact_payload
from .config import RemoteRunnerConfig
from .storage import fetch_upload
from .storage_core import get_connection


def _build_run_outputs(execution: dict, result_dir: Path) -> dict[str, str]:
    configured = execution.get("outputs") if isinstance(execution, dict) else None
    if not isinstance(configured, dict) or not configured:
        raise ValueError("EXECUTION_OUTPUTS_REQUIRED")
    outputs: dict[str, str] = {}
    for key, value in configured.items():
        name = str(key or "").strip()
        relative = str(value or "").strip()
        if not name or not relative:
            continue
        candidate = (result_dir / relative).resolve()
        if result_dir.resolve() not in [candidate, *candidate.parents]:
            raise ValueError("OUTPUT_PATH_OUTSIDE_RESULT_DIR")
        outputs[name] = str(candidate)
    if not outputs:
        raise ValueError("OUTPUTS_REQUIRED")
    return outputs


def _resolve_run_inputs(
    cfg: RemoteRunnerConfig,
    run_spec: dict,
    *,
    input_work_dir: Path | None = None,
) -> list[dict]:
    raw_inputs = run_spec.get("inputs") or []
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("INPUT_REQUIRED")
    resolved: list[dict] = []
    for index, item in enumerate(raw_inputs):
        if not isinstance(item, dict):
            raise ValueError("INPUT_INVALID")
        resolved.append(_resolve_run_input(cfg, item, index=index, input_work_dir=input_work_dir))
    return resolved


def _resolve_run_input(
    cfg: RemoteRunnerConfig,
    item: dict[str, Any],
    *,
    index: int,
    input_work_dir: Path | None,
) -> dict[str, Any]:
    upload_id = _optional_text(item.get("uploadId"))
    artifact_id = _optional_text(item.get("artifactId"))
    artifact_blob_id = _optional_text(item.get("artifactBlobId"))
    materialization_id = _optional_text(item.get("materializationId"))
    if upload_id and (artifact_id or artifact_blob_id or materialization_id):
        raise ValueError("INPUT_SOURCE_AMBIGUOUS")
    if upload_id:
        return _resolve_upload_input(cfg, item, index=index, upload_id=upload_id)
    if artifact_id:
        if artifact_blob_id or materialization_id:
            raise ValueError("INPUT_SOURCE_AMBIGUOUS")
        return _resolve_artifact_id_input(
            cfg,
            item,
            index=index,
            artifact_id=artifact_id,
            input_work_dir=input_work_dir,
        )
    if artifact_blob_id or materialization_id:
        if not artifact_blob_id or not materialization_id:
            raise ValueError("INPUT_ARTIFACT_MATERIALIZATION_REQUIRED")
        return _resolve_artifact_materialization_input(
            cfg,
            item,
            index=index,
            artifact_blob_id=artifact_blob_id,
            materialization_id=materialization_id,
            input_work_dir=input_work_dir,
        )
    raise ValueError("INPUT_SOURCE_REQUIRED")


def _resolve_upload_input(
    cfg: RemoteRunnerConfig,
    item: dict[str, Any],
    *,
    index: int,
    upload_id: str,
) -> dict[str, Any]:
    upload = fetch_upload(cfg, upload_id)
    if upload is None:
        raise ValueError("INPUT_NOT_FOUND")
    path = Path(str(upload["path"]))
    if not path.exists():
        raise ValueError("INPUT_FILE_MISSING")
    return {
        "sourceType": "upload",
        "sourceId": upload["uploadId"],
        "uploadId": upload["uploadId"],
        "name": str(item.get("name") or "").strip(),
        "filename": str(item.get("filename") or upload["filename"]),
        "role": str(item.get("role") or "input"),
        "path": str(path),
        "sizeBytes": upload["sizeBytes"],
        "sha256": upload["sha256"],
        "mimeType": upload["mimeType"],
        "index": index,
    }


def _resolve_artifact_id_input(
    cfg: RemoteRunnerConfig,
    item: dict[str, Any],
    *,
    index: int,
    artifact_id: str,
    input_work_dir: Path | None,
) -> dict[str, Any]:
    restore_dir = _require_input_work_dir(input_work_dir)
    with get_connection(cfg) as connection:
        artifact = connection.execute(
            "SELECT * FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if artifact is None:
            raise ValueError("INPUT_ARTIFACT_NOT_FOUND")
        if str(artifact["lifecycle_state"] or "") != "active":
            raise ValueError("INPUT_ARTIFACT_NOT_ACTIVE")
        blob = connection.execute(
            """
            SELECT * FROM artifact_blobs
            WHERE sha256 = ? AND size_bytes = ?
            """,
            (artifact["sha256"], int(artifact["size_bytes"])),
        ).fetchone()
        if blob is None:
            raise ValueError("INPUT_ARTIFACT_LEDGER_MISSING")
        materialization = connection.execute(
            """
            SELECT * FROM artifact_materializations
            WHERE artifact_blob_id = ? AND storage_backend = ? AND storage_uri = ?
            """,
            (blob["artifact_blob_id"], artifact["storage_backend"], artifact["storage_uri"]),
        ).fetchone()
        if materialization is None:
            raise ValueError("INPUT_ARTIFACT_MATERIALIZATION_NOT_FOUND")
    upstream_run_id = _optional_text(item.get("upstreamRunId")) or str(artifact["run_id"])
    if upstream_run_id != str(artifact["run_id"]):
        raise ValueError("INPUT_ARTIFACT_UPSTREAM_RUN_MISMATCH")
    restored = restore_artifact_payload(
        cfg,
        _artifact_row_record(artifact),
        _input_restore_destination(
            restore_dir,
            index=index,
            filename=str(item.get("filename") or Path(str(artifact["path"])).name),
        ),
    )
    return _resolved_artifact_input(
        item,
        index=index,
        artifact_id=artifact_id,
        artifact_blob_id=str(blob["artifact_blob_id"]),
        source_materialization=_row_to_dict(materialization),
        restored=restored,
        upstream_run_id=upstream_run_id,
        filename_default=Path(str(artifact["path"])).name,
        mime_type=str(artifact["mime_type"]),
        size_bytes=int(artifact["size_bytes"]),
        sha256=str(artifact["sha256"]),
    )


def _resolve_artifact_materialization_input(
    cfg: RemoteRunnerConfig,
    item: dict[str, Any],
    *,
    index: int,
    artifact_blob_id: str,
    materialization_id: str,
    input_work_dir: Path | None,
) -> dict[str, Any]:
    restore_dir = _require_input_work_dir(input_work_dir)
    with get_connection(cfg) as connection:
        blob = connection.execute(
            "SELECT * FROM artifact_blobs WHERE artifact_blob_id = ?",
            (artifact_blob_id,),
        ).fetchone()
        if blob is None:
            raise ValueError("INPUT_ARTIFACT_BLOB_NOT_FOUND")
        materialization = connection.execute(
            "SELECT * FROM artifact_materializations WHERE materialization_id = ?",
            (materialization_id,),
        ).fetchone()
        if materialization is None:
            raise ValueError("INPUT_ARTIFACT_MATERIALIZATION_NOT_FOUND")
        if materialization["artifact_blob_id"] != artifact_blob_id:
            raise ValueError("INPUT_ARTIFACT_MATERIALIZATION_BLOB_MISMATCH")
    materialization_dict = _row_to_dict(materialization)
    if str(materialization_dict.get("lifecycle_state") or "") != "active":
        raise ValueError("INPUT_ARTIFACT_MATERIALIZATION_NOT_ACTIVE")
    filename_default = _materialization_filename(materialization_dict, fallback=artifact_blob_id)
    restored = restore_artifact_payload(
        cfg,
        _blob_materialization_record(blob, materialization),
        _input_restore_destination(
            restore_dir,
            index=index,
            filename=str(item.get("filename") or filename_default),
        ),
    )
    return _resolved_artifact_input(
        item,
        index=index,
        artifact_id=_optional_text(item.get("sourceArtifactId")),
        artifact_blob_id=artifact_blob_id,
        source_materialization=materialization_dict,
        restored=restored,
        upstream_run_id=_optional_text(item.get("upstreamRunId")),
        filename_default=filename_default,
        mime_type=str(blob["media_type"]),
        size_bytes=int(blob["size_bytes"]),
        sha256=str(blob["sha256"]),
    )


def _resolved_artifact_input(
    item: dict[str, Any],
    *,
    index: int,
    artifact_id: str | None,
    artifact_blob_id: str,
    source_materialization: dict[str, Any],
    restored: dict[str, Any],
    upstream_run_id: str | None,
    filename_default: str,
    mime_type: str,
    size_bytes: int,
    sha256: str,
) -> dict[str, Any]:
    if int(restored["sizeBytes"]) != size_bytes or str(restored["sha256"]) != sha256:
        raise ValueError(f"INPUT_ARTIFACT_DIGEST_MISMATCH: {artifact_blob_id}")
    return {
        "sourceType": "artifact",
        "sourceId": artifact_id or artifact_blob_id,
        **({"artifactId": artifact_id} if artifact_id else {}),
        "artifactBlobId": artifact_blob_id,
        "sourceMaterializationId": source_materialization["materialization_id"],
        "sourceStorageBackend": source_materialization["storage_backend"],
        "inputStorageBackend": restored["storageBackend"],
        "inputStorageUri": restored["storageUri"],
        **({"upstreamRunId": upstream_run_id} if upstream_run_id else {}),
        "name": str(item.get("name") or "").strip(),
        "filename": str(item.get("filename") or filename_default or artifact_blob_id),
        "role": str(item.get("role") or "input"),
        "path": str(restored["path"]),
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "mimeType": mime_type,
        "index": index,
    }


def _artifact_row_record(row: Any) -> dict[str, Any]:
    return {
        "artifactId": row["artifact_id"],
        "path": row["path"],
        "storageBackend": row["storage_backend"],
        "storageUri": row["storage_uri"],
        "sizeBytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
        "mimeType": row["mime_type"],
    }


def _blob_materialization_record(blob: Any, materialization: Any) -> dict[str, Any]:
    return {
        "artifactBlobId": blob["artifact_blob_id"],
        "path": materialization["local_path"] or materialization["storage_uri"],
        "storageBackend": materialization["storage_backend"],
        "storageUri": materialization["storage_uri"],
        "localPath": materialization["local_path"],
        "sizeBytes": int(blob["size_bytes"]),
        "sha256": blob["sha256"],
        "mimeType": blob["media_type"],
    }


def _require_input_work_dir(input_work_dir: Path | None) -> Path:
    if input_work_dir is None:
        raise ValueError("INPUT_ARTIFACT_RESTORE_DIR_REQUIRED")
    path = Path(input_work_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _input_restore_destination(input_work_dir: Path, *, index: int, filename: str) -> Path:
    safe_name = _safe_filename(filename) or "artifact-input"
    return input_work_dir / f"{index + 1:03d}-{safe_name}"


def _safe_filename(value: str) -> str:
    name = Path(str(value or "").strip()).name
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in name).strip("._-")


def _materialization_filename(materialization: dict[str, Any], *, fallback: str) -> str:
    local_path = _optional_text(materialization.get("local_path"))
    if local_path:
        return Path(local_path).name
    storage_uri = _optional_text(materialization.get("storage_uri"))
    if storage_uri:
        return Path(storage_uri.rstrip("/")).name
    return fallback


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
