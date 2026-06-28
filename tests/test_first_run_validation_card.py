from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_validation_card_from_request,
)


def test_first_run_validation_card_is_server_generated_and_redacted(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []
    _patch_first_run_sources(monkeypatch, calls=calls)

    card = asyncio.run(
        build_first_run_validation_card_from_request(
            "run_first",
            server_id="srv_first",
        )
    )["data"]

    assert calls == [("exports", "srv_first")]
    assert card["schemaVersion"] == "h2ometa.first-run.validation-card.v1"
    assert card["generatedAt"] == "2026-06-29T00:00:00Z"
    assert card["scenario"]["pipelineId"] == "moving-pictures-16s-rulegraph-v1"
    assert card["workflowRevision"]["workflowRevisionId"] == "wfrev_first"
    assert card["result"]["resultId"] == "res_run_first"
    assert card["resultPackage"]["packageExportId"] == "rpex_full"
    assert card["resultPackage"]["artifactPayloadMode"] == "full"
    assert {item["code"] for item in card["checks"]} >= {
        "FIRST_RUN_PIPELINE_MATCH",
        "FIRST_RUN_COMPLETED",
        "FIRST_RUN_WORKFLOW_REVISION_PRESENT",
        "FIRST_RUN_INPUT_LINEAGE_PRESENT",
        "FIRST_RUN_OUTPUT_CHECKSUMS_PRESENT",
        "FIRST_RUN_RESULT_PACKAGE_ACTIVE",
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
        ({"artifacts": [{"artifactId": "art_summary", "artifactKey": "summary.tsv"}]}, "FIRST_RUN_OUTPUT_CHECKSUMS_REQUIRED"),
    ],
)
def test_first_run_validation_card_requires_lineage_and_output_checksums(
    monkeypatch,
    result_patch: dict[str, Any],
    expected_code: str,
) -> None:
    result = _result()
    result.update(result_patch)
    _patch_first_run_sources(monkeypatch, result=result)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match=expected_code):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_route_and_error_handler_are_registered() -> None:
    route_source = _source("apps/api/workflow_first_run_routes.py")
    service_source = _source("apps/api/workflow_first_run_service.py")
    main_source = _source("apps/api/main.py")
    route_errors = _source("apps/api/route_errors.py")

    assert '@router.get("/api/v1/first-run/runs/{run_id}/validation-card")' in route_source
    assert "build_first_run_validation_card_from_request" in route_source
    assert "workflow_first_run_router" in main_source
    assert "WorkflowFirstRunValidationCardUnavailableError(ValueError):\n    status_code = 409" in service_source
    assert "WorkflowFirstRunValidationCardUnavailableError" in route_errors
    assert "status_detail_response(exc)" in route_errors


def _patch_first_run_sources(
    monkeypatch,
    *,
    calls: list[tuple[str, str | None]] | None = None,
    exports: list[dict[str, Any]] | None = None,
    result: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
) -> None:
    async def fake_get_run(run_id: str) -> dict[str, Any]:
        assert run_id == "run_first"
        return {"data": run if run is not None else _run()}

    async def fake_get_result(result_id: str) -> dict[str, Any]:
        assert result_id == "res_run_first"
        return {"data": result if result is not None else _result()}

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


def _result() -> dict[str, Any]:
    return {
        "resultId": "res_run_first",
        "runId": "run_first",
        "resultDir": "C:/secret/results",
        "artifacts": [
            {
                "artifactId": "art_summary",
                "artifactKey": "summary.tsv",
                "kind": "table",
                "mimeType": "text/tab-separated-values",
                "path": "C:/secret/results/summary.tsv",
                "storageUri": "file:///secret/results/summary.tsv",
                "sizeBytes": 128,
                "sha256": "a" * 64,
            },
            {
                "artifactId": "art_report",
                "artifactKey": "run-report.html",
                "kind": "report",
                "mimeType": "text/html",
                "sizeBytes": 1024,
                "sha256": "b" * 64,
            },
        ],
        "inputArtifacts": [
            {
                "artifactBlobId": "blob_metadata",
                "sha256": "c" * 64,
                "mimeType": "text/tab-separated-values",
                "sizeBytes": 256,
                "sourceStorageUri": "s3://secret/sample-metadata.tsv",
                "ports": [
                    {
                        "portName": "metadata",
                        "inputRole": "metadata",
                        "inputIndex": 0,
                        "sourceType": "upload",
                        "sourceId": "upl_metadata",
                        "filename": "sample-metadata.tsv",
                        "uploadId": "upl_metadata",
                        "storageUri": "file:///secret/sample-metadata.tsv",
                    }
                ],
            }
        ],
        "lineageSummary": {
            "schemaVersion": "h2ometa.result-lineage-summary.v1",
            "edgeCount": 3,
            "inputEdgeCount": 1,
            "outputEdgeCount": 2,
            "predicateCounts": {"prov:generated": 2, "prov:used": 1},
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
