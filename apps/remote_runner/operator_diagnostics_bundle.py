from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_ledger_storage import (
    record_artifact_blob_for_path,
    record_artifact_materialization,
    record_lineage_edge,
    record_run_artifact_edge,
)
from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .storage_core import get_connection, now_iso


OPERATOR_DIAGNOSTICS_EVENT_TYPE = "operator.diagnostics.bundle.created.v1"
OPERATOR_DIAGNOSTICS_SCHEMA_NAME = "OperatorDiagnosticsBundleEvidence"


def archive_operator_diagnostics_bundle(
    cfg: RemoteRunnerConfig,
    *,
    bundle: dict[str, Any],
    bundle_path: Path,
) -> dict[str, Any]:
    path = Path(bundle_path)
    if not path.is_file():
        raise ValueError("OPERATOR_DIAGNOSTICS_BUNDLE_PATH_INVALID")
    blob = record_artifact_blob_for_path(
        cfg,
        path=path,
        media_type="application/json",
        created_at=str(bundle.get("collectedAt") or now_iso()),
    )
    materialization = record_artifact_materialization(
        cfg,
        artifact_blob_id=blob["artifactBlobId"],
        storage_backend="local",
        storage_uri=path.resolve().as_uri(),
        local_path=path,
        created_at=str(bundle.get("collectedAt") or now_iso()),
    )
    run_edge = _record_run_edge(cfg, bundle=bundle, blob=blob)
    payload = _archive_payload(
        bundle=bundle,
        blob=blob,
        materialization=materialization,
        run_edge=run_edge,
    )
    subject = payload["subject"]
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type=OPERATOR_DIAGNOSTICS_EVENT_TYPE,
            schema_name=OPERATOR_DIAGNOSTICS_SCHEMA_NAME,
            subject_kind=str(subject["kind"]),
            subject_id=str(subject["id"]),
            payload=payload,
            producer="operator_diagnostics",
            occurred_at=str(bundle.get("collectedAt") or now_iso()),
        )
        connection.commit()
    lineage_edge = _record_lineage_edge(
        cfg,
        bundle=bundle,
        blob=blob,
        event_id=str(event["eventId"]),
    )
    return {
        "eventId": event["eventId"],
        "eventType": event["eventType"],
        "payloadHash": event["payloadHash"],
        "eventHash": event["eventHash"],
        "artifactBlobId": blob["artifactBlobId"],
        "materializationId": materialization["materializationId"],
        "runArtifactEdgeId": str((run_edge or {}).get("edgeId") or ""),
        "lineageEdgeId": str((lineage_edge or {}).get("lineageEdgeId") or ""),
        "bundleSha256": blob["sha256"],
        "sizeBytes": blob["sizeBytes"],
        "subject": subject,
    }


def _archive_payload(
    *,
    bundle: dict[str, Any],
    blob: dict[str, Any],
    materialization: dict[str, Any],
    run_edge: dict[str, Any] | None,
) -> dict[str, Any]:
    subject = _archive_subject(bundle)
    identity = bundle.get("identity") if isinstance(bundle.get("identity"), dict) else {}
    release = bundle.get("release") if isinstance(bundle.get("release"), dict) else {}
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    return {
        "schemaVersion": str(bundle.get("schemaVersion") or ""),
        "bundleId": str(bundle.get("bundleId") or ""),
        "bundleHash": str(bundle.get("bundleHash") or ""),
        "bundleSha256": str(blob["sha256"]),
        "artifactBlobId": str(blob["artifactBlobId"]),
        "materializationId": str(materialization["materializationId"]),
        "runArtifactEdgeId": str((run_edge or {}).get("edgeId") or ""),
        "storageBackend": str(materialization["storageBackend"]),
        "storageUri": str(materialization["storageUri"]),
        "sizeBytes": int(blob["sizeBytes"]),
        "subject": subject,
        "serverId": str(identity.get("serverId") or ""),
        "runId": str(identity.get("runId") or ""),
        "scenarioId": str(identity.get("scenarioId") or ""),
        "releaseTag": str(release.get("releaseTag") or ""),
        "sourceCommit": str(release.get("sourceCommit") or ""),
        "collectedAt": str(bundle.get("collectedAt") or ""),
        "remoteRunnerReachable": bool(summary.get("remoteRunnerReachable")),
        "readinessOk": bool(summary.get("readinessOk")),
        "reasonCodes": list(summary.get("reasonCodes") or []),
        "endpointStatuses": dict(summary.get("endpointStatuses") or {}),
        "includedSections": list(bundle.get("includedSections") or []),
        "redactionPolicy": dict(bundle.get("redactionPolicy") or {}),
    }


def _archive_subject(bundle: dict[str, Any]) -> dict[str, str]:
    identity = bundle.get("identity") if isinstance(bundle.get("identity"), dict) else {}
    for kind, key in (("run", "runId"), ("server", "serverId"), ("scenario", "scenarioId")):
        value = str(identity.get(key) or "").strip()
        if value:
            return {"kind": kind, "id": value}
    bundle_id = str(bundle.get("bundleId") or "").strip()
    return {"kind": "operator_diagnostics", "id": bundle_id or "unscoped"}


def _record_run_edge(
    cfg: RemoteRunnerConfig,
    *,
    bundle: dict[str, Any],
    blob: dict[str, Any],
) -> dict[str, Any] | None:
    identity = bundle.get("identity") if isinstance(bundle.get("identity"), dict) else {}
    run_id = str(identity.get("runId") or "").strip()
    if not run_id:
        return None
    return record_run_artifact_edge(
        cfg,
        run_id=run_id,
        artifact_blob_id=str(blob["artifactBlobId"]),
        role="diagnostic",
        port_name="operator-diagnostics-bundle",
        step_id="operator_diagnostics",
        content_hash=str(blob["sha256"]),
        created_at=str(bundle.get("collectedAt") or now_iso()),
    )


def _record_lineage_edge(
    cfg: RemoteRunnerConfig,
    *,
    bundle: dict[str, Any],
    blob: dict[str, Any],
    event_id: str,
) -> dict[str, Any] | None:
    identity = bundle.get("identity") if isinstance(bundle.get("identity"), dict) else {}
    run_id = str(identity.get("runId") or "").strip()
    if not run_id:
        return None
    return record_lineage_edge(
        cfg,
        subject_kind="run",
        subject_id=run_id,
        predicate="prov:generated",
        object_kind="artifact_blob",
        object_id=str(blob["artifactBlobId"]),
        run_id=run_id,
        evidence_event_id=event_id,
        payload={
            "bundleId": str(bundle.get("bundleId") or ""),
            "artifactKey": "operator-diagnostics-bundle",
            "role": "diagnostic",
        },
        content_hash=str(blob["sha256"]),
        created_at=str(bundle.get("collectedAt") or now_iso()),
    )
