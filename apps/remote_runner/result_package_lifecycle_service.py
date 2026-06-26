from __future__ import annotations

from typing import Any, Literal

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .governance_audit import record_governance_audit_event
from .result_package_download_service import build_result_package_download
from .result_package_storage import mark_result_package_export_retired
from .storage_core import get_connection, now_iso


RESULT_PACKAGE_RETIRE_CONFIRMATION: Literal["retire-result-package-export"] = "retire-result-package-export"
RESULT_PACKAGE_RETIRE_EVENT_TYPE = "result.package.retire.v1"
RESULT_PACKAGE_RETIRE_SCHEMA_NAME = "ResultPackageRetireEvent"
RESULT_PACKAGE_RETIRE_SCHEMA_VERSION = "h2ometa.result-package-retire.v1"


def retire_result_package_export(
    cfg: RemoteRunnerConfig,
    result_id: str,
    package_export_id: str,
    *,
    confirmation: str,
    actor: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if str(confirmation or "").strip() != RESULT_PACKAGE_RETIRE_CONFIRMATION:
        raise ValueError("RESULT_PACKAGE_RETIRE_CONFIRMATION_REQUIRED")
    normalized_actor = str(actor or "remote-runner-api").strip() or "remote-runner-api"
    normalized_reason = str(reason or "").strip()
    download = build_result_package_download(
        cfg,
        result_id=result_id,
        package_export_id=package_export_id,
    )
    retired_at = now_iso()
    with get_connection(cfg) as connection:
        record = mark_result_package_export_retired(
            connection,
            package_export_id=download["packageExportId"],
            retired_at=retired_at,
        )
        evidence = append_evidence_event(
            connection,
            event_type=RESULT_PACKAGE_RETIRE_EVENT_TYPE,
            schema_name=RESULT_PACKAGE_RETIRE_SCHEMA_NAME,
            subject_kind="result_package_export",
            subject_id=download["packageExportId"],
            payload=_retire_evidence_payload(
                download,
                actor=normalized_actor,
                reason=normalized_reason,
                retired_at=retired_at,
            ),
            schema_version="v1",
            producer="result_package_lifecycle_service",
            occurred_at=retired_at,
        )
        connection.commit()
    audit = record_governance_audit_event(
        cfg,
        action="result.package.retire",
        actor=normalized_actor,
        subject_kind="result_package_export",
        subject_id=download["packageExportId"],
        details={
            "resultId": download["resultId"],
            "runId": download["runId"],
            "packageExportId": download["packageExportId"],
            "workflowRevisionId": download["workflowRevisionId"],
            "artifactPayloadMode": download["artifactPayloadMode"],
            "sizeBytes": download["sizeBytes"],
            "packageSha256": download["sha256"],
            "manifestSha256": download["manifestSha256"],
            "packageFileDeleted": False,
            "reason": normalized_reason,
            "evidenceId": evidence["eventId"],
        },
    )
    return {
        "schemaVersion": RESULT_PACKAGE_RETIRE_SCHEMA_VERSION,
        "resultId": record["resultId"],
        "runId": record["runId"],
        "packageExportId": record["packageExportId"],
        "workflowRevisionId": record["workflowRevisionId"],
        "artifactPayloadMode": record["artifactPayloadMode"],
        "lifecycleState": record["lifecycleState"],
        "retiredAt": retired_at,
        "packageFileDeleted": False,
        "sizeBytes": download["sizeBytes"],
        "sha256": download["sha256"],
        "manifestSha256": download["manifestSha256"],
        "evidenceId": evidence["eventId"],
        "governanceAuditEventId": audit["eventId"],
    }


def _retire_evidence_payload(
    download: dict[str, Any],
    *,
    actor: str,
    reason: str,
    retired_at: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": RESULT_PACKAGE_RETIRE_SCHEMA_VERSION,
        "resultId": download["resultId"],
        "runId": download["runId"],
        "packageExportId": download["packageExportId"],
        "workflowRevisionId": download["workflowRevisionId"],
        "artifactPayloadMode": download["artifactPayloadMode"],
        "actor": actor,
        "reason": reason,
        "retiredAt": retired_at,
        "packageFileDeleted": False,
        "sizeBytes": download["sizeBytes"],
        "packageSha256": download["sha256"],
        "manifestSha256": download["manifestSha256"],
    }
