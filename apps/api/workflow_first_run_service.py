"""Server-side validation card for the First Successful Run flow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.api.execution_query_service import (
    get_result_from_request,
    get_result_preview_from_request,
    get_run_from_request,
    get_workflow_revision_from_request,
    list_result_package_exports_from_request,
)
from apps.api.workflow_first_run_pilot_handoff import build_first_run_pilot_handoff
from apps.api.workflow_first_run_software_evidence import build_first_run_software_environment
from apps.api.workflow_sample_data_service import MOVING_PICTURES_FILES, MOVING_PICTURES_PIPELINE_ID


FIRST_RUN_VALIDATION_CARD_SCHEMA_VERSION = "h2ometa.first-run.validation-card.v1"
FIRST_RUN_REPORT_INTERPRETATION_SCHEMA_VERSION = "h2ometa.first-run.report-interpretation.v1"
FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED = "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"
FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED = "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"
FIRST_RUN_REPORT_PREVIEW_REQUIRED = "FIRST_RUN_REPORT_PREVIEW_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED"
FIRST_RUN_RESULT_PACKAGE_REQUIRED = "FIRST_RUN_RESULT_PACKAGE_REQUIRED"
FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH = "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH"
FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED = "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
FIRST_RUN_SAMPLE_INPUTS_REQUIRED = "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"

MOVING_PICTURES_REPORT_OUTPUTS = (
    {
        "name": "summary.tsv",
        "key": "summary",
        "label": "Sample summary",
        "kind": "table",
        "interpretation": "Per-sample body site, matched reads, passed reads, and unique feature counts.",
    },
    {
        "name": "qc-summary.tsv",
        "key": "qc_summary",
        "label": "QC summary",
        "kind": "table",
        "interpretation": "Run-level demultiplexing and quality-filter totals.",
    },
    {
        "name": "feature-table.tsv",
        "key": "feature_table",
        "label": "Feature table",
        "kind": "table",
        "interpretation": "Feature abundance matrix across samples.",
    },
    {
        "name": "run-report.html",
        "key": "report",
        "label": "HTML report",
        "kind": "report",
        "interpretation": "Human-readable report with top samples and QC cards.",
    },
)
MOVING_PICTURES_REPORT_OUTPUT_NAMES = {str(item["name"]) for item in MOVING_PICTURES_REPORT_OUTPUTS}
MOVING_PICTURES_OUTPUT_KEYS_TO_NAMES = {str(item["key"]): str(item["name"]) for item in MOVING_PICTURES_REPORT_OUTPUTS}
MOVING_PICTURES_PREVIEW_OUTPUT_NAMES = {"summary.tsv", "qc-summary.tsv"}
MOVING_PICTURES_SAMPLE_INPUTS = tuple(
    {
        "role": item.role,
        "filename": item.filename,
        "sourceUrl": item.url,
        "expectedSha256": item.expected_sha256,
        "expectedSizeBytes": item.expected_size_bytes,
    }
    for item in MOVING_PICTURES_FILES
)


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
    workflow_revision_payload = await get_workflow_revision_from_request(workflow_revision_id, server_id=server_id)
    workflow_revision = _require_mapping(_unwrap_data(workflow_revision_payload, {}), "FIRST_RUN_WORKFLOW_REVISION_NOT_FOUND", workflow_revision_id)

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
    report_previews = await _load_first_run_report_previews(
        result_id,
        _mapping_items(result.get("artifacts")),
    )

    card = _build_validation_card(
        package_export=package_export,
        report_previews=report_previews,
        result=result,
        result_id=result_id,
        run=run,
        server_id=server_id,
        workflow_revision=workflow_revision,
        workflow_revision_id=workflow_revision_id,
    )
    return {"data": card}


def _build_validation_card(
    *,
    package_export: dict[str, Any],
    report_previews: dict[str, dict[str, Any]],
    result: dict[str, Any],
    result_id: str,
    run: dict[str, Any],
    server_id: str | None,
    workflow_revision: dict[str, Any],
    workflow_revision_id: str,
) -> dict[str, Any]:
    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    artifacts = [_safe_artifact(item) for item in _mapping_items(result.get("artifacts"))]
    run_inputs = [_safe_run_input(item) for item in _mapping_items(run_spec.get("inputs"))]
    input_artifacts = [_safe_input_artifact(item) for item in _mapping_items(result.get("inputArtifacts"))]
    _assert_validation_card_evidence(
        artifacts=artifacts,
        input_artifacts=input_artifacts,
        package_export=package_export,
        result_id=result_id,
        workflow_revision_id=workflow_revision_id,
    )
    sample_data = _sample_data_evidence(
        input_artifacts=input_artifacts,
        run_inputs=run_inputs,
        sample_data_prep_proof=_safe_sample_data_prep_proof(run_spec.get("sampleDataPrepProof")),
    )
    try:
        software_environment = build_first_run_software_environment(workflow_revision)
    except ValueError as exc:
        raise _unavailable(str(exc).split(":", 1)[0], str(exc)) from exc
    report_interpretation = _report_interpretation(
        artifacts=artifacts,
        report_previews=report_previews,
    )
    checks = _validation_checks(
        artifacts=artifacts,
        input_artifacts=input_artifacts,
        package_export=package_export,
        report_interpretation=report_interpretation,
        sample_data=sample_data,
        software_environment=software_environment,
        workflow_revision_id=workflow_revision_id,
    )
    card = {
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
            "contentHash": software_environment.get("contentHash"),
        },
        "softwareEnvironment": software_environment,
        "inputs": run_inputs,
        "inputArtifacts": input_artifacts,
        "sampleData": sample_data,
        "result": {
            "resultId": result_id,
            "artifactCount": len(artifacts),
            "inputArtifactCount": len(input_artifacts),
            "lineageSummary": _safe_lineage_summary(result.get("lineageSummary")),
        },
        "reportInterpretation": report_interpretation,
        "keyResults": _key_results(artifacts),
        "artifacts": artifacts,
        "database": {
            "required": False,
            "summary": "No external reference database is required for this Moving Pictures 16S first run.",
        },
        "resultPackage": _safe_result_package(package_export),
        "checks": checks,
        "standards": {
            "w3cProv": "https://www.w3.org/TR/prov-primer/",
            "workflowRunCrate": "https://www.researchobject.org/workflow-run-crate/",
        },
    }
    card["pilotHandoff"] = build_first_run_pilot_handoff(card)
    return card


def _validation_checks(
    *,
    artifacts: list[dict[str, Any]],
    input_artifacts: list[dict[str, Any]],
    package_export: dict[str, Any],
    report_interpretation: dict[str, Any],
    sample_data: dict[str, Any],
    software_environment: dict[str, Any],
    workflow_revision_id: str,
) -> list[dict[str, Any]]:
    checksum_count = sum(1 for artifact in artifacts if artifact.get("sha256"))
    return [
        _passed_check("FIRST_RUN_PIPELINE_MATCH", MOVING_PICTURES_PIPELINE_ID),
        _passed_check("FIRST_RUN_COMPLETED", "run status is completed"),
        _passed_check("FIRST_RUN_WORKFLOW_REVISION_PRESENT", workflow_revision_id),
        _passed_check("FIRST_RUN_SOFTWARE_ENVIRONMENT_VERIFIED", str(software_environment.get("contentHash") or "")),
        _passed_check("FIRST_RUN_INPUT_LINEAGE_PRESENT", f"{len(input_artifacts)} input artifacts"),
        _passed_check("FIRST_RUN_SAMPLE_INPUTS_VERIFIED", f"{len(sample_data.get('items') or [])} official sample inputs"),
        _passed_check("FIRST_RUN_OUTPUT_CHECKSUMS_PRESENT", f"{checksum_count} output checksums"),
        _passed_check("FIRST_RUN_EXPECTED_OUTPUTS_PRESENT", ", ".join(sorted(MOVING_PICTURES_REPORT_OUTPUT_NAMES))),
        _passed_check(
            "FIRST_RUN_REPORT_INTERPRETATION_READY",
            f"{len(report_interpretation.get('metrics') or [])} metrics",
        ),
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
            "displayName": _artifact_output_name(item),
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


def _sample_data_evidence(
    *,
    run_inputs: list[dict[str, Any]],
    input_artifacts: list[dict[str, Any]],
    sample_data_prep_proof: dict[str, Any],
) -> dict[str, Any]:
    run_inputs_by_role = _run_inputs_by_role(run_inputs)
    input_artifacts_by_role = _input_artifacts_by_role(input_artifacts)
    prep_proof = _sample_data_prep_proof_by_role(sample_data_prep_proof)
    items = []
    for expected in MOVING_PICTURES_SAMPLE_INPUTS:
        role = str(expected["role"])
        run_input = run_inputs_by_role.get(role)
        if not run_input:
            raise _unavailable(FIRST_RUN_SAMPLE_INPUTS_REQUIRED, f"{role} run input is missing")
        if str(run_input.get("filename") or "") != expected["filename"]:
            raise _unavailable(
                FIRST_RUN_SAMPLE_INPUTS_REQUIRED,
                f"{role} filename must be {expected['filename']}",
            )
        input_artifact = input_artifacts_by_role.get(role)
        if not input_artifact:
            raise _unavailable(FIRST_RUN_SAMPLE_INPUTS_REQUIRED, f"{role} input artifact lineage is missing")
        _assert_sample_input_integrity(role=role, expected=expected, input_artifact=input_artifact)
        prep_item = prep_proof["itemsByRole"].get(role)
        if not prep_item:
            raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep proof is missing")
        _assert_sample_prep_proof(role=role, expected=expected, prep_item=prep_item)
        port = input_artifact["port"]
        artifact = input_artifact["artifact"]
        items.append(
            _compact(
                {
                    "role": role,
                    "filename": expected["filename"],
                    "sourceUrl": expected["sourceUrl"],
                    "prepProof": prep_item,
                    "uploadId": run_input.get("uploadId") or port.get("uploadId"),
                    "artifactBlobId": artifact.get("artifactBlobId"),
                    "sha256": artifact.get("sha256"),
                    "expectedSha256": expected["expectedSha256"],
                    "sizeBytes": artifact.get("sizeBytes"),
                    "expectedSizeBytes": expected["expectedSizeBytes"],
                    "integrityStatus": "passed",
                }
            )
        )
    return {
        "schemaVersion": "h2ometa.first-run.sample-data-evidence.v1",
        "source": "QIIME 2 Moving Pictures tutorial",
        "status": "verified",
        "prepProof": prep_proof["summary"],
        "items": items,
    }


def _safe_sample_data_prep_proof(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    items = [_safe_sample_prep_item(item) for item in _mapping_items(value.get("items"))]
    return _compact(
        {
            "schemaVersion": value.get("schemaVersion"),
            "source": value.get("source"),
            "cachePolicy": value.get("cachePolicy"),
            "items": [item for item in items if item],
        }
    )


def _sample_data_prep_proof_by_role(proof: dict[str, Any]) -> dict[str, Any]:
    if proof.get("schemaVersion") != "h2ometa.workflow-sample-data-prep-proof.v1":
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, "sample prep proof schema is invalid")
    if proof.get("source") != "QIIME 2 Moving Pictures tutorial":
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, "sample prep proof source is invalid")
    if proof.get("cachePolicy") != "verified-sha256-local-cache":
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, "sample prep proof cache policy is invalid")
    items = [item for item in _mapping_items(proof.get("items")) if item]
    by_role = {str(item.get("role") or ""): item for item in items if item.get("role")}
    return {
        "summary": {
            "schemaVersion": "h2ometa.workflow-sample-data-prep-proof.v1",
            "source": "QIIME 2 Moving Pictures tutorial",
            "cachePolicy": "verified-sha256-local-cache",
            "items": items,
        },
        "itemsByRole": by_role,
    }


def _safe_sample_prep_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _compact(
        {
            "schemaVersion": value.get("schemaVersion"),
            "role": value.get("role"),
            "filename": value.get("filename"),
            "sourceUrl": value.get("sourceUrl"),
            "sha256": value.get("sha256"),
            "expectedSha256": value.get("expectedSha256"),
            "expectedSizeBytes": value.get("expectedSizeBytes"),
            "cacheStatus": value.get("cacheStatus"),
            "downloadStatus": value.get("downloadStatus"),
            "downloadAttempts": value.get("downloadAttempts"),
        }
    )


def _assert_sample_prep_proof(*, role: str, expected: dict[str, Any], prep_item: dict[str, Any]) -> None:
    if prep_item.get("schemaVersion") != "h2ometa.workflow-sample-data-prep-proof.v1":
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep proof schema is invalid")
    if str(prep_item.get("filename") or "") != expected["filename"]:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep filename is invalid")
    if str(prep_item.get("sourceUrl") or "") != expected["sourceUrl"]:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep source is invalid")
    if str(prep_item.get("expectedSha256") or "") != expected["expectedSha256"]:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep hash is invalid")
    if prep_item.get("expectedSizeBytes") != expected["expectedSizeBytes"]:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep size is invalid")
    if str(prep_item.get("sha256") or "") != expected["expectedSha256"]:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep sha256 is invalid")
    if str(prep_item.get("cacheStatus") or "") not in {"stored", "hit", "write-failed"}:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep cache status is invalid")
    if str(prep_item.get("downloadStatus") or "") not in {"downloaded", "skipped-cache-hit"}:
        raise _unavailable(FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED, f"{role} sample prep download status is invalid")


def _run_inputs_by_role(run_inputs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_role: dict[str, dict[str, Any]] = {}
    for item in run_inputs:
        role = str(item.get("role") or "").strip()
        if role in {str(expected["role"]) for expected in MOVING_PICTURES_SAMPLE_INPUTS}:
            by_role[role] = item
    return by_role


def _input_artifacts_by_role(input_artifacts: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    by_role: dict[str, dict[str, dict[str, Any]]] = {}
    expected_by_role = {str(item["role"]): item for item in MOVING_PICTURES_SAMPLE_INPUTS}
    expected_by_filename = {str(item["filename"]): item for item in MOVING_PICTURES_SAMPLE_INPUTS}
    for artifact in input_artifacts:
        for port in _mapping_items(artifact.get("ports")):
            role = _sample_role_for_port(port, expected_by_role, expected_by_filename)
            if role and role not in by_role:
                by_role[role] = {"artifact": artifact, "port": port}
    return by_role


def _sample_role_for_port(
    port: dict[str, Any],
    expected_by_role: dict[str, dict[str, Any]],
    expected_by_filename: dict[str, dict[str, Any]],
) -> str:
    for key in ("inputRole", "portName", "inputName"):
        value = str(port.get(key) or "").strip()
        if value in expected_by_role:
            return value
    filename = str(port.get("filename") or "").strip()
    expected = expected_by_filename.get(filename)
    return str(expected["role"]) if expected else ""


def _assert_sample_input_integrity(
    *,
    role: str,
    expected: dict[str, Any],
    input_artifact: dict[str, dict[str, Any]],
) -> None:
    artifact = input_artifact["artifact"]
    actual_sha = str(artifact.get("sha256") or "")
    expected_sha = str(expected["expectedSha256"])
    actual_size = artifact.get("sizeBytes")
    expected_size = expected["expectedSizeBytes"]
    if actual_sha != expected_sha or actual_size != expected_size:
        raise _unavailable(
            FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH,
            f"{role} expected size={expected_size} sha256={expected_sha}",
        )


async def _load_first_run_report_previews(
    result_id: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    previews: dict[str, dict[str, Any]] = {}
    for output in MOVING_PICTURES_REPORT_OUTPUTS:
        output_name = str(output["name"])
        if output_name not in MOVING_PICTURES_PREVIEW_OUTPUT_NAMES:
            continue
        artifact = _artifact_for_output(artifacts, output_name)
        if artifact is None:
            continue
        artifact_id = str(artifact.get("artifactId") or "").strip()
        if not artifact_id:
            raise _unavailable(FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED, f"{output_name} artifactId is missing")
        try:
            payload = await get_result_preview_from_request(result_id, artifact_id=artifact_id)
        except Exception as exc:  # noqa: BLE001 - validation cards must fail closed when preview evidence is unreadable.
            raise _unavailable(
                FIRST_RUN_REPORT_PREVIEW_REQUIRED,
                f"{output_name} preview is required: {type(exc).__name__}",
            ) from exc
        previews[output_name] = _require_mapping(
            _unwrap_data(payload, {}),
            FIRST_RUN_REPORT_PREVIEW_REQUIRED,
            f"{output_name} preview payload is empty",
        )
    return previews


def _report_interpretation(
    *,
    artifacts: list[dict[str, Any]],
    report_previews: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing_outputs = _missing_expected_output_names(artifacts)
    if missing_outputs:
        raise _unavailable(
            FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED,
            f"expected Moving Pictures outputs missing: {', '.join(missing_outputs)}",
        )
    summary_columns, summary_rows, summary_truncated = _required_table_preview(
        report_previews.get("summary.tsv"),
        "summary.tsv",
        required_columns=("passed_reads", "unique_features"),
    )
    qc_columns, qc_rows, qc_truncated = _required_table_preview(
        report_previews.get("qc-summary.tsv"),
        "qc-summary.tsv",
        required_columns=("metric", "value"),
    )
    return {
        "schemaVersion": FIRST_RUN_REPORT_INTERPRETATION_SCHEMA_VERSION,
        "status": "ready",
        "summary": "Moving Pictures 16S first run completed with the expected report, summary, QC, and feature-table artifacts.",
        "outputs": _report_output_items(artifacts),
        "metrics": [
            *_summary_metrics(summary_columns, summary_rows),
            *_qc_metrics(qc_columns, qc_rows),
        ],
        "previewSources": [
            _preview_source(report_previews["summary.tsv"], "summary.tsv", summary_truncated),
            _preview_source(report_previews["qc-summary.tsv"], "qc-summary.tsv", qc_truncated),
        ],
        "redaction": {
            "rawPathsExposed": False,
            "storageUrisExposed": False,
            "previewRowsEmbedded": False,
            "policy": "metrics-only",
        },
    }


def _report_output_items(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {
        output_name: artifact
        for artifact in artifacts
        if (output_name := _artifact_output_name(artifact)) in MOVING_PICTURES_REPORT_OUTPUT_NAMES
    }
    items = []
    for output in MOVING_PICTURES_REPORT_OUTPUTS:
        artifact = by_name[str(output["name"])]
        items.append(
            _compact(
                {
                    "name": output["name"],
                    "key": output["key"],
                    "label": output["label"],
                    "kind": output["kind"],
                    "present": True,
                    "artifactId": artifact.get("artifactId"),
                    "mimeType": artifact.get("mimeType"),
                    "sizeBytes": artifact.get("sizeBytes"),
                    "sha256": artifact.get("sha256"),
                    "interpretation": output["interpretation"],
                }
            )
        )
    return items


def _required_table_preview(
    preview: dict[str, Any] | None,
    output_name: str,
    *,
    required_columns: tuple[str, ...],
) -> tuple[list[str], list[list[str]], bool]:
    if not isinstance(preview, dict):
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{output_name} preview is missing")
    preview_data = preview.get("preview") if isinstance(preview.get("preview"), dict) else {}
    if preview_data.get("kind") != "table":
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{output_name} preview is not a table")
    columns = [str(item) for item in preview_data.get("columns") or []]
    rows = [
        [str(cell) for cell in row]
        for row in (preview_data.get("rows") or [])
        if isinstance(row, list)
    ]
    if not columns or not rows:
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{output_name} table preview is empty")
    missing_columns = [column for column in required_columns if column not in columns]
    if missing_columns:
        raise _unavailable(
            FIRST_RUN_REPORT_PREVIEW_REQUIRED,
            f"{output_name} preview missing columns: {', '.join(missing_columns)}",
        )
    return columns, rows, bool(preview_data.get("truncated"))


def _summary_metrics(columns: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    passed_reads = _sum_numeric_column(rows, columns.index("passed_reads"), "summary.tsv:passed_reads")
    unique_features = _sum_numeric_column(rows, columns.index("unique_features"), "summary.tsv:unique_features")
    return [
        _metric("sample_count", "samples", len(rows), "summary.tsv"),
        _metric("passed_reads_total", "passed reads", passed_reads, "summary.tsv"),
        _metric("unique_features_sample_sum", "unique features", unique_features, "summary.tsv"),
    ]


def _qc_metrics(columns: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    metric_index = columns.index("metric")
    value_index = columns.index("value")
    preferred = {"total_pairs", "matched_reads", "passed_reads", "samples_with_reads", "features"}
    metrics = []
    for row in rows:
        metric_id = str(row[metric_index] if metric_index < len(row) else "").strip()
        if metric_id not in preferred:
            continue
        value = _numeric_value(row[value_index] if value_index < len(row) else "", f"qc-summary.tsv:{metric_id}")
        metrics.append(_metric(f"qc_{metric_id}", metric_id.replace("_", " "), value, "qc-summary.tsv"))
    return metrics


def _metric(metric_id: str, label: str, value: int | float, source: str) -> dict[str, Any]:
    return {
        "metricId": metric_id,
        "label": label,
        "value": value,
        "displayValue": _format_number(value),
        "source": source,
    }


def _sum_numeric_column(rows: list[list[str]], column_index: int, source: str) -> int | float:
    return sum(_numeric_value(row[column_index] if column_index < len(row) else "", source) for row in rows)


def _numeric_value(value: Any, source: str) -> int | float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{source} has an empty numeric value")
    try:
        number = float(text)
    except ValueError as exc:
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{source} is not numeric") from exc
    return int(number) if number.is_integer() else number


def _format_number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _preview_source(preview: dict[str, Any], output_name: str, truncated: bool) -> dict[str, Any]:
    artifact = preview.get("artifact") if isinstance(preview.get("artifact"), dict) else {}
    preview_data = preview.get("preview") if isinstance(preview.get("preview"), dict) else {}
    return _compact(
        {
            "name": output_name,
            "artifactId": preview.get("artifactId") or artifact.get("artifactId"),
            "kind": preview_data.get("kind"),
            "truncated": truncated,
        }
    )


def _key_results(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred = []
    for artifact in artifacts:
        label = _artifact_output_name(artifact) or str(artifact.get("kind") or artifact.get("artifactId") or "")
        if label in {"summary.tsv", "qc-summary.tsv", "feature-table.tsv", "run-report.html"}:
            preferred.append(artifact)
    return preferred or artifacts[:3]


def _artifact_for_output(artifacts: list[dict[str, Any]], output_name: str) -> dict[str, Any] | None:
    return next((artifact for artifact in artifacts if _artifact_output_name(artifact) == output_name), None)


def _missing_expected_output_names(artifacts: list[dict[str, Any]]) -> list[str]:
    present = {_artifact_output_name(artifact) for artifact in artifacts}
    return sorted(name for name in MOVING_PICTURES_REPORT_OUTPUT_NAMES if name not in present)


def _artifact_output_name(item: dict[str, Any]) -> str:
    for key in ("displayName", "artifactKey", "name"):
        label = str(item.get(key) or "").strip()
        if label in MOVING_PICTURES_REPORT_OUTPUT_NAMES:
            return label
        mapped = MOVING_PICTURES_OUTPUT_KEYS_TO_NAMES.get(label)
        if mapped:
            return mapped
    basename = _basename(item.get("path"))
    return basename if basename in MOVING_PICTURES_REPORT_OUTPUT_NAMES else ""


def _basename(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    return text.rsplit("/", 1)[-1] if text else ""


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
    missing_expected_outputs = _missing_expected_output_names(artifacts)
    if missing_expected_outputs:
        raise _unavailable(
            FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED,
            f"expected Moving Pictures outputs missing: {', '.join(missing_expected_outputs)}",
        )
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
