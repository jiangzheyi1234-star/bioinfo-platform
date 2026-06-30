from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from apps.api.workflow_first_run_status_service import build_first_run_status_from_request
from apps.api.workflow_sample_data_service import MOVING_PICTURES_PIPELINE_ID

from tests.test_first_run_validation_card import _exports_for_case, _package, _patch_first_run_sources, _result, _run


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
    assert result["evidence"]["run"]["runId"] == "run_first"
    assert result["evidence"]["report"]["ready"] is True
    assert result["evidence"]["report"]["outputs"] == [
        "summary.tsv",
        "qc-summary.tsv",
        "feature-table.tsv",
        "run-report.html",
    ]
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
    assert result["evidence"]["run"] is None


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
    assert result["evidence"]["report"] == {"ready": False}
    assert result["evidence"]["resultPackage"] == {"ready": False, "blockedCode": expected_code}
    assert result["evidence"]["validation"]["ready"] is False
    assert result["evidence"]["validation"]["blockedCode"] == expected_code


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
    assert result["nextAction"]["target"] == "#runner-readiness"


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

    monkeypatch.setattr("apps.api.workflow_first_run_status_service.list_runs_from_request", fake_list_runs)
    monkeypatch.setattr(
        "apps.api.workflow_first_run_status_service.inspect_workflow_sample_data_status",
        fake_sample_status,
    )


def _noneligible_run(run_id: str, *, last_updated_at: str = "2026-06-29T00:10:00Z") -> dict[str, Any]:
    run = _run()
    run["runId"] = run_id
    run["lastUpdatedAt"] = last_updated_at
    run["runSpec"] = {**run["runSpec"]}
    run["runSpec"].pop("sampleDataPrepProof", None)
    return run
