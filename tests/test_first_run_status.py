from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from apps.api.workflow_sample_data_service import MOVING_PICTURES_PIPELINE_ID

from tests.test_first_run_validation_card import (
    _exports_for_case,
    _package,
    _patch_first_run_sources,
    _previews_for_trust_case,
    _result,
    _run,
)


def test_first_run_status_reports_ready_official_sample_run_and_ignores_newer_noneligible_run(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch)
    _patch_status_sources(
        monkeypatch,
        runs=[
            {**_run(), "lastUpdatedAt": "2026-06-29T00:20:00Z"},
            _noneligible_run("run_manual", last_updated_at="2026-06-29T00:25:00Z"),
        ],
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first", refresh=True))["data"]

    assert result["schemaVersion"] == "h2ometa.first-run.status.v1"
    assert result["scenario"]["pipelineId"] == MOVING_PICTURES_PIPELINE_ID
    assert result["scenario"]["expectedSampleRoles"] == ["metadata", "barcodes", "sequences"]
    assert result["serverId"] == "srv_first"
    assert result["status"] == "ready"
    assert result["stage"] == "validation_ready"
    assert result["nextAction"]["code"] == "COMPLETE"
    assert result["latestEligibleRun"]["runId"] == "run_first"
    assert result["ignoredLatestRun"]["runId"] == "run_manual"
    assert result["ignoredLatestRun"]["blockingCode"] == "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
    assert result["evidence"]["sampleCache"]["status"] == "ready"
    assert result["evidence"]["server"]["ready"] is True
    assert result["evidence"]["execution"]["ready"] is True
    assert result["evidence"]["workflow"]["ready"] is True
    assert result["evidence"]["workflow"]["pipelineId"] == MOVING_PICTURES_PIPELINE_ID
    assert result["evidence"]["run"]["runId"] == "run_first"
    assert result["evidence"]["report"]["ready"] is True
    assert result["evidence"]["report"]["outputs"] == [
        "summary.tsv",
        "qc-summary.tsv",
        "feature-table.tsv",
        "run-report.html",
    ]
    assert {item["metricId"]: item["value"] for item in result["evidence"]["report"]["metrics"]} == {
        "sample_count": 2,
        "passed_reads_total": 30,
        "unique_features_sample_sum": 7,
        "qc_total_pairs": 60,
        "qc_matched_reads": 60,
        "qc_passed_reads": 30,
        "qc_samples_with_reads": 2,
        "qc_features": 7,
    }
    assert result["evidence"]["resultPackage"]["ready"] is True
    assert result["evidence"]["resultPackage"]["packageExportId"] == "rpex_full"
    assert result["evidence"]["resultPackage"]["sha256"] == "d" * 64
    assert result["evidence"]["resultPackage"]["manifestSha256"] == "e" * 64
    assert result["evidence"]["resultPackage"]["artifactPayloadMode"] == "full"
    assert result["evidence"]["resultPackage"]["includeArtifacts"] is True
    assert result["evidence"]["validation"]["ready"] is True
    assert result["evidence"]["validation"]["validationChecksPassed"] == 10
    assert result["evidence"]["validation"]["evidenceBundleReady"] is True
    assert result["evidence"]["validation"]["evidenceBundleId"] == "res_run_first.first-run-evidence"


def test_first_run_status_blocks_until_official_sample_run_exists(monkeypatch) -> None:
    async def fail_validation_card(*_args, **_kwargs):
        raise AssertionError("status must not build a validation card without an eligible official sample run")

    _patch_status_sources(monkeypatch, runs=[_noneligible_run("run_manual")], sample_status="source_required")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.build_first_run_validation_card_from_request",
        fail_validation_card,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "prepare_sample_data"
    assert result["nextAction"] == {
        "code": "PREPARE_SAMPLE_DATA",
        "detail": "准备并上传官方 Moving Pictures 16S 样例数据。",
        "label": "准备示例数据",
        "target": "#sample-data",
    }
    assert result["latestEligibleRun"] is None
    assert result["ignoredLatestRun"]["runId"] == "run_manual"
    assert result["evidence"]["sampleCache"]["status"] == "source_required"


def test_first_run_status_guides_submit_when_sample_cache_ready_without_eligible_run(monkeypatch) -> None:
    async def fail_validation_card(*_args, **_kwargs):
        raise AssertionError("status must not build a validation card before a first-run submission exists")

    _patch_status_sources(monkeypatch, runs=[], sample_status="ready")
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.build_first_run_validation_card_from_request",
        fail_validation_card,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "submit_run"
    assert result["nextAction"] == {
        "code": "SUBMIT_RUN",
        "detail": "官方 Moving Pictures 16S 样例数据已就绪，提交首跑运行。",
        "label": "提交运行",
        "target": "#sample-data",
    }
    assert result["latestEligibleRun"] is None
    assert result["ignoredLatestRun"] is None
    assert result["evidence"]["sampleCache"]["status"] == "ready"
    assert result["evidence"]["sampleCache"]["verifiedCacheCount"] == 3
    assert result["evidence"]["server"]["ready"] is True
    assert result["evidence"]["execution"]["ready"] is True
    assert result["evidence"]["workflow"]["ready"] is True
    assert result["evidence"]["run"] is None


def test_first_run_status_blocks_stale_server_before_remote_run_queries(monkeypatch) -> None:
    async def fail_list_runs(*_args, **_kwargs):
        raise AssertionError("status must not list runs before a selected server is found")

    async def fail_validation_card(*_args, **_kwargs):
        raise AssertionError("status must not build a validation card before runner readiness passes")

    _patch_status_sources(monkeypatch, runs=[], servers=[])
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fail_list_runs)
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.build_first_run_validation_card_from_request",
        fail_validation_card,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_missing"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "connect_remote"
    assert result["nextAction"]["code"] == "CONNECT_REMOTE"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_SERVER_NOT_FOUND"
    assert result["evidence"]["server"] == {
        "ready": False,
        "serverId": "srv_missing",
        "connected": False,
        "runnerReady": False,
        "blockedCode": "FIRST_RUN_SERVER_NOT_FOUND",
    }
    assert result["evidence"]["execution"] == {"ready": False, "blockedCode": "FIRST_RUN_SERVER_NOT_FOUND"}
    assert result["latestEligibleRun"] is None


def test_first_run_status_blocks_disconnected_server_before_remote_run_queries(monkeypatch) -> None:
    async def fail_list_runs(*_args, **_kwargs):
        raise AssertionError("status must not list runs before SSH is connected")

    _patch_status_sources(monkeypatch, runs=[], server=_server(connected=False, ready=False))
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fail_list_runs)

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "connect_remote"
    assert result["nextAction"]["code"] == "CONNECT_REMOTE"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_SERVER_NOT_CONNECTED"
    assert result["evidence"]["server"]["connected"] is False
    assert result["evidence"]["server"]["blockedCode"] == "FIRST_RUN_SERVER_NOT_CONNECTED"
    assert result["evidence"]["execution"] == {"ready": False, "blockedCode": "FIRST_RUN_SERVER_NOT_CONNECTED"}


def test_first_run_status_blocks_runner_not_ready_before_remote_run_queries(monkeypatch) -> None:
    async def fail_list_runs(*_args, **_kwargs):
        raise AssertionError("status must not list runs before runner readiness passes")

    _patch_status_sources(
        monkeypatch,
        runs=[],
        server=_server(ready=False, reason_code="PIPELINE_REGISTRY_NOT_READY", message="Pipeline registry is not ready."),
    )
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fail_list_runs)

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "runner_readiness"
    assert result["nextAction"]["code"] == "ENSURE_RUNNER"
    assert result["nextAction"]["blockedCode"] == "PIPELINE_REGISTRY_NOT_READY"
    assert result["nextAction"]["detail"] == "Pipeline registry is not ready."
    assert result["evidence"]["server"]["ready"] is False
    assert result["evidence"]["server"]["runnerReady"] is False
    assert result["evidence"]["execution"] == {"ready": False, "blockedCode": "PIPELINE_REGISTRY_NOT_READY"}


def test_first_run_status_blocks_when_moving_pictures_workflow_is_not_ready(monkeypatch) -> None:
    async def fail_list_runs(*_args, **_kwargs):
        raise AssertionError("status must not list runs before the first-run workflow is WorkflowReady")

    _patch_status_sources(
        monkeypatch,
        runs=[],
        workflow={"id": MOVING_PICTURES_PIPELINE_ID, "name": "Moving Pictures 16S", "runnable": False, "status": "Validation template"},
    )
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fail_list_runs)

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "select_example"
    assert result["nextAction"]["code"] == "REFRESH_WORKFLOW"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_WORKFLOW_NOT_READY"
    assert result["evidence"]["server"]["ready"] is True
    assert result["evidence"]["execution"]["ready"] is True
    assert result["evidence"]["workflow"]["ready"] is False
    assert result["evidence"]["workflow"]["blockedCode"] == "FIRST_RUN_WORKFLOW_NOT_READY"


def test_first_run_status_blocks_execution_diagnostics_not_ready_before_run_actions(monkeypatch) -> None:
    async def fail_validation_card(*_args, **_kwargs):
        raise AssertionError("status must not build a validation card when execution diagnostics is blocked")

    _patch_status_sources(
        monkeypatch,
        runs=[_run()],
        execution_diagnostics={
            "schemaVersion": "execution-diagnostics.v1",
            "readiness": {
                "ok": False,
                "status": "blocked",
                "reasonCode": "WORKFLOW_EXECUTION_ADMISSION_BLOCKED",
                "blockingReasons": [
                    {
                        "code": "WORKFLOW_EXECUTION_ADMISSION_BLOCKED",
                        "message": "worker lease table is unavailable",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.build_first_run_validation_card_from_request",
        fail_validation_card,
    )

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "runner_readiness"
    assert result["nextAction"]["code"] == "ENSURE_RUNNER"
    assert result["nextAction"]["blockedCode"] == "WORKFLOW_EXECUTION_ADMISSION_BLOCKED"
    assert result["nextAction"]["detail"] == "execution diagnostics 未通过：worker lease table is unavailable"
    assert result["evidence"]["server"]["ready"] is True
    assert result["evidence"]["execution"]["ready"] is False
    assert result["evidence"]["execution"]["blockingReasons"] == [
        {
            "code": "WORKFLOW_EXECUTION_ADMISSION_BLOCKED",
            "message": "worker lease table is unavailable",
        }
    ]


def test_first_run_status_blocks_invalid_execution_diagnostics_schema(monkeypatch) -> None:
    async def fail_list_runs(*_args, **_kwargs):
        raise AssertionError("status must not list runs with an invalid diagnostics contract")

    _patch_status_sources(
        monkeypatch,
        runs=[],
        execution_diagnostics={
            "schemaVersion": "workflow-execution-diagnostics.v1",
            "readiness": {
                "ok": True,
                "status": "ready",
            },
        },
    )
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fail_list_runs)

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "runner_readiness"
    assert result["nextAction"]["code"] == "ENSURE_RUNNER"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_EXECUTION_DIAGNOSTICS_SCHEMA_INVALID"
    assert result["evidence"]["execution"] == {
        "ready": False,
        "blockedCode": "FIRST_RUN_EXECUTION_DIAGNOSTICS_SCHEMA_INVALID",
        "detail": "execution diagnostics response must use execution-diagnostics.v1.",
    }


def test_first_run_status_uses_validation_card_standard_for_report_readiness(monkeypatch) -> None:
    result_payload = _result()
    result_payload["artifacts"] = [
        item for item in result_payload["artifacts"] if item["artifactId"] != "art_feature_table"
    ]
    _patch_first_run_sources(monkeypatch, result=result_payload)
    _patch_status_sources(monkeypatch, runs=[_run()])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "inspect_failed_run"
    assert result["nextAction"]["code"] == "INSPECT_FAILED_RUN"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"
    assert result["nextAction"]["target"] == "#run-report"
    assert result["evidence"]["validation"]["ready"] is False
    assert result["evidence"]["validation"]["blockedCode"] == "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"
    assert result["evidence"]["report"] == {"ready": False, "blockedCode": "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"}
    assert result["evidence"]["resultPackage"] == {"ready": False}


def test_first_run_status_blocks_when_report_trust_assertions_fail(monkeypatch) -> None:
    _patch_first_run_sources(monkeypatch, previews=_previews_for_trust_case("qc_features_mismatch"))
    _patch_status_sources(monkeypatch, runs=[_run()])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "inspect_failed_run"
    assert result["nextAction"]["code"] == "INSPECT_FAILED_RUN"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED"
    assert result["nextAction"]["target"] == "#run-report"
    assert result["evidence"]["validation"]["ready"] is False
    assert result["evidence"]["validation"]["blockedCode"] == "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED"
    assert result["evidence"]["report"] == {
        "ready": False,
        "blockedCode": "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED",
    }
    assert result["evidence"]["resultPackage"] == {"ready": False}


@pytest.mark.parametrize(
    ("export_case", "expected_code"),
    [
        ("none", "FIRST_RUN_RESULT_PACKAGE_REQUIRED"),
        ("metadata-only", "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"),
        ("no-download", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
        ("no-hash", "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED"),
    ],
)
def test_first_run_status_uses_validation_card_standard_for_result_package_readiness(
    monkeypatch,
    export_case: str,
    expected_code: str,
) -> None:
    _patch_first_run_sources(monkeypatch, exports=_exports_for_case(export_case))
    _patch_status_sources(monkeypatch, runs=[_run()])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "export_result_package"
    assert result["nextAction"]["code"] == "FINALIZE_FIRST_RUN"
    assert result["nextAction"]["blockedCode"] == expected_code
    assert result["nextAction"]["target"] == "#result-package"
    assert result["evidence"]["report"]["ready"] is True
    assert result["evidence"]["report"]["outputs"] == [
        "summary.tsv",
        "qc-summary.tsv",
        "feature-table.tsv",
        "run-report.html",
    ]
    assert {item["metricId"]: item["value"] for item in result["evidence"]["report"]["metrics"]}["passed_reads_total"] == 30
    assert result["evidence"]["resultPackage"] == {"ready": False, "blockedCode": expected_code}
    assert result["evidence"]["validation"]["ready"] is False
    assert result["evidence"]["validation"]["blockedCode"] == expected_code


def test_first_run_status_prioritizes_report_trust_before_result_package_export(monkeypatch) -> None:
    _patch_first_run_sources(
        monkeypatch,
        exports=_exports_for_case("none"),
        previews=_previews_for_trust_case("qc_features_mismatch"),
    )
    _patch_status_sources(monkeypatch, runs=[_run()])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "inspect_failed_run"
    assert result["nextAction"]["code"] == "INSPECT_FAILED_RUN"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED"
    assert result["nextAction"]["target"] == "#run-report"
    assert result["evidence"]["report"] == {
        "ready": False,
        "blockedCode": "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED",
    }
    assert result["evidence"]["resultPackage"] == {"ready": False}
    assert result["evidence"]["validation"]["blockedCode"] == "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED"


@pytest.mark.parametrize(
    ("package_patch", "expected_code"),
    [
        ({"resultId": "res_other"}, "FIRST_RUN_RESULT_PACKAGE_RESULT_MISMATCH"),
        ({"workflowRevisionId": "wfrev_other"}, "FIRST_RUN_RESULT_PACKAGE_REVISION_MISMATCH"),
    ],
)
def test_first_run_status_blocks_package_ledger_mismatch_without_finalize_action(
    monkeypatch,
    package_patch: dict[str, Any],
    expected_code: str,
) -> None:
    package = _package("rpex_wrong")
    package.update(package_patch)
    _patch_first_run_sources(monkeypatch, exports=[package])
    _patch_status_sources(monkeypatch, runs=[_run()])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "export_result_package"
    assert result["nextAction"]["code"] == "REFRESH_RUN"
    assert result["nextAction"]["blockedCode"] == expected_code
    assert result["nextAction"]["label"] == "检查结果包账本"
    assert result["nextAction"]["target"] == "#result-package"
    assert result["evidence"]["resultPackage"] == {"ready": False, "blockedCode": expected_code}
    assert result["evidence"]["validation"]["blockedCode"] == expected_code


def test_first_run_status_requires_connection_before_guiding_run_actions(monkeypatch) -> None:
    _patch_status_sources(monkeypatch, runs=[_run()])

    result = asyncio.run(build_first_run_status_from_request())["data"]

    assert result["status"] == "blocked"
    assert result["stage"] == "connect_remote"
    assert result["nextAction"]["code"] == "CONNECT_REMOTE"
    assert result["nextAction"]["blockedCode"] == "FIRST_RUN_SERVER_REQUIRED"
    assert result["nextAction"]["target"] == "#runner-readiness"
    assert result["evidence"]["server"]["blockedCode"] == "FIRST_RUN_SERVER_REQUIRED"
    assert result["evidence"]["execution"]["blockedCode"] == "FIRST_RUN_SERVER_REQUIRED"
    assert result["evidence"]["workflow"]["blockedCode"] == "FIRST_RUN_SERVER_REQUIRED"


def test_first_run_status_requires_run_spec_pipeline_and_upload_backed_sample_inputs(monkeypatch) -> None:
    run = _run()
    run["pipelineId"] = MOVING_PICTURES_PIPELINE_ID
    run["runSpec"]["pipelineId"] = "manual-moving-pictures-run"
    _patch_status_sources(monkeypatch, runs=[run])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["latestEligibleRun"] is None
    assert result["ignoredLatestRun"]["blockingCode"] == "FIRST_RUN_PIPELINE_UNSUPPORTED"

    run = _run()
    run["runSpec"]["inputs"][0].pop("uploadId")
    _patch_status_sources(monkeypatch, runs=[run])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["latestEligibleRun"] is None
    assert result["ignoredLatestRun"]["blockingCode"] == "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"


def test_first_run_status_rejects_non_strict_official_sample_prep_proof(monkeypatch) -> None:
    proof_cases = [
        ("schemaVersion", "wrong-schema"),
        ("sourceUrl", "https://example.test/not-official.tsv"),
        ("expectedSizeBytes", 0),
        ("cacheStatus", "unknown"),
        ("downloadStatus", "unknown"),
    ]
    for field, value in proof_cases:
        run = _run()
        run["runSpec"]["sampleDataPrepProof"]["items"][0][field] = value
        _patch_status_sources(monkeypatch, runs=[run])

        result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

        assert result["status"] == "blocked"
        assert result["latestEligibleRun"] is None
        assert result["ignoredLatestRun"]["blockingCode"] == "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"


def test_first_run_status_rejects_duplicate_or_extra_sample_roles(monkeypatch) -> None:
    run = _run()
    run["runSpec"]["sampleDataPrepProof"]["items"][1]["role"] = "metadata"
    _patch_status_sources(monkeypatch, runs=[run])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["latestEligibleRun"] is None
    assert result["ignoredLatestRun"]["blockingCode"] == "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"

    run = _run()
    run["runSpec"]["inputs"].append({"role": "extra", "filename": "extra.tsv", "uploadId": "upl_extra"})
    _patch_status_sources(monkeypatch, runs=[run])

    result = asyncio.run(build_first_run_status_from_request(server_id="srv_first"))["data"]

    assert result["status"] == "blocked"
    assert result["latestEligibleRun"] is None
    assert result["ignoredLatestRun"]["blockingCode"] == "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"


def test_first_run_status_route_and_service_are_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    route_source = (root / "apps" / "api" / "workflow_first_run_routes.py").read_text(encoding="utf-8")
    service_source = (root / "apps" / "api" / "workflow_first_run_status_service.py").read_text(encoding="utf-8")
    finalize_source = (root / "apps" / "api" / "workflow_first_run_finalize_service.py").read_text(encoding="utf-8")

    assert '@router.get("/api/v1/first-run/status")' in route_source
    assert "build_first_run_status_from_request" in route_source
    assert "runId: str | None = None" in route_source
    assert "run_id=runId" in route_source
    assert "FIRST_RUN_STATUS_SCHEMA_VERSION" in service_source
    assert "list_runs_from_request" in service_source
    assert "inspect_workflow_sample_data_status" in service_source
    assert "build_first_run_validation_card_from_request" in service_source
    assert "get_run_from_request" in service_source
    assert "list_servers_from_request" in service_source
    assert "get_server_execution_diagnostics_from_request" in service_source
    assert "get_workflow_catalog_from_request" in service_source
    assert "finalize_first_run_from_request" not in service_source
    assert "export_result_package_from_request" not in service_source
    assert 'startswith("FIRST_RUN_RESULT_PACKAGE")' not in service_source
    assert "_PACKAGE_RECOVERABLE_CODES" not in finalize_source
    assert "is_first_run_result_package_export_required" in finalize_source
    assert "def first_run_next_action(" in finalize_source


def _patch_status_sources(
    monkeypatch,
    *,
    runs: list[dict[str, Any]],
    sample_status: str = "ready",
    server: dict[str, Any] | None = None,
    servers: list[dict[str, Any]] | None = None,
    execution_diagnostics: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
) -> None:
    async def fake_list_runs(refresh: bool) -> dict[str, Any]:
        return {"data": {"items": runs, "refresh": refresh}}

    async def fake_sample_status(pipeline_id: str) -> dict[str, Any]:
        assert pipeline_id == MOVING_PICTURES_PIPELINE_ID
        return {
            "data": {
                "schemaVersion": "h2ometa.workflow-sample-data-status.v1",
                "pipelineId": MOVING_PICTURES_PIPELINE_ID,
                "status": sample_status,
                "itemCount": 3,
                "verifiedCacheCount": 3 if sample_status == "ready" else 0,
                "missingCacheCount": 0 if sample_status == "ready" else 3,
                "sourceRequired": sample_status != "ready",
                "blockerCodes": [],
                "items": [],
            }
        }

    async def fake_list_servers(refresh: bool) -> dict[str, Any]:
        items = servers if servers is not None else [server or _server()]
        return {"data": {"items": items, "refresh": refresh}}

    async def fake_execution_diagnostics(server_id: str) -> dict[str, Any]:
        assert server_id == "srv_first"
        return {"data": execution_diagnostics or _execution_diagnostics()}

    async def fake_workflow_catalog(refresh: bool) -> dict[str, Any]:
        return {"data": {"items": [workflow or _workflow()], "refresh": refresh}}

    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fake_list_runs)
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_servers_from_request", fake_list_servers)
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.get_server_execution_diagnostics_from_request",
        fake_execution_diagnostics,
    )
    monkeypatch.setattr("apps.api.workflow_first_run_status_service.get_workflow_catalog_from_request", fake_workflow_catalog)
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.inspect_workflow_sample_data_status",
        fake_sample_status,
    )


def _server(
    *,
    server_id: str = "srv_first",
    connected: bool = True,
    ready: bool = True,
    reason_code: str = "",
    message: str = "Remote runner control plane is ready.",
) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "label": "first-run",
        "connected": connected,
        "ready": ready,
        "reasonCode": reason_code,
        "message": message,
        "runner": {
            "ready": ready,
            "reasonCode": reason_code,
            "message": message,
        },
    }


def _execution_diagnostics() -> dict[str, Any]:
    return {
        "schemaVersion": "execution-diagnostics.v1",
        "readiness": {
            "ok": True,
            "status": "ready",
            "reasonCode": "",
            "blockingReasons": [],
        },
    }


def _workflow() -> dict[str, Any]:
    return {
        "id": MOVING_PICTURES_PIPELINE_ID,
        "name": "Moving Pictures 16S",
        "runnable": True,
        "status": "WorkflowReady",
        "source": "bundled",
        "version": "v1",
    }


def _noneligible_run(run_id: str, *, last_updated_at: str = "2026-06-29T00:10:00Z") -> dict[str, Any]:
    run = _run()
    run["runId"] = run_id
    run["lastUpdatedAt"] = last_updated_at
    run["runSpec"] = {**run["runSpec"]}
    run["runSpec"].pop("sampleDataPrepProof", None)
    return run
