from __future__ import annotations

import hashlib
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .artifact_io import (
    assert_managed_artifact_storage,
    iter_artifact_file_payloads,
)
from .artifact_product_audit import audit_artifact
from .artifact_product_payloads import json_bytes, json_sha256, redacted_run
from .artifact_product_lineage import (
    input_artifact_name,
    input_artifact_ro_crate_id,
    input_artifacts_from_lineage,
)
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event, list_evidence_events
from .execution_query_storage import fetch_result, fetch_run_events, fetch_run_results, require_run
from .governance_audit import record_governance_audit_event
from .result_package_validation import (
    PROCESS_RUN_CRATE_PROFILE_URI,
    RO_CRATE_CONTEXT_1_1,
    RO_CRATE_SPEC_URI,
    WORKFLOW_RO_CRATE_PROFILE_URI,
    WORKFLOW_RUN_CONTEXT,
    WORKFLOW_RUN_CRATE_PROFILE_URI,
    validate_result_package_archive,
)
from .result_package_storage import (
    ensure_result_package_export_recordable,
    record_result_package_export_in_connection,
)
from .rule_execution_storage import fetch_run_rules
from .storage_core import get_connection, now_iso
from .workflow_revision_storage import fetch_workflow_revision


RESULT_PACKAGE_SCHEMA_VERSION = "h2ometa.result-package.v2"
RESULT_PACKAGE_PROFILE = "h2ometa.result-evidence-package.v1"
RESULT_EXPORT_EVENT_TYPE = "result.export.v1"
RESULT_EXPORT_SCHEMA_NAME = "ResultPackageExportEvent"
RESULT_EXPORTABLE_RUN_STATUSES = {"completed", "failed"}
ARTIFACT_PAYLOAD_MODE_INCLUDED = "included"
ARTIFACT_PAYLOAD_MODE_METADATA_ONLY = "metadata-only"


def build_result_artifact_audit(
    cfg: RemoteRunnerConfig,
    result_id: str,
    *,
    verify_payload: bool = True,
) -> dict[str, Any]:
    verify_payload = _require_bool(verify_payload, "RESULT_ARTIFACT_AUDIT_VERIFY_PAYLOAD_BOOL_REQUIRED")
    result_id = _require_result_id(result_id)
    result = fetch_result(cfg, result_id)
    checked_at = now_iso()
    audited = [
        audit_artifact(cfg, artifact, verify_payload=verify_payload)
        for artifact in result["artifacts"]
    ]
    failed = [item for item in audited if item["status"] != "passed"]
    return {
        "resultId": result_id,
        "runId": result["runId"],
        "verificationMode": (
            "payload-checksum" if verify_payload else ARTIFACT_PAYLOAD_MODE_METADATA_ONLY
        ),
        "status": "failed" if failed else "passed",
        "checkedAt": checked_at,
        "artifactCount": len(audited),
        "failedCount": len(failed),
        "artifacts": audited,
    }


def export_result_package(
    cfg: RemoteRunnerConfig,
    result_id: str,
    *,
    include_artifacts: bool,
    actor: str | None = None,
) -> dict[str, Any]:
    result_id = _require_result_id(result_id)
    result = fetch_result(cfg, result_id)
    _require_canonical_result_id(result_id, result)
    run = require_run(cfg, str(result["runId"]))
    workflow_revision = _require_workflow_revision(cfg, run)
    _require_exportable_run(run)
    result_bundle = fetch_run_results(cfg, str(result["runId"]))
    payload_mode = _artifact_payload_mode(include_artifacts)
    ensure_result_package_export_recordable(
        cfg,
        result_id=result_id,
        artifact_payload_mode=payload_mode,
    )
    audit = build_result_artifact_audit(
        cfg,
        result_id,
        verify_payload=include_artifacts,
    )
    if audit["status"] != "passed":
        raise ValueError("RESULT_ARTIFACT_AUDIT_FAILED")

    created_at = now_iso()
    safe_run, redacted_paths = redacted_run(run)
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
    package_path = export_dir / _package_filename(result_id, payload_mode)
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
        include_artifacts=include_artifacts,
        artifact_payload_mode=payload_mode,
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
            include_artifacts=include_artifacts,
        )
        manifest_sha256 = json_sha256(manifest)
        validation = validate_result_package_archive(
            temp_path,
            expected_manifest_sha256=manifest_sha256,
            expected_schema_version=RESULT_PACKAGE_SCHEMA_VERSION,
            expected_package_profile=RESULT_PACKAGE_PROFILE,
        )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    size_bytes, sha256 = _file_stats(temp_path)
    package_uri = package_path.resolve().as_uri()
    published = False
    try:
        with get_connection(cfg) as connection:
            connection.execute("BEGIN IMMEDIATE")
            evidence = _append_result_export_evidence(
                connection,
                result_id=result_id,
                run_id=str(result["runId"]),
                workflow_revision_id=str(workflow_revision["workflowRevisionId"]),
                size_bytes=size_bytes,
                sha256=sha256,
                manifest_sha256=manifest_sha256,
                artifact_count=len(result["artifacts"]),
                include_artifacts=include_artifacts,
                artifact_payload_mode=payload_mode,
                created_at=created_at,
                validation=validation,
            )
            export_record = record_result_package_export_in_connection(
                connection,
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
                include_artifacts=include_artifacts,
                artifact_payload_mode=payload_mode,
                created_at=created_at,
            )
            temp_path.replace(package_path)
            published = True
            connection.commit()
    except Exception as exc:
        if published:
            package_path.unlink(missing_ok=True)
        else:
            temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"RESULT_PACKAGE_EXPORT_RECORD_FAILED: {exc}") from exc
    record_governance_audit_event(
        cfg,
        action="result.export",
        subject_kind="result",
        subject_id=result_id,
        actor=str(actor or "remote-runner-api").strip() or "remote-runner-api",
        details={
            "runId": str(result["runId"]),
            "workflowRevisionId": str(workflow_revision["workflowRevisionId"]),
            "includeArtifacts": include_artifacts,
            "artifactPayloadMode": payload_mode,
            "artifactCount": len(result["artifacts"]),
            "sizeBytes": size_bytes,
            "packageSha256": sha256,
            "manifestSha256": manifest_sha256,
            "validationStatus": validation["status"],
            "validationSchemaVersion": validation["schemaVersion"],
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
        "includeArtifacts": include_artifacts,
        "artifactPayloadMode": payload_mode,
        "packagePath": str(package_path),
        "packageUri": package_uri,
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "manifestSha256": manifest_sha256,
        "validation": validation,
        "evidenceId": evidence["eventId"],
        "createdAt": created_at,
        "manifest": manifest,
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
    include_artifacts: bool,
    artifact_payload_mode: str,
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
                "packagePath": _package_artifact_root(artifact) if include_artifacts else None,
                "externalUri": artifact["storageUri"],
                "includedInPackage": include_artifacts,
            }
        )
    input_artifacts = input_artifacts_from_lineage(result_bundle["lineageEdges"])
    return {
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "packageProfile": RESULT_PACKAGE_PROFILE,
        "resultId": result["resultId"],
        "runId": result["runId"],
        "workflowRevisionId": workflow_revision["workflowRevisionId"],
        "pipelineId": result["pipelineId"],
        "createdAt": created_at,
        "includeArtifacts": include_artifacts,
        "artifactPayloadMode": artifact_payload_mode,
        "standards": {
            "roCrate": RO_CRATE_SPEC_URI,
            "w3cProv": "https://www.w3.org/TR/prov-o/",
            "processRunCrate": PROCESS_RUN_CRATE_PROFILE_URI,
            "workflowRunCrate": WORKFLOW_RUN_CRATE_PROFILE_URI,
            "workflowRoCrate": WORKFLOW_RO_CRATE_PROFILE_URI,
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
        "inputArtifactCount": len(input_artifacts),
        "inputArtifacts": input_artifacts,
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
                "used": [
                    f"workflowRevision:{workflow_revision['workflowRevisionId']}",
                    *[f"artifactBlob:{artifact['artifactBlobId']}" for artifact in input_artifacts],
                ],
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
    include_artifacts: bool,
) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write_zip_bytes(
            archive,
            "manifest.json",
            json_bytes(manifest),
        )
        _write_zip_bytes(
            archive,
            "ro-crate-metadata.json",
            json_bytes(ro_crate_metadata),
        )
        for name, payload in sorted(metadata_files.items()):
            _write_zip_bytes(archive, name, json_bytes(payload))
        if include_artifacts:
            for artifact in artifacts:
                _write_artifact_to_zip(cfg, archive, artifact)


def _write_artifact_to_zip(
    cfg: RemoteRunnerConfig,
    archive: zipfile.ZipFile,
    artifact: dict[str, Any],
) -> None:
    assert_managed_artifact_storage(cfg, artifact)
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


def _package_filename(result_id: str, artifact_payload_mode: str) -> str:
    if artifact_payload_mode == ARTIFACT_PAYLOAD_MODE_INCLUDED:
        return f"{result_id}.zip"
    if artifact_payload_mode == ARTIFACT_PAYLOAD_MODE_METADATA_ONLY:
        return f"{result_id}.metadata-only.zip"
    raise ValueError(f"RESULT_PACKAGE_ARTIFACT_PAYLOAD_MODE_UNSUPPORTED: {artifact_payload_mode}")


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


def _artifact_payload_mode(include_artifacts: bool) -> str:
    include_artifacts = _require_bool(
        include_artifacts,
        "RESULT_PACKAGE_INCLUDE_ARTIFACTS_BOOL_REQUIRED",
    )
    return ARTIFACT_PAYLOAD_MODE_INCLUDED if include_artifacts else ARTIFACT_PAYLOAD_MODE_METADATA_ONLY


def _require_bool(value: object, code: str) -> bool:
    if type(value) is not bool:
        raise ValueError(code)
    return value


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
        raw = json_bytes(payload)
        items.append(
            {
                "path": path,
                "mimeType": "application/json",
                "sizeBytes": len(raw),
                "sha256": json_sha256(payload),
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
    artifact_parts = [{"@id": _artifact_ro_crate_id(artifact)} for artifact in manifest["artifacts"]]
    input_parts = [
        {"@id": input_artifact_ro_crate_id(artifact)}
        for artifact in manifest.get("inputArtifacts", [])
        if str(artifact.get("artifactBlobId") or "").strip()
    ]
    metadata_parts = [{"@id": "manifest.json"}, *[{"@id": item["path"]} for item in metadata_index]]
    workflow_id = f"#workflow-{manifest['workflowRevisionId']}"
    run_action_id = f"#run-{manifest['runId']}"
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": [
                {"@id": RO_CRATE_SPEC_URI},
                {"@id": WORKFLOW_RO_CRATE_PROFILE_URI},
            ],
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "conformsTo": [
                {"@id": PROCESS_RUN_CRATE_PROFILE_URI},
                {"@id": WORKFLOW_RUN_CRATE_PROFILE_URI},
                {"@id": WORKFLOW_RO_CRATE_PROFILE_URI},
            ],
            "name": f"H2OMeta result package {manifest['resultId']}",
            "datePublished": manifest["createdAt"],
            "identifier": manifest["resultId"],
            "hasPart": [*metadata_parts, *artifact_parts, *input_parts],
            "mainEntity": {"@id": workflow_id},
            "mentions": [{"@id": run_action_id}],
        },
        {
            "@id": run_action_id,
            "@type": "CreateAction",
            "name": f"H2OMeta workflow run {manifest['runId']}",
            "startTime": manifest["run"]["startedAt"],
            "endTime": manifest["run"]["finishedAt"],
            "instrument": {"@id": workflow_id},
            **({"object": input_parts} if input_parts else {}),
            "result": artifact_parts,
        },
        {
            "@id": workflow_id,
            "@type": ["SoftwareSourceCode", "ComputationalWorkflow"],
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
                "about": {"@id": run_action_id},
            }
        )
    for artifact in manifest["artifacts"]:
        graph.append(
            {
                "@id": _artifact_ro_crate_id(artifact),
                "@type": "Dataset",
                "name": artifact["kind"],
                "encodingFormat": artifact["mimeType"],
                "contentSize": artifact["sizeBytes"],
                "sha256": artifact["sha256"],
                "identifier": artifact["artifactId"],
                "h2ometa:includedInPackage": artifact["includedInPackage"],
                "h2ometa:storageBackend": artifact["storageBackend"],
                "h2ometa:storageUri": artifact["storageUri"],
                "about": {"@id": run_action_id},
            }
        )
    for artifact in manifest.get("inputArtifacts", []):
        if not str(artifact.get("artifactBlobId") or "").strip():
            continue
        graph.append(
            {
                "@id": input_artifact_ro_crate_id(artifact),
                "@type": "Dataset",
                "name": input_artifact_name(artifact),
                "encodingFormat": artifact.get("mimeType") or "application/octet-stream",
                "contentSize": artifact.get("sizeBytes"),
                "sha256": artifact.get("sha256"),
                "identifier": artifact["artifactBlobId"],
                "h2ometa:role": "input",
                "h2ometa:ports": artifact.get("ports") or [],
                "about": {"@id": run_action_id},
            }
        )
    return {
        "@context": [RO_CRATE_CONTEXT_1_1, WORKFLOW_RUN_CONTEXT],
        "@graph": graph,
    }


def _artifact_ro_crate_id(artifact: dict[str, Any]) -> str:
    if artifact.get("includedInPackage"):
        return f"{artifact['packagePath']}/"
    return str(artifact["externalUri"])


def _append_result_export_evidence(
    connection: Any,
    *,
    result_id: str,
    run_id: str,
    workflow_revision_id: str,
    size_bytes: int,
    sha256: str,
    manifest_sha256: str,
    artifact_count: int,
    include_artifacts: bool,
    artifact_payload_mode: str,
    created_at: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schemaVersion": RESULT_PACKAGE_SCHEMA_VERSION,
        "packageProfile": RESULT_PACKAGE_PROFILE,
        "resultId": result_id,
        "runId": run_id,
        "workflowRevisionId": workflow_revision_id,
        "sizeBytes": size_bytes,
        "sha256": sha256,
        "manifestSha256": manifest_sha256,
        "includeArtifacts": include_artifacts,
        "artifactPayloadMode": artifact_payload_mode,
        "artifactCount": artifact_count,
        "validation": {
            "schemaVersion": validation["schemaVersion"],
            "status": validation["status"],
            "manifestSha256": validation["manifestSha256"],
            "checkCount": len(validation["checks"]),
        },
        "createdAt": created_at,
    }
    return append_evidence_event(
        connection,
        event_type=RESULT_EXPORT_EVENT_TYPE,
        schema_name=RESULT_EXPORT_SCHEMA_NAME,
        subject_kind="result",
        subject_id=result_id,
        payload=payload,
        producer="artifact_product_service",
        occurred_at=created_at,
    )
