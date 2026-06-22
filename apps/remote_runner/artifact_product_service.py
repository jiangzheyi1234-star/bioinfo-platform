from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .artifact_io import artifact_record_exists, artifact_record_stats, iter_artifact_file_payloads
from .config import RemoteRunnerConfig
from .execution_query_storage import fetch_result, fetch_run_results
from .governance_audit import record_governance_audit_event
from .storage_core import now_iso


RESULT_PACKAGE_SCHEMA_VERSION = "h2ometa.result-package.v1"


def build_result_artifact_audit(cfg: RemoteRunnerConfig, result_id: str) -> dict[str, Any]:
    result = fetch_result(cfg, result_id)
    checked_at = now_iso()
    audited = [_audit_artifact(cfg, artifact) for artifact in result["artifacts"]]
    failed = [item for item in audited if item["status"] != "passed"]
    return {
        "resultId": result_id,
        "runId": result["runId"],
        "status": "failed" if failed else "passed",
        "checkedAt": checked_at,
        "artifactCount": len(audited),
        "failedCount": len(failed),
        "artifacts": audited,
    }


def export_result_package(cfg: RemoteRunnerConfig, result_id: str) -> dict[str, Any]:
    result = fetch_result(cfg, result_id)
    result_bundle = fetch_run_results(cfg, str(result["runId"]))
    audit = build_result_artifact_audit(cfg, result_id)
    if audit["status"] != "passed":
        raise ValueError("RESULT_ARTIFACT_AUDIT_FAILED")

    created_at = now_iso()
    export_dir = Path(cfg.results_dir) / "packages" / result_id
    export_dir.mkdir(parents=True, exist_ok=True)
    package_path = export_dir / f"{result_id}.zip"
    temp_path = export_dir / f".{package_path.name}.{uuid.uuid4().hex}.tmp"
    manifest = _result_package_manifest(
        result=result,
        result_bundle=result_bundle,
        audit=audit,
        created_at=created_at,
    )
    try:
        _write_result_package(
            cfg,
            temp_path,
            manifest=manifest,
            artifacts=result["artifacts"],
        )
        temp_path.replace(package_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    size_bytes, sha256 = _file_stats(package_path)
    record_governance_audit_event(
        cfg,
        action="result.export",
        subject_kind="result",
        subject_id=result_id,
        details={
            "runId": str(result["runId"]),
            "artifactCount": len(result["artifacts"]),
            "sizeBytes": size_bytes,
            "packageSha256": sha256,
        },
    )
    return {
        "resultId": result_id,
        "runId": result["runId"],
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "packagePath": str(package_path),
        "packageUri": package_path.resolve().as_uri(),
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "createdAt": created_at,
        "manifest": manifest,
    }


def _audit_artifact(cfg: RemoteRunnerConfig, artifact: dict[str, Any]) -> dict[str, Any]:
    expected_size = int(artifact.get("sizeBytes") or 0)
    expected_sha = str(artifact.get("sha256") or "")
    exists = False
    actual_size: int | None = None
    actual_sha: str | None = None
    error = ""
    try:
        exists = artifact_record_exists(cfg, artifact)
        actual_size, actual_sha = artifact_record_stats(cfg, artifact)
    except ValueError as exc:
        error = str(exc)
    status = (
        "passed"
        if exists and not error and actual_size == expected_size and actual_sha == expected_sha
        else "failed"
    )
    return {
        "artifactId": artifact["artifactId"],
        "path": str(artifact.get("path") or ""),
        "storageBackend": artifact["storageBackend"],
        "storageUri": artifact["storageUri"],
        "exists": exists,
        "expectedSizeBytes": expected_size,
        "actualSizeBytes": actual_size,
        "expectedSha256": expected_sha,
        "actualSha256": actual_sha,
        "sizeOk": actual_size == expected_size,
        "checksumOk": actual_sha == expected_sha,
        "status": status,
        **({"error": error} if error else {}),
    }


def _result_package_manifest(
    *,
    result: dict[str, Any],
    result_bundle: dict[str, Any],
    audit: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    package_artifacts = []
    for artifact in result["artifacts"]:
        package_artifacts.append(
            {
                "artifactId": artifact["artifactId"],
                "runId": artifact["runId"],
                "kind": artifact["kind"],
                "mimeType": artifact["mimeType"],
                "sizeBytes": artifact["sizeBytes"],
                "sha256": artifact["sha256"],
                "storageBackend": artifact["storageBackend"],
                "storageUri": artifact["storageUri"],
                "packagePath": _package_artifact_root(artifact),
            }
        )
    return {
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "resultId": result["resultId"],
        "runId": result["runId"],
        "pipelineId": result["pipelineId"],
        "createdAt": created_at,
        "artifactCount": len(package_artifacts),
        "artifacts": package_artifacts,
        "lineageEdges": result_bundle["lineageEdges"],
        "audit": audit,
    }


def _write_result_package(
    cfg: RemoteRunnerConfig,
    package_path: Path,
    *,
    manifest: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_zip_bytes(
            archive,
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
        )
        for artifact in artifacts:
            _write_artifact_to_zip(cfg, archive, artifact)


def _write_artifact_to_zip(
    cfg: RemoteRunnerConfig,
    archive: zipfile.ZipFile,
    artifact: dict[str, Any],
) -> None:
    root = _package_artifact_root(artifact)
    for relative_path, payload in iter_artifact_file_payloads(cfg, artifact):
        _write_zip_bytes(archive, f"{root}/{relative_path}", payload)


def _write_zip_bytes(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name)
    info.date_time = (1980, 1, 1, 0, 0, 0)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload)


def _package_artifact_root(artifact: dict[str, Any]) -> str:
    return f"artifacts/{artifact['artifactId']}"


def _file_stats(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), hashlib.sha256(payload).hexdigest()
