from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .artifact_io import artifact_record_exists, artifact_record_stats, iter_artifact_file_payloads
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event, list_evidence_events
from .execution_query_storage import fetch_result, fetch_run_events, fetch_run_results, require_run
from .governance_audit import record_governance_audit_event
from .result_package_storage import record_result_package_export
from .rule_execution_storage import fetch_run_rules
from .storage_core import get_connection, now_iso
from .workflow_revision_storage import fetch_workflow_revision


RESULT_PACKAGE_SCHEMA_VERSION = "h2ometa.result-package.v2"
RESULT_PACKAGE_PROFILE = "h2ometa.result-evidence-package.v1"
RESULT_EXPORT_EVENT_TYPE = "result.export.v1"
RESULT_EXPORT_SCHEMA_NAME = "ResultPackageExportEvent"
RESULT_EXPORTABLE_RUN_STATUSES = {"completed", "failed"}
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


def build_result_artifact_audit(cfg: RemoteRunnerConfig, result_id: str) -> dict[str, Any]:
    result_id = _require_result_id(result_id)
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
    result_id = _require_result_id(result_id)
    result = fetch_result(cfg, result_id)
    _require_canonical_result_id(result_id, result)
    run = require_run(cfg, str(result["runId"]))
    workflow_revision = _require_workflow_revision(cfg, run)
    _require_exportable_run(run)
    result_bundle = fetch_run_results(cfg, str(result["runId"]))
    audit = build_result_artifact_audit(cfg, result_id)
    if audit["status"] != "passed":
        raise ValueError("RESULT_ARTIFACT_AUDIT_FAILED")

    created_at = now_iso()
    safe_run, redacted_paths = _redacted_run(run)
    lineage_edges = list(result_bundle["lineageEdges"])
    run_events = fetch_run_events(cfg, str(result["runId"]))
    rule_bundle = fetch_run_rules(cfg, str(result["runId"]))
    evidence_events = _collect_result_package_evidence(
        cfg,
        run_id=str(result["runId"]),
        lineage_edges=lineage_edges,
    )
    metadata_files = _metadata_payloads(
        run=safe_run,
        workflow_revision=workflow_revision,
        run_events=run_events,
        rule_bundle=rule_bundle,
        lineage_edges=lineage_edges,
        evidence_events=evidence_events,
        audit=audit,
    )
    metadata_index = _metadata_index(metadata_files)
    export_dir = Path(cfg.results_dir) / "packages" / result_id
    export_dir.mkdir(parents=True, exist_ok=True)
    package_path = export_dir / f"{result_id}.zip"
    temp_path = export_dir / f".{package_path.name}.{uuid.uuid4().hex}.tmp"
    manifest = _result_package_manifest(
        result=result,
        run=safe_run,
        workflow_revision=workflow_revision,
        result_bundle=result_bundle,
        audit=audit,
        run_events=run_events,
        rule_bundle=rule_bundle,
        evidence_events=evidence_events,
        metadata_index=metadata_index,
        redacted_secret_paths=redacted_paths,
        created_at=created_at,
    )
    ro_crate_metadata = _ro_crate_metadata(
        manifest=manifest,
        metadata_index=metadata_index,
    )
    try:
        _write_result_package(
            cfg,
            temp_path,
            manifest=manifest,
            ro_crate_metadata=ro_crate_metadata,
            metadata_files=metadata_files,
            artifacts=result["artifacts"],
        )
        temp_path.replace(package_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    size_bytes, sha256 = _file_stats(package_path)
    manifest_sha256 = _json_sha256(manifest)
    evidence = _record_result_export_evidence(
        cfg,
        result_id=result_id,
        run_id=str(result["runId"]),
        workflow_revision_id=str(workflow_revision["workflowRevisionId"]),
        package_path=package_path,
        size_bytes=size_bytes,
        sha256=sha256,
        manifest_sha256=manifest_sha256,
        artifact_count=len(result["artifacts"]),
        created_at=created_at,
    )
    package_uri = package_path.resolve().as_uri()
    try:
        export_record = record_result_package_export(
            cfg,
            result_id=result_id,
            run_id=str(result["runId"]),
            workflow_revision_id=str(workflow_revision["workflowRevisionId"]),
            package_path=package_path,
            package_uri=package_uri,
            size_bytes=size_bytes,
            sha256=sha256,
            manifest_sha256=manifest_sha256,
            evidence_event_id=evidence["eventId"],
            artifact_ids=[str(artifact["artifactId"]) for artifact in result["artifacts"]],
            created_at=created_at,
        )
    except Exception as exc:
        raise RuntimeError(f"RESULT_PACKAGE_EXPORT_RECORD_FAILED: {exc}") from exc
    record_governance_audit_event(
        cfg,
        action="result.export",
        subject_kind="result",
        subject_id=result_id,
        details={
            "runId": str(result["runId"]),
            "workflowRevisionId": str(workflow_revision["workflowRevisionId"]),
            "artifactCount": len(result["artifacts"]),
            "sizeBytes": size_bytes,
            "packageSha256": sha256,
            "manifestSha256": manifest_sha256,
            "evidenceId": evidence["eventId"],
            "packageExportId": export_record["packageExportId"],
        },
    )
    return {
        "resultId": result_id,
        "runId": result["runId"],
        "workflowRevisionId": workflow_revision["workflowRevisionId"],
        "packageExportId": export_record["packageExportId"],
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "packageProfile": RESULT_PACKAGE_PROFILE,
        "packagePath": str(package_path),
        "packageUri": package_uri,
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "manifestSha256": manifest_sha256,
        "evidenceId": evidence["eventId"],
        "createdAt": created_at,
        "manifest": manifest,
    }


def _audit_artifact(cfg: RemoteRunnerConfig, artifact: dict[str, Any]) -> dict[str, Any]:
    expected_size = int(artifact.get("sizeBytes") or 0)
    expected_sha = str(artifact.get("sha256") or "")
    lifecycle_state = str(artifact.get("lifecycleState") or "active")
    if lifecycle_state == "deleted":
        return {
            "artifactId": artifact["artifactId"],
            "path": str(artifact.get("path") or ""),
            "storageBackend": artifact["storageBackend"],
            "storageUri": artifact["storageUri"],
            "exists": False,
            "expectedSizeBytes": expected_size,
            "actualSizeBytes": None,
            "expectedSha256": expected_sha,
            "actualSha256": None,
            "sizeOk": False,
            "checksumOk": False,
            "status": "deleted",
            "deletedAt": artifact.get("deletedAt"),
            "gcReason": str(artifact.get("gcReason") or ""),
        }
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
    run: dict[str, Any],
    workflow_revision: dict[str, Any],
    result_bundle: dict[str, Any],
    audit: dict[str, Any],
    run_events: list[dict[str, Any]],
    rule_bundle: dict[str, Any],
    evidence_events: list[dict[str, Any]],
    metadata_index: list[dict[str, Any]],
    redacted_secret_paths: list[str],
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
                "includedInPackage": True,
            }
        )
    return {
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "packageProfile": RESULT_PACKAGE_PROFILE,
        "resultId": result["resultId"],
        "runId": result["runId"],
        "workflowRevisionId": workflow_revision["workflowRevisionId"],
        "pipelineId": result["pipelineId"],
        "createdAt": created_at,
        "standards": {
            "roCrate": "https://w3id.org/ro/crate/1.1",
            "w3cProv": "https://www.w3.org/TR/prov-o/",
            "workflowRunCrate": "https://w3id.org/ro/wfrun",
        },
        "metadataFiles": metadata_index,
        "run": {
            "runId": run["runId"],
            "projectId": run["projectId"],
            "pipelineId": run["pipelineId"],
            "pipelineVersion": run["pipelineVersion"],
            "runSpecVersion": run["runSpecVersion"],
            "workflowRevisionId": run["workflowRevisionId"],
            "status": run["status"],
            "stage": run["stage"],
            "startedAt": run["startedAt"],
            "finishedAt": run["finishedAt"],
            "submittedAt": run["submittedAt"],
            "trigger": run.get("trigger"),
        },
        "runSpec": run["runSpec"],
        "redactedSecretPaths": redacted_secret_paths,
        "workflowRevision": {
            "workflowRevisionId": workflow_revision["workflowRevisionId"],
            "contentHash": workflow_revision["contentHash"],
            "draftId": workflow_revision["draftId"],
            "draftRevision": workflow_revision["draftRevision"],
            "createdAt": workflow_revision["createdAt"],
            "createdBy": workflow_revision["createdBy"],
        },
        "artifactCount": len(package_artifacts),
        "artifacts": package_artifacts,
        "lineageEdges": result_bundle["lineageEdges"],
        "eventCounts": {
            "runEvents": len(run_events),
            "rules": len(rule_bundle.get("items") or []),
            "ruleEvents": sum(len(rule.get("events") or []) for rule in rule_bundle.get("items") or []),
            "evidenceEvents": len(evidence_events),
        },
        "provenance": {
            "activity": {
                "id": f"run:{result['runId']}",
                "type": "prov:Activity",
                "startedAt": run["startedAt"],
                "endedAt": run["finishedAt"],
                "wasAssociatedWith": "h2ometa.remote_runner",
                "used": [f"workflowRevision:{workflow_revision['workflowRevisionId']}"],
                "generated": [f"artifact:{artifact['artifactId']}" for artifact in result["artifacts"]],
            },
            "agent": {
                "id": "h2ometa.remote_runner",
                "type": "prov:SoftwareAgent",
            },
        },
        "audit": audit,
    }


def _write_result_package(
    cfg: RemoteRunnerConfig,
    package_path: Path,
    *,
    manifest: dict[str, Any],
    ro_crate_metadata: dict[str, Any],
    metadata_files: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_zip_bytes(
            archive,
            "manifest.json",
            _json_bytes(manifest),
        )
        _write_zip_bytes(
            archive,
            "ro-crate-metadata.json",
            _json_bytes(ro_crate_metadata),
        )
        for name, payload in sorted(metadata_files.items()):
            _write_zip_bytes(archive, name, _json_bytes(payload))
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


def _require_workflow_revision(cfg: RemoteRunnerConfig, run: dict[str, Any]) -> dict[str, Any]:
    workflow_revision_id = str(run.get("workflowRevisionId") or "").strip()
    if not workflow_revision_id:
        raise ValueError("RESULT_WORKFLOW_REVISION_REQUIRED")
    workflow_revision = fetch_workflow_revision(cfg, workflow_revision_id)
    if workflow_revision is None:
        raise ValueError(f"RESULT_WORKFLOW_REVISION_NOT_FOUND: {workflow_revision_id}")
    return workflow_revision


def _require_result_id(result_id: str) -> str:
    normalized = str(result_id or "").strip()
    if (
        not normalized
        or normalized != str(result_id or "")
        or not normalized.startswith("res_")
        or ".." in normalized
        or "/" in normalized
        or "\\" in normalized
        or any(not (char.isalnum() or char in "_.-") for char in normalized)
    ):
        raise ValueError("RESULT_ID_INVALID")
    return normalized


def _require_canonical_result_id(result_id: str, result: dict[str, Any]) -> None:
    expected = f"res_{result['runId']}"
    if result_id != expected:
        raise ValueError("RESULT_ID_INVALID")


def _require_exportable_run(run: dict[str, Any]) -> None:
    status = str(run.get("status") or "").strip()
    if status not in RESULT_EXPORTABLE_RUN_STATUSES:
        raise ValueError(f"RESULT_RUN_NOT_TERMINAL: {status or 'unknown'}")


def _metadata_payloads(
    *,
    run: dict[str, Any],
    workflow_revision: dict[str, Any],
    run_events: list[dict[str, Any]],
    rule_bundle: dict[str, Any],
    lineage_edges: list[dict[str, Any]],
    evidence_events: list[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "metadata/run.json": run,
        "metadata/workflow-revision.json": workflow_revision,
        "metadata/run-events.json": {"runId": run["runId"], "items": run_events},
        "metadata/rules.json": rule_bundle,
        "metadata/lineage.json": {"runId": run["runId"], "items": lineage_edges},
        "metadata/evidence-events.json": {"items": evidence_events},
        "metadata/artifact-audit.json": audit,
    }


def _metadata_index(metadata_files: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for path, payload in sorted(metadata_files.items()):
        raw = _json_bytes(payload)
        items.append(
            {
                "path": path,
                "mimeType": "application/json",
                "sizeBytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return items


def _collect_result_package_evidence(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    lineage_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    _extend_unique_events(
        events,
        seen,
        list_evidence_events(cfg, subject_kind="run", subject_id=run_id, limit=500),
    )
    artifact_blob_ids = sorted(
        {
            str(edge.get("objectId") or "")
            for edge in lineage_edges
            if str(edge.get("objectKind") or "") == "artifact_blob" and str(edge.get("objectId") or "")
        }
    )
    for artifact_blob_id in artifact_blob_ids:
        _extend_unique_events(
            events,
            seen,
            list_evidence_events(
                cfg,
                subject_kind="artifact_blob",
                subject_id=artifact_blob_id,
                limit=500,
            ),
        )
    return sorted(events, key=lambda item: (int(item.get("seq") or 0), str(item.get("eventId") or "")))


def _extend_unique_events(
    target: list[dict[str, Any]],
    seen: set[str],
    events: list[dict[str, Any]],
) -> None:
    for event in events:
        event_id = str(event.get("eventId") or "")
        if event_id and event_id not in seen:
            target.append(event)
            seen.add(event_id)


def _ro_crate_metadata(
    *,
    manifest: dict[str, Any],
    metadata_index: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_parts = [
        {"@id": f"{artifact['packagePath']}/"}
        for artifact in manifest["artifacts"]
    ]
    metadata_parts = [{"@id": "manifest.json"}, *[{"@id": item["path"]} for item in metadata_index]]
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": f"H2OMeta result package {manifest['resultId']}",
            "datePublished": manifest["createdAt"],
            "identifier": manifest["resultId"],
            "hasPart": [*metadata_parts, *artifact_parts],
            "mentions": [{"@id": f"#run-{manifest['runId']}"}],
        },
        {
            "@id": f"#run-{manifest['runId']}",
            "@type": "CreateAction",
            "name": f"H2OMeta workflow run {manifest['runId']}",
            "startTime": manifest["run"]["startedAt"],
            "endTime": manifest["run"]["finishedAt"],
            "instrument": {"@id": f"#workflow-{manifest['workflowRevisionId']}"},
            "result": artifact_parts,
        },
        {
            "@id": f"#workflow-{manifest['workflowRevisionId']}",
            "@type": "SoftwareSourceCode",
            "name": f"H2OMeta WorkflowRevision {manifest['workflowRevisionId']}",
            "identifier": manifest["workflowRevisionId"],
            "sha256": manifest["workflowRevision"]["contentHash"],
        },
        {
            "@id": "manifest.json",
            "@type": "File",
            "encodingFormat": "application/json",
            "about": {"@id": "./"},
        },
    ]
    for item in metadata_index:
        graph.append(
            {
                "@id": item["path"],
                "@type": "File",
                "encodingFormat": item["mimeType"],
                "contentSize": item["sizeBytes"],
                "sha256": item["sha256"],
                "about": {"@id": f"#run-{manifest['runId']}"},
            }
        )
    for artifact in manifest["artifacts"]:
        graph.append(
            {
                "@id": f"{artifact['packagePath']}/",
                "@type": "Dataset",
                "name": artifact["kind"],
                "encodingFormat": artifact["mimeType"],
                "contentSize": artifact["sizeBytes"],
                "sha256": artifact["sha256"],
                "identifier": artifact["artifactId"],
                "about": {"@id": f"#run-{manifest['runId']}"},
            }
        )
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": graph,
    }


def _record_result_export_evidence(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    run_id: str,
    workflow_revision_id: str,
    package_path: Path,
    size_bytes: int,
    sha256: str,
    manifest_sha256: str,
    artifact_count: int,
    created_at: str,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "packageProfile": RESULT_PACKAGE_PROFILE,
        "resultId": result_id,
        "runId": run_id,
        "workflowRevisionId": workflow_revision_id,
        "packagePath": str(package_path),
        "packageUri": package_path.resolve().as_uri(),
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "manifestSha256": manifest_sha256,
        "artifactCount": artifact_count,
        "createdAt": created_at,
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=RESULT_EXPORT_EVENT_TYPE,
            schema_name=RESULT_EXPORT_SCHEMA_NAME,
            subject_kind="result",
            subject_id=result_id,
            payload=payload,
            producer="artifact_product_service",
            occurred_at=created_at,
        )
        connection.commit()
    return event


def _redacted_run(run: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    redacted_paths: list[str] = []
    safe_run = _redact_sensitive(run, path="", redacted_paths=redacted_paths)
    if not isinstance(safe_run, dict):
        raise ValueError("RESULT_RUN_METADATA_INVALID")
    return safe_run, redacted_paths


def _redact_sensitive(value: Any, *, path: str, redacted_paths: list[str]) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if _is_sensitive_key(str(key)):
                redacted[key] = "<redacted>"
                redacted_paths.append(child_path)
            else:
                redacted[key] = _redact_sensitive(item, path=child_path, redacted_paths=redacted_paths)
        return redacted
    if isinstance(value, list):
        return [
            _redact_sensitive(item, path=f"{path}[{index}]", redacted_paths=redacted_paths)
            for index, item in enumerate(value)
        ]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = str(key or "").lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _json_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _json_bytes(value: Any, *, indent: int | None = 2) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent).encode("utf-8")
