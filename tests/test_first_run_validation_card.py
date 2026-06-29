from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_validation_card_from_request,
)
from apps.api.workflow_first_run_finalize_service import (
    WorkflowFirstRunFinalizeRequest,
    finalize_first_run_from_request,
)
from apps.api.workflow_sample_data_service import MOVING_PICTURES_FILES


def test_first_run_validation_card_is_server_generated_and_redacted(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    _patch_first_run_sources(monkeypatch, calls=calls)

    card = asyncio.run(
        build_first_run_validation_card_from_request(
            "run_first",
            server_id="srv_first",
        )
    )["data"]

    assert calls == [
        ("revision", "srv_first"),
        ("exports", "srv_first"),
        ("preview", "art_summary"),
        ("preview", "art_qc"),
    ]
    assert card["schemaVersion"] == "h2ometa.first-run.validation-card.v1"
    assert card["generatedAt"] == "2026-06-29T00:00:00Z"
    assert card["scenario"]["pipelineId"] == "moving-pictures-16s-rulegraph-v1"
    assert card["workflowRevision"]["workflowRevisionId"] == "wfrev_first"
    assert card["workflowRevision"]["contentHash"] == "c" * 64
    software = card["softwareEnvironment"]
    assert software["schemaVersion"] == "h2ometa.first-run.software-environment.v1"
    assert software["status"] == "verified"
    assert software["workflowRevisionId"] == "wfrev_first"
    assert software["contentHash"] == "c" * 64
    assert software["compiler"] == {
        "name": "h2ometa-remote-runner-bundled-pipeline",
        "version": "1.0.0",
    }
    assert software["runtime"]["engine"] == "snakemake"
    assert software["runtime"]["pipelineVersion"] == "1.0.0"
    assert software["runtime"]["runtimeLockSha256"] == "9" * 64
    assert software["workflow"]["source"] == "remote-runner-pipeline-registry"
    assert software["workflow"]["sourceFileCount"] == 3
    assert [item["path"] for item in software["workflow"]["sourceFiles"]] == [
        "workflow/Snakefile",
        "workflow/envs/base.yaml",
        "workflow/scripts/render_report.py",
    ]
    assert card["result"]["resultId"] == "res_run_first"
    assert card["resultPackage"]["packageExportId"] == "rpex_full"
    assert card["resultPackage"]["artifactPayloadMode"] == "full"
    assert {item["code"] for item in card["checks"]} >= {
        "FIRST_RUN_PIPELINE_MATCH",
        "FIRST_RUN_COMPLETED",
        "FIRST_RUN_WORKFLOW_REVISION_PRESENT",
        "FIRST_RUN_SOFTWARE_ENVIRONMENT_VERIFIED",
        "FIRST_RUN_INPUT_LINEAGE_PRESENT",
        "FIRST_RUN_SAMPLE_INPUTS_VERIFIED",
        "FIRST_RUN_OUTPUT_CHECKSUMS_PRESENT",
        "FIRST_RUN_EXPECTED_OUTPUTS_PRESENT",
        "FIRST_RUN_REPORT_INTERPRETATION_READY",
        "FIRST_RUN_RESULT_PACKAGE_ACTIVE",
    }
    sample_data = card["sampleData"]
    assert sample_data["schemaVersion"] == "h2ometa.first-run.sample-data-evidence.v1"
    assert sample_data["status"] == "verified"
    assert [item["role"] for item in sample_data["items"]] == ["metadata", "barcodes", "sequences"]
    assert {item["role"]: item["integrityStatus"] for item in sample_data["items"]} == {
        "metadata": "passed",
        "barcodes": "passed",
        "sequences": "passed",
    }
    assert {item["role"]: item["sha256"] for item in sample_data["items"]} == {
        item.role: item.expected_sha256 for item in MOVING_PICTURES_FILES
    }
    interpretation = card["reportInterpretation"]
    assert interpretation["schemaVersion"] == "h2ometa.first-run.report-interpretation.v1"
    assert interpretation["status"] == "ready"
    assert [item["name"] for item in interpretation["outputs"]] == [
        "summary.tsv",
        "qc-summary.tsv",
        "feature-table.tsv",
        "run-report.html",
    ]
    assert {item["name"]: item["artifactId"] for item in interpretation["outputs"]} == {
        "summary.tsv": "art_summary",
        "qc-summary.tsv": "art_qc",
        "feature-table.tsv": "art_feature_table",
        "run-report.html": "art_report",
    }
    metrics = {item["metricId"]: item["value"] for item in interpretation["metrics"]}
    assert metrics["sample_count"] == 2
    assert metrics["passed_reads_total"] == 30
    assert metrics["unique_features_sample_sum"] == 7
    assert metrics["qc_total_pairs"] == 60
    assert metrics["qc_features"] == 7
    assert interpretation["redaction"] == {
        "rawPathsExposed": False,
        "storageUrisExposed": False,
        "previewRowsEmbedded": False,
        "policy": "metrics-only",
    }

    serialized = json.dumps(card, sort_keys=True)
    assert "C:/secret" not in serialized
    assert "s3://secret" not in serialized
    assert '"packagePath"' not in serialized
    assert '"storageUri"' not in serialized
    assert '"sourceStorageUri"' not in serialized


@pytest.mark.parametrize(
    ("run_patch", "expected_code"),
    [
        ({"pipelineId": "taxonomy-v1"}, "FIRST_RUN_PIPELINE_UNSUPPORTED"),
        ({"status": "failed"}, "FIRST_RUN_NOT_SUCCESSFUL"),
        ({"workflowRevisionId": ""}, "FIRST_RUN_WORKFLOW_REVISION_REQUIRED"),
    ],
)
def test_first_run_validation_card_rejects_invalid_run_state(
    monkeypatch,
    run_patch: dict[str, Any],
    expected_code: str,
) -> None:
    run = _run()
    run.update(run_patch)
    if run_patch.get("workflowRevisionId") == "":
        run["runSpec"]["workflowRevisionId"] = ""
    _patch_first_run_sources(monkeypatch, run=run)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match=expected_code):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


@pytest.mark.parametrize(
    ("revision_patch", "expected_code"),
    [
        ({"contentHash": ""}, "FIRST_RUN_WORKFLOW_REVISION_CONTENT_HASH_REQUIRED"),
        ({"runtimeLock": {}}, "FIRST_RUN_WORKFLOW_RUNTIME_LOCK_REQUIRED"),
        ({"manifest": {"files": []}}, "FIRST_RUN_WORKFLOW_SOURCE_FILES_REQUIRED"),
    ],
)
def test_first_run_validation_card_requires_workflow_revision_software_evidence(
    monkeypatch,
    revision_patch: dict[str, Any],
    expected_code: str,
) -> None:
    revision = _workflow_revision()
    revision.update(revision_patch)
    _patch_first_run_sources(monkeypatch, workflow_revision=revision)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match=expected_code):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


@pytest.mark.parametrize(
    ("export_case", "expected_code"),
    [
        ("none", "FIRST_RUN_RESULT_PACKAGE_REQUIRED"),
        ("metadata-only", "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"),
        ("no-download", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
        ("no-hash", "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED"),
    ],
)
def test_first_run_validation_card_requires_full_downloadable_hashed_package(
    monkeypatch,
    export_case: str,
    expected_code: str,
) -> None:
    _patch_first_run_sources(monkeypatch, exports=_exports_for_case(export_case))

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match=expected_code):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


@pytest.mark.parametrize(
    ("package_patch", "expected_code"),
    [
        ({"resultId": "res_other"}, "FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH"),
        ({"workflowRevisionId": "wfrev_other"}, "FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH"),
    ],
)
def test_first_run_validation_card_rejects_mismatched_result_package(
    monkeypatch,
    package_patch: dict[str, Any],
    expected_code: str,
) -> None:
    package = _package("rpex_full")
    package.update(package_patch)
    _patch_first_run_sources(monkeypatch, exports=[package])

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match=expected_code):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


@pytest.mark.parametrize(
    ("result_patch", "expected_code"),
    [
        ({"inputArtifacts": []}, "FIRST_RUN_INPUT_LINEAGE_REQUIRED"),
        ({"artifacts": []}, "FIRST_RUN_OUTPUT_ARTIFACTS_REQUIRED"),
    ],
)
def test_first_run_validation_card_requires_lineage_and_output_artifacts(
    monkeypatch,
    result_patch: dict[str, Any],
    expected_code: str,
) -> None:
    result = _result()
    result.update(result_patch)
    _patch_first_run_sources(monkeypatch, result=result)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match=expected_code):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_requires_expected_outputs(monkeypatch) -> None:
    result = _result()
    result["artifacts"] = [item for item in result["artifacts"] if item["artifactId"] != "art_feature_table"]
    _patch_first_run_sources(monkeypatch, result=result)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_requires_checksums_for_expected_outputs(monkeypatch) -> None:
    result = _result()
    result["artifacts"][0].pop("sha256")
    _patch_first_run_sources(monkeypatch, result=result)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_OUTPUT_CHECKSUMS_REQUIRED"):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_requires_official_sample_input_integrity(monkeypatch) -> None:
    result = _result()
    result["inputArtifacts"][1]["sha256"] = "0" * 64
    _patch_first_run_sources(monkeypatch, result=result)

    with pytest.raises(
        WorkflowFirstRunValidationCardUnavailableError,
        match="FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH",
    ):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_requires_all_official_sample_roles(monkeypatch) -> None:
    run = _run()
    run["runSpec"]["inputs"] = [item for item in run["runSpec"]["inputs"] if item["role"] != "sequences"]
    _patch_first_run_sources(monkeypatch, run=run)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_SAMPLE_INPUTS_REQUIRED"):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_requires_parseable_report_previews(monkeypatch) -> None:
    previews = _previews()
    previews["art_summary"]["preview"] = {"kind": "table", "columns": ["sample_id"], "rows": [["sample-a"]]}
    _patch_first_run_sources(monkeypatch, previews=previews)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_REPORT_PREVIEW_REQUIRED"):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_finalize_reuses_existing_full_package(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch)

    async def fail_export(*_args, **_kwargs):
        raise AssertionError("finalize must not export when validation card is already ready")

    monkeypatch.setattr("apps.api.workflow_first_run_finalize_service.export_result_package_from_request", fail_export)

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert result["schemaVersion"] == "h2ometa.first-run.finalization.v1"
    assert result["status"] == "ready"
    assert result["packageAction"] == "reused"
    assert result["resultPackage"]["packageExportId"] == "rpex_full"
    assert result["validationCard"]["checks"]


def test_first_run_finalize_exports_full_package_when_missing(monkeypatch) -> None:
    exports: list[dict[str, Any]] = []
    export_calls: list[tuple[str, bool, str | None, str | None]] = []
    _patch_first_run_sources(monkeypatch, exports=exports)

    async def fake_export(result_id: str, request) -> dict[str, Any]:
        export_calls.append((result_id, request.includeArtifacts, request.serverId, request.actor))
        package = _package("rpex_finalized")
        exports.append(package)
        return {"data": package}

    monkeypatch.setattr("apps.api.workflow_first_run_finalize_service.export_result_package_from_request", fake_export)

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first", actor="operator"),
        )
    )["data"]

    assert export_calls == [("res_run_first", True, "srv_first", "operator")]
    assert result["status"] == "ready"
    assert result["packageAction"] == "exported"
    assert result["resultPackage"]["packageExportId"] == "rpex_finalized"
    assert result["validationCard"]["resultPackage"]["packageExportId"] == "rpex_finalized"


def test_first_run_finalize_returns_typed_blocked_action(monkeypatch) -> None:
    run = _run()
    run["status"] = "failed"
    _patch_first_run_sources(monkeypatch, run=run)

    async def fail_export(*_args, **_kwargs):
        raise AssertionError("finalize must not export before a successful first run")

    monkeypatch.setattr("apps.api.workflow_first_run_finalize_service.export_result_package_from_request", fail_export)

    result = asyncio.run(
        finalize_first_run_from_request(
            "run_first",
            WorkflowFirstRunFinalizeRequest(serverId="srv_first"),
        )
    )["data"]

    assert result == {
        "schemaVersion": "h2ometa.first-run.finalization.v1",
        "status": "blocked",
        "nextAction": {
            "code": "FIRST_RUN_NOT_SUCCESSFUL",
            "detail": "FIRST_RUN_NOT_SUCCESSFUL: run status is failed",
            "label": "等待首跑成功完成",
            "target": "/workflows/first-run#run-report",
        },
    }


def test_first_run_validation_card_route_and_error_handler_are_registered() -> None:
    route_source = _source("apps/api/workflow_first_run_routes.py")
    finalize_source = _source("apps/api/workflow_first_run_finalize_service.py")
    service_source = _source("apps/api/workflow_first_run_service.py")
    main_source = _source("apps/api/main.py")
    route_errors = _source("apps/api/route_errors.py")

    assert '@router.get("/api/v1/first-run/runs/{run_id}/validation-card")' in route_source
    assert '@router.post("/api/v1/first-run/runs/{run_id}/finalize")' in route_source
    assert "build_first_run_validation_card_from_request" in route_source
    assert "finalize_first_run_from_request" in route_source
    assert "FIRST_RUN_FINALIZATION_SCHEMA_VERSION" in finalize_source
    assert "export_result_package_from_request" in finalize_source
    assert "ResultPackageExportRequest(" in finalize_source
    assert "includeArtifacts=True" in finalize_source
    assert "workflow_first_run_router" in main_source
    assert "WorkflowFirstRunValidationCardUnavailableError(ValueError):\n    status_code = 409" in service_source
    assert "WorkflowFirstRunValidationCardUnavailableError" in route_errors
    assert "status_detail_response(exc)" in route_errors


def _patch_first_run_sources(
    monkeypatch,
    *,
    calls: list[tuple[str, str | None]] | None = None,
    exports: list[dict[str, Any]] | None = None,
    previews: dict[str, dict[str, Any]] | None = None,
    result: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
    workflow_revision: dict[str, Any] | None = None,
) -> None:
    async def fake_get_run(run_id: str) -> dict[str, Any]:
        assert run_id == "run_first"
        return {"data": run if run is not None else _run()}

    async def fake_get_result(result_id: str) -> dict[str, Any]:
        assert result_id == "res_run_first"
        return {"data": result if result is not None else _result()}

    async def fake_get_workflow_revision(
        workflow_revision_id: str,
        *,
        server_id: str | None = None,
    ) -> dict[str, Any]:
        assert workflow_revision_id == "wfrev_first"
        if calls is not None:
            calls.append(("revision", server_id))
        return {"data": workflow_revision if workflow_revision is not None else _workflow_revision()}

    async def fake_get_preview(result_id: str, *, artifact_id: str | None) -> dict[str, Any]:
        assert result_id == "res_run_first"
        assert artifact_id is not None
        if calls is not None:
            calls.append(("preview", artifact_id))
        preview_map = previews if previews is not None else _previews()
        return {"data": preview_map[artifact_id]}

    async def fake_list_exports(
        result_id: str,
        *,
        server_id: str | None = None,
        lifecycle_state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        assert result_id == "res_run_first"
        assert lifecycle_state == "active"
        assert limit == 25
        if calls is not None:
            calls.append(("exports", server_id))
        return {"data": {"items": exports if exports is not None else _exports()}}

    monkeypatch.setattr("apps.api.workflow_first_run_service.get_run_from_request", fake_get_run)
    monkeypatch.setattr("apps.api.workflow_first_run_service.get_result_from_request", fake_get_result)
    monkeypatch.setattr("apps.api.workflow_first_run_service.get_workflow_revision_from_request", fake_get_workflow_revision)
    monkeypatch.setattr("apps.api.workflow_first_run_service.get_result_preview_from_request", fake_get_preview)
    monkeypatch.setattr("apps.api.workflow_first_run_service.list_result_package_exports_from_request", fake_list_exports)
    monkeypatch.setattr("apps.api.workflow_first_run_service._utc_now", lambda: "2026-06-29T00:00:00Z")


def _run() -> dict[str, Any]:
    return {
        "runId": "run_first",
        "pipelineId": "moving-pictures-16s-rulegraph-v1",
        "workflowRevisionId": "wfrev_first",
        "status": "completed",
        "stage": "completed",
        "startedAt": "2026-06-29T00:00:00Z",
        "finishedAt": "2026-06-29T00:20:00Z",
        "runSpec": {
            "pipelineId": "moving-pictures-16s-rulegraph-v1",
            "workflowRevisionId": "wfrev_first",
            "inputs": [
                {"role": "metadata", "filename": "sample-metadata.tsv", "uploadId": "upl_metadata"},
                {"role": "barcodes", "filename": "barcodes.fastq.gz", "uploadId": "upl_barcodes"},
                {"role": "sequences", "filename": "sequences.fastq.gz", "uploadId": "upl_sequences"},
            ],
        },
    }


def _workflow_revision() -> dict[str, Any]:
    return {
        "workflowRevisionId": "wfrev_first",
        "contentHash": "c" * 64,
        "runtimeLockSha256": "9" * 64,
        "manifest": {
            "schemaVersion": "bundled-pipeline-workflow-revision-manifest.v1",
            "pipelineId": "moving-pictures-16s-rulegraph-v1",
            "pipelineVersion": "1.0.0",
            "source": "remote-runner-pipeline-registry",
            "snakefile": "workflow/Snakefile",
            "files": [
                {"path": "workflow/Snakefile", "sha256": "1" * 64},
                {"path": "workflow/envs/base.yaml", "sha256": "2" * 64},
                {"path": "workflow/scripts/render_report.py", "sha256": "3" * 64},
            ],
        },
        "runtimeLock": {
            "schemaVersion": "bundled-pipeline-runtime-lock.v1",
            "engine": "snakemake",
            "pipelineId": "moving-pictures-16s-rulegraph-v1",
            "pipelineVersion": "1.0.0",
        },
        "compiler": {
            "name": "h2ometa-remote-runner-bundled-pipeline",
            "version": "1.0.0",
        },
    }


def _result() -> dict[str, Any]:
    return {
        "resultId": "res_run_first",
        "runId": "run_first",
        "resultDir": "C:/secret/results",
        "artifacts": [
            {
                "artifactId": "art_summary",
                "artifactKey": "summary",
                "kind": "table",
                "mimeType": "text/tab-separated-values",
                "path": "C:/secret/results/summary.tsv",
                "storageUri": "file:///secret/results/summary.tsv",
                "sizeBytes": 128,
                "sha256": "a" * 64,
            },
            {
                "artifactId": "art_qc",
                "artifactKey": "qc_summary",
                "kind": "table",
                "mimeType": "text/tab-separated-values",
                "path": "C:/secret/results/qc-summary.tsv",
                "storageUri": "file:///secret/results/qc-summary.tsv",
                "sizeBytes": 96,
                "sha256": "f" * 64,
            },
            {
                "artifactId": "art_feature_table",
                "artifactKey": "feature_table",
                "kind": "table",
                "mimeType": "text/tab-separated-values",
                "path": "C:/secret/results/feature-table.tsv",
                "storageUri": "file:///secret/results/feature-table.tsv",
                "sizeBytes": 512,
                "sha256": "1" * 64,
            },
            {
                "artifactId": "art_report",
                "artifactKey": "report",
                "kind": "report",
                "mimeType": "text/html",
                "path": "C:/secret/results/run-report.html",
                "storageUri": "file:///secret/results/run-report.html",
                "sizeBytes": 1024,
                "sha256": "b" * 64,
            },
        ],
        "inputArtifacts": [
            _input_artifact("metadata", "sample-metadata.tsv", "upl_metadata", "text/tab-separated-values"),
            _input_artifact("barcodes", "barcodes.fastq.gz", "upl_barcodes", "application/gzip"),
            _input_artifact("sequences", "sequences.fastq.gz", "upl_sequences", "application/gzip"),
        ],
        "lineageSummary": {
            "schemaVersion": "h2ometa.result-lineage-summary.v1",
            "edgeCount": 7,
            "inputEdgeCount": 3,
            "outputEdgeCount": 4,
            "predicateCounts": {"prov:generated": 4, "prov:used": 3},
        },
    }


def _input_artifact(role: str, filename: str, upload_id: str, mime_type: str) -> dict[str, Any]:
    expected = _expected_sample(role)
    return {
        "artifactBlobId": f"blob_{role}",
        "sha256": expected.expected_sha256,
        "mimeType": mime_type,
        "sizeBytes": expected.expected_size_bytes,
        "sourceStorageUri": f"s3://secret/{filename}",
        "ports": [
            {
                "portName": role,
                "inputRole": role,
                "inputIndex": ["metadata", "barcodes", "sequences"].index(role),
                "sourceType": "upload",
                "sourceId": upload_id,
                "filename": filename,
                "uploadId": upload_id,
                "storageUri": f"file:///secret/{filename}",
            }
        ],
    }


def _expected_sample(role: str):
    return next(item for item in MOVING_PICTURES_FILES if item.role == role)


def _previews() -> dict[str, dict[str, Any]]:
    return {
        "art_summary": {
            "resultId": "res_run_first",
            "artifactId": "art_summary",
            "artifact": {
                "artifactId": "art_summary",
                "artifactKey": "summary",
                "path": "C:/secret/results/summary.tsv",
                "storageUri": "s3://secret/results/summary.tsv",
            },
            "preview": {
                "kind": "table",
                "columns": [
                    "sample_id",
                    "barcode",
                    "body_site",
                    "subject",
                    "matched_reads",
                    "passed_reads",
                    "unique_features",
                ],
                "rows": [
                    ["sample-a", "AAAA", "gut", "subject-1", "40", "20", "4"],
                    ["sample-b", "BBBB", "skin", "subject-2", "20", "10", "3"],
                ],
                "truncated": False,
            },
        },
        "art_qc": {
            "resultId": "res_run_first",
            "artifactId": "art_qc",
            "artifact": {
                "artifactId": "art_qc",
                "artifactKey": "qc_summary",
                "path": "C:/secret/results/qc-summary.tsv",
                "storageUri": "s3://secret/results/qc-summary.tsv",
            },
            "preview": {
                "kind": "table",
                "columns": ["metric", "value"],
                "rows": [
                    ["total_pairs", "60"],
                    ["matched_reads", "60"],
                    ["passed_reads", "30"],
                    ["unmatched_barcodes", "0"],
                    ["samples_with_reads", "2"],
                    ["features", "7"],
                ],
                "truncated": False,
            },
        },
    }


def _exports() -> list[dict[str, Any]]:
    return [
        _package("rpex_metadata", artifact_payload_mode="metadata-only", include_artifacts=False),
        _package("rpex_full"),
    ]


def _exports_for_case(export_case: str) -> list[dict[str, Any]]:
    if export_case == "none":
        return []
    if export_case == "metadata-only":
        return [_package("rpex_metadata", artifact_payload_mode="metadata-only", include_artifacts=False)]
    if export_case == "no-download":
        return [_package("rpex_no_download", download=False)]
    if export_case == "no-hash":
        return [_package("rpex_no_hash", sha256="", manifest_sha256="")]
    raise AssertionError(f"unknown export case: {export_case}")


def _package(
    package_export_id: str,
    *,
    artifact_payload_mode: str = "full",
    download: bool = True,
    include_artifacts: bool = True,
    manifest_sha256: str = "e" * 64,
    sha256: str = "d" * 64,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "packageExportId": package_export_id,
        "resultId": "res_run_first",
        "runId": "run_first",
        "workflowRevisionId": "wfrev_first",
        "lifecycleState": "active",
        "packageBytesState": "available",
        "artifactPayloadMode": artifact_payload_mode,
        "includeArtifacts": include_artifacts,
        "sizeBytes": 4096,
        "sha256": sha256,
        "manifestSha256": manifest_sha256,
        "evidenceId": "ev_export",
        "packagePath": "C:/secret/packages/result.zip",
    }
    if download:
        item["download"] = {
            "href": "/api/v1/results/res_run_first/exports/rpex_full/download",
            "filename": "rpex_full.zip",
        }
    return item


def _source(path: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
