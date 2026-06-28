"""Server-side validation card for the First Successful Run flow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.api.execution_query_service import (
    get_result_from_request,
    get_run_from_request,
    list_result_package_exports_from_request,
)
from apps.api.workflow_sample_data_service import MOVING_PICTURES_PIPELINE_ID


FIRST_RUN_VALIDATION_CARD_SCHEMA_VERSION = "h2ometa.first-run.validation-card.v1"
FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED = "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_REQUIRED"


class WorkflowFirstRunValidationCardUnavailableError(ValueError):
    status_code = 409


async def build_first_run_validation_card_from_request(
    run_id: str,
    *,
    server_id: str | None = None,
) -> dict[str, Any]:
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        raise _unavailable("FIRST_RUN_RUN_ID_REQUIRED", "runId is required")

    run_payload = await get_run_from_request(normalized_run_id)
    run = _require_mapping(_unwrap_data(run_payload, {}), "FIRST_RUN_RUN_NOT_FOUND", normalized_run_id)
    pipeline_id = _pipeline_id(run)
    if pipeline_id != MOVING_PICTURES_PIPELINE_ID:
        raise _unavailable(
            "FIRST_RUN_PIPELINE_UNSUPPORTED",
            f"expected {MOVING_PICTURES_PIPELINE_ID}, got {pipeline_id or 'missing'}",
        )

    status = str(run.get("status") or "").strip()
    if status != "completed":
        raise _unavailable("FIRST_RUN_NOT_SUCCESSFUL", f"run status is {status or 'missing'}")

    workflow_revision_id = _workflow_revision_id(run)
    if not workflow_revision_id:
        raise _unavailable(
            "FIRST_RUN_WORKFLOW_REVISION_REQUIRED",
            "completed first-run validation requires WorkflowRevision",
        )

    result_id = _canonical_result_id_for_run(normalized_run_id)
    result_payload = await get_result_from_request(result_id)
    result = _require_mapping(_unwrap_data(result_payload, {}), "FIRST_RUN_RESULT_MISSING", result_id)
    if str(result.get("runId") or "").strip() != normalized_run_id:
        raise _unavailable("FIRST_RUN_RESULT_RUN_MISMATCH", f"{result_id} does not belong to {normalized_run_id}")

    exports_payload = await list_result_package_exports_from_request(
        result_id,
        server_id=server_id,
        lifecycle_state="active",
        limit=25,
    )
    exports_data = _require_mapping(_unwrap_data(exports_payload, {}), FIRST_RUN_RESULT_PACKAGE_REQUIRED, result_id)
    package_export = _require_result_package(exports_data.get("items"))

    card = _build_validation_card(
        package_export=package_export,
        result=result,
        result_id=result_id,
        run=run,
        server_id=server_id,
        workflow_revision_id=workflow_revision_id,
    )
    return {"data": card}


def _build_validation_card(
    *,
    package_export: dict[str, Any],
    result: dict[str, Any],
    result_id: str,
    run: dict[str, Any],
    server_id: str | None,
    workflow_revision_id: str,
) -> dict[str, Any]:
    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    artifacts = [_safe_artifact(item) for item in _mapping_items(result.get("artifacts"))]
    input_artifacts = [_safe_input_artifact(item) for item in _mapping_items(result.get("inputArtifacts"))]
    _assert_validation_card_evidence(
        artifacts=artifacts,
        input_artifacts=input_artifacts,
        package_export=package_export,
        result_id=result_id,
        workflow_revision_id=workflow_revision_id,
    )
    return {
        "schemaVersion": FIRST_RUN_VALIDATION_CARD_SCHEMA_VERSION,
        "generatedAt": _utc_now(),
        "scenario": {
            "scenarioId": "moving-pictures-16s",
            "dataset": "QIIME 2 Moving Pictures tutorial",
            "datasetUrl": "https://docs.qiime2.org/2024.10/tutorials/moving-pictures/",
            "pipelineId": MOVING_PICTURES_PIPELINE_ID,
            "pipelineName": "Moving Pictures 16S",
        },
        "run": {
            "runId": str(run.get("runId") or ""),
            "status": str(run.get("status") or ""),
            "stage": str(run.get("stage") or ""),
            "startedAt": str(run.get("startedAt") or ""),
            "finishedAt": str(run.get("finishedAt") or ""),
        },
        "runner": {
            "serverId": str(server_id or ""),
        },
        "workflowRevision": {
            "workflowRevisionId": workflow_revision_id,
        },
        "inputs": [_safe_run_input(item) for item in _mapping_items(run_spec.get("inputs"))],
        "inputArtifacts": input_artifacts,
        "result": {
            "resultId": result_id,
            "artifactCount": len(artifacts),
            "inputArtifactCount": len(input_artifacts),
            "lineageSummary": _safe_lineage_summary(result.get("lineageSummary")),
        },
        "keyResults": _key_results(artifacts),
        "artifacts": artifacts,
        "database": {
            "required": False,
            "summary": "No external reference database is required for this Moving Pictures 16S first run.",
        },
        "resultPackage": _safe_result_package(package_export),
        "checks": _validation_checks(
            artifacts=artifacts,
            input_artifacts=input_artifacts,
            package_export=package_export,
            workflow_revision_id=workflow_revision_id,
        ),
        "standards": {
            "w3cProv": "https://www.w3.org/TR/prov-primer/",
            "workflowRunCrate": "https://www.researchobject.org/workflow-run-crate/",
        },
    }


def _validation_checks(
    *,
    artifacts: list[dict[str, Any]],
    input_artifacts: list[dict[str, Any]],
    package_export: dict[str, Any],
    workflow_revision_id: str,
) -> list[dict[str, Any]]:
    checksum_count = sum(1 for artifact in artifacts if artifact.get("sha256"))
    return [
        _passed_check("FIRST_RUN_PIPELINE_MATCH", MOVING_PICTURES_PIPELINE_ID),
        _passed_check("FIRST_RUN_COMPLETED", "run status is completed"),
        _passed_check("FIRST_RUN_WORKFLOW_REVISION_PRESENT", workflow_revision_id),
        _passed_check("FIRST_RUN_INPUT_LINEAGE_PRESENT", f"{len(input_artifacts)} input artifacts"),
        _passed_check("FIRST_RUN_OUTPUT_CHECKSUMS_PRESENT", f"{checksum_count} output checksums"),
        _passed_check("FIRST_RUN_RESULT_PACKAGE_ACTIVE", str(package_export.get("packageExportId") or "")),
    ]


def _passed_check(code: str, detail: str) -> dict[str, str]:
    return {
        "code": code,
        "status": "passed",
        "detail": detail,
    }


def _safe_run_input(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "role": item.get("role"),
            "filename": item.get("filename"),
            "uploadId": item.get("uploadId"),
            "artifactId": item.get("artifactId") or item.get("sourceArtifactId"),
            "artifactBlobId": item.get("artifactBlobId"),
            "upstreamRunId": item.get("upstreamRunId"),
        }
    )


def _safe_input_artifact(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "artifactBlobId": item.get("artifactBlobId"),
            "sha256": item.get("sha256"),
            "mimeType": item.get("mimeType"),
            "sizeBytes": item.get("sizeBytes"),
            "ports": [_safe_input_port(port) for port in _mapping_items(item.get("ports"))],
        }
    )


def _safe_input_port(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "portName": item.get("portName"),
            "inputName": item.get("inputName"),
            "inputRole": item.get("inputRole"),
            "inputIndex": item.get("inputIndex"),
            "sourceType": item.get("sourceType"),
            "sourceId": item.get("sourceId"),
            "filename": item.get("filename"),
            "uploadId": item.get("uploadId"),
            "artifactId": item.get("artifactId"),
            "upstreamRunId": item.get("upstreamRunId"),
        }
    )


def _safe_artifact(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "artifactId": item.get("artifactId"),
            "artifactKey": item.get("artifactKey"),
            "kind": item.get("kind"),
            "mimeType": item.get("mimeType"),
            "sizeBytes": item.get("sizeBytes"),
            "sha256": item.get("sha256"),
        }
    )


def _safe_lineage_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _compact(
        {
            "schemaVersion": value.get("schemaVersion"),
            "edgeCount": value.get("edgeCount"),
            "inputEdgeCount": value.get("inputEdgeCount"),
            "outputEdgeCount": value.get("outputEdgeCount"),
            "cacheAdoptionEdgeCount": value.get("cacheAdoptionEdgeCount"),
            "predicateCounts": value.get("predicateCounts") if isinstance(value.get("predicateCounts"), dict) else None,
        }
    )


def _safe_result_package(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "packageExportId": item.get("packageExportId"),
            "resultId": item.get("resultId"),
            "runId": item.get("runId"),
            "workflowRevisionId": item.get("workflowRevisionId"),
            "lifecycleState": item.get("lifecycleState"),
            "packageBytesState": item.get("packageBytesState"),
            "artifactPayloadMode": item.get("artifactPayloadMode"),
            "includeArtifacts": item.get("includeArtifacts"),
            "sizeBytes": item.get("sizeBytes"),
            "sha256": item.get("sha256"),
            "manifestSha256": item.get("manifestSha256"),
            "evidenceId": item.get("evidenceId"),
            "download": item.get("download") if isinstance(item.get("download"), dict) else None,
            "createdAt": item.get("createdAt"),
        }
    )


def _key_results(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred = []
    for artifact in artifacts:
        label = str(artifact.get("artifactKey") or artifact.get("kind") or artifact.get("artifactId") or "")
        if label in {"summary.tsv", "qc-summary.tsv", "run-report.html"}:
            preferred.append(artifact)
    return preferred or artifacts[:3]


def _require_result_package(items: Any) -> dict[str, Any]:
    exports = [item for item in _mapping_items(items) if item.get("lifecycleState") == "active"]
    if not exports:
        raise _unavailable(
            FIRST_RUN_RESULT_PACKAGE_REQUIRED,
            "generate a full result package before exporting a validation card",
        )
    downloadable = [
        item
        for item in exports
        if item.get("packageBytesState") == "available" and isinstance(item.get("download"), dict)
    ]
    if not downloadable:
        raise _unavailable(
            FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED,
            "validation card requires an active package with downloadable bytes",
        )
    full_downloads = [item for item in downloadable if item.get("artifactPayloadMode") == "full" or item.get("includeArtifacts") is True]
    if not full_downloads:
        raise _unavailable(
            FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED,
            "validation card requires a full result package, not metadata-only evidence",
        )
    return full_downloads[0]


def _assert_validation_card_evidence(
    *,
    artifacts: list[dict[str, Any]],
    input_artifacts: list[dict[str, Any]],
    package_export: dict[str, Any],
    result_id: str,
    workflow_revision_id: str,
) -> None:
    if not input_artifacts:
        raise _unavailable("FIRST_RUN_INPUT_LINEAGE_REQUIRED", "input artifact lineage is empty")
    if not artifacts:
        raise _unavailable("FIRST_RUN_OUTPUT_ARTIFACTS_REQUIRED", "output artifacts are empty")
    missing_checksums = [str(item.get("artifactId") or "unknown") for item in artifacts if not item.get("sha256")]
    if missing_checksums:
        raise _unavailable(
            "FIRST_RUN_OUTPUT_CHECKSUMS_REQUIRED",
            f"output artifact checksums missing: {', '.join(missing_checksums)}",
        )
    if not package_export.get("sha256") or not package_export.get("manifestSha256"):
        raise _unavailable(
            FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED,
            "result package sha256 and manifestSha256 are required",
        )
    if str(package_export.get("resultId") or "").strip() != result_id:
        raise _unavailable(
            "FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH",
            "result package does not match the first-run result",
        )
    if str(package_export.get("workflowRevisionId") or "").strip() != workflow_revision_id:
        raise _unavailable(
            "FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH",
            "result package does not match the first-run WorkflowRevision",
        )


def _pipeline_id(run: dict[str, Any]) -> str:
    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    return str(run.get("pipelineId") or run_spec.get("pipelineId") or "").strip()


def _workflow_revision_id(run: dict[str, Any]) -> str:
    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    return str(run.get("workflowRevisionId") or run_spec.get("workflowRevisionId") or "").strip()


def _canonical_result_id_for_run(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    return normalized if normalized.startswith("res_") else f"res_{normalized}"


def _require_mapping(value: Any, code: str, detail: str) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return value
    raise _unavailable(code, detail)


def _unwrap_data(payload: Any, default: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload if payload is not None else default


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _unavailable(code: str, detail: str) -> WorkflowFirstRunValidationCardUnavailableError:
    return WorkflowFirstRunValidationCardUnavailableError(f"{code}: {detail}")
