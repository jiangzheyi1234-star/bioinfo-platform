from __future__ import annotations

import asyncio
import copy
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
    handoff = card["pilotHandoff"]
    assert handoff["schemaVersion"] == "h2ometa.first-run.single-user-lab-pilot-handoff.v1"
    assert handoff["evidenceBundle"] == _expected_evidence_bundle()
    assert handoff["backupRestore"] == {
        "schemaVersion": "h2ometa.first-run.backup-restore-handoff.v1",
        "mode": "read-only-plan",
        "planCommand": (
            "scripts\\single_user_pilot_backup_plan.ps1 "
            "-RemoteRunnerSharedRoot \"<remote-shared-root>\" -RequireExistingState"
        ),
        "restoreProofCommand": "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady",
        "runbookPath": "docs/single-user-pilot-backup-restore.md",
        "requiresIsolatedRestore": True,
        "requiresManualSecretRebind": True,
        "noAutomaticBackup": True,
        "excludedActions": ["hot-sqlite-copy", "secret-archive", "cache-as-durable-state"],
    }
    assert [item["scenarioId"] for item in handoff["nextScenarios"]] == [
        "taxonomy-classification",
        "amr-annotation",
    ]
    assert handoff["nextScenarios"][0]["databasePackCoverage"]["packCount"] == 1
    taxonomy_tool_slice = handoff["nextScenarios"][0]["toolSlicePromotionHandoff"]
    assert taxonomy_tool_slice["schemaVersion"] == "h2ometa.first-run.next-scenario-tool-slice-promotion-handoff.v1"
    assert taxonomy_tool_slice["requiredState"] == "WorkflowReady"
    assert taxonomy_tool_slice["noAutomaticExecution"] is True
    assert taxonomy_tool_slice["sliceSize"] == {"min": 3, "max": 5, "actual": 3}
    assert [item["contractState"] for item in taxonomy_tool_slice["toolOptions"]] == ["planned", "planned", "planned"]
    assert {item["acceptanceEvidenceContract"]["status"] for item in taxonomy_tool_slice["toolOptions"]} == {
        "operator_required"
    }
    assert {item["acceptanceEvidenceContract"]["evidenceRef"] for item in taxonomy_tool_slice["toolOptions"]} == {""}
    assert all(
        "pending-string-only-evidence" in item["acceptanceEvidenceContract"]["rejectedEvidence"]
        for item in taxonomy_tool_slice["toolOptions"]
    )
    assert all(
        set(item["acceptanceEvidenceContract"]["evidencePointers"]) == {
            "toolRevisionId",
            "capabilityBundle",
            "ruleSpec",
            "environmentLock",
            "smokeFixture",
            "expectedOutputArtifacts",
        }
        for item in taxonomy_tool_slice["toolOptions"]
    )
    assert taxonomy_tool_slice["promotionContract"]["requiredEvidence"] == [
        "toolRevisionId",
        "capability-bundle-v1",
        "RuleSpec",
        "environment-lock",
        "smoke-fixture",
        "expected-output-artifacts",
    ]
    assert "tool-count-only-readiness" in taxonomy_tool_slice["promotionContract"]["excludedActions"]
    taxonomy_install = handoff["nextScenarios"][0]["databaseInstallHandoff"]
    assert taxonomy_install["schemaVersion"] == "h2ometa.first-run.next-scenario-database-install-handoff.v1"
    assert taxonomy_install["mode"] == "manual_external"
    assert taxonomy_install["status"] == "operator_required"
    assert taxonomy_install["noAutomaticExecution"] is True
    assert taxonomy_install["readyScan"] == {
        "schemaVersion": "h2ometa.database-pack-ready-scan.v1",
        "method": "POST",
        "path": "/api/v1/database-pack-ready-scans",
        "requestFields": ["packId", "readyPath", "fieldPaths?"],
        "acceptedStatus": "ready",
        "mutatesRegistry": False,
        "requiresOperatorReadyPath": True,
        "auditAction": "database_pack.ready_scan",
    }
    assert taxonomy_install["registration"] == {
        "method": "POST",
        "path": "/api/v1/databases",
        "requiresReadyScan": True,
        "prefillSource": "database-pack-ready-scan.registrationPrefill",
        "prefillFields": [
            "id",
            "name",
            "templateId",
            "type",
            "version",
            "path",
            "databaseLayer",
            "source",
            "sizeBytes",
            "checksum",
            "metadata.installedFromPackId",
        ],
        "acceptedStatus": "available",
    }
    assert {item["code"] for item in taxonomy_install["checklist"]} == {
        "SELECT_TEMPLATE",
        "VERIFY_CHECKSUM",
        "READY_SCAN",
        "REGISTER_DATABASE",
        "BIND_DATABASE",
        "REAL_DATABASE_ACCEPTANCE",
    }
    assert taxonomy_install["packOptions"][0]["packId"] == "h2ometa-gtdbtk-r232-official"
    assert taxonomy_install["packOptions"][0]["checksum"] == "md5:25a59e0352b1fd150c589f56559767d4"
    assert taxonomy_install["packOptions"][0]["registrationScriptPath"] == "scripts/register_gtdbtk_r232_database.py"
    assert taxonomy_install["evidencePolicy"]["acceptedEvidenceType"] == "real-database-acceptance"
    assert taxonomy_install["evidencePolicy"]["validationFixtureAccepted"] is False
    assert taxonomy_install["excludedActions"] == ["automatic-download", "automatic-extract", "automatic-install"]
    assert handoff["nextScenarios"][1]["databasePackCoverage"]["missingTemplates"] == [
        "card_rgi",
        "eggnog_mapper",
        "interproscan",
    ]
    assert handoff["nextScenarios"][1]["databaseInstallHandoff"]["readyScan"]["path"] == (
        "/api/v1/database-pack-ready-scans"
    )
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
    assert sample_data["prepProof"]["schemaVersion"] == "h2ometa.workflow-sample-data-prep-proof.v1"
    assert sample_data["prepProof"]["cachePolicy"] == "verified-sha256-local-cache"
    assert {item["role"]: item["prepProof"]["cacheStatus"] for item in sample_data["items"]} == {
        "metadata": "stored",
        "barcodes": "stored",
        "sequences": "stored",
    }
    assert {item["role"]: item["prepProof"]["downloadStatus"] for item in sample_data["items"]} == {
        "metadata": "downloaded",
        "barcodes": "downloaded",
        "sequences": "downloaded",
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
        ("empty-download-href", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
        ("external-download-href", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
        ("wrong-download-api", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
        ("wrong-download-result", "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED"),
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


def test_first_run_validation_card_requires_sample_prep_proof(monkeypatch) -> None:
    run = _run()
    run["runSpec"].pop("sampleDataPrepProof")
    _patch_first_run_sources(monkeypatch, run=run)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


def test_first_run_validation_card_requires_parseable_report_previews(monkeypatch) -> None:
    previews = _previews()
    previews["art_summary"]["preview"] = {"kind": "table", "columns": ["sample_id"], "rows": [["sample-a"]]}
    _patch_first_run_sources(monkeypatch, previews=previews)

    with pytest.raises(WorkflowFirstRunValidationCardUnavailableError, match="FIRST_RUN_REPORT_PREVIEW_REQUIRED"):
        asyncio.run(build_first_run_validation_card_from_request("run_first"))


@pytest.mark.parametrize(
    "preview_case",
    [
        "zero_passed_reads",
        "zero_unique_features",
        "missing_qc_samples_with_reads",
        "missing_qc_features",
        "qc_passed_reads_mismatch",
        "qc_samples_with_reads_mismatch",
        "qc_features_mismatch",
    ],
)
def test_first_run_validation_card_requires_report_trust_assertions(monkeypatch, preview_case: str) -> None:
    _patch_first_run_sources(monkeypatch, previews=_previews_for_trust_case(preview_case))

    with pytest.raises(
        WorkflowFirstRunValidationCardUnavailableError,
        match="FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED",
    ):
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
    assert result["evidenceBundle"] == _expected_evidence_bundle()
    assert result["pilotHandoff"] == {
        "schemaVersion": "h2ometa.first-run.single-user-lab-pilot-handoff.v1",
        "scope": "single-user-lab",
        "status": "ready",
        "evidence": {
            "runId": "run_first",
            "resultId": "res_run_first",
            "workflowRevisionId": "wfrev_first",
            "packageExportId": "rpex_full",
            "packageSha256": "d" * 64,
            "manifestSha256": "e" * 64,
            "validationChecksPassed": 10,
            "validationChecksTotal": 10,
        },
        "evidenceBundle": _expected_evidence_bundle(),
        "backupRestore": {
            "schemaVersion": "h2ometa.first-run.backup-restore-handoff.v1",
            "mode": "read-only-plan",
            "planCommand": (
                "scripts\\single_user_pilot_backup_plan.ps1 "
                "-RemoteRunnerSharedRoot \"<remote-shared-root>\" -RequireExistingState"
            ),
            "restoreProofCommand": "scripts\\first_run_pilot_check.ps1 -RunFirstSuccessfulRun -RequireFinalizationReady",
            "runbookPath": "docs/single-user-pilot-backup-restore.md",
            "requiresIsolatedRestore": True,
            "requiresManualSecretRebind": True,
            "noAutomaticBackup": True,
            "excludedActions": ["hot-sqlite-copy", "secret-archive", "cache-as-durable-state"],
        },
        "nextScenarios": result["validationCard"]["pilotHandoff"]["nextScenarios"],
        "nextAction": {
            "code": "RUN_OWN_SMALL_SAMPLE",
            "label": "用自己的小样本跑一次",
            "target": "/workflows",
        },
        "exclusions": ["public-multi-user", "rbac", "kubernetes", "automatic-database-install"],
    }
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
    assert result["evidenceBundle"]["requiredFiles"][0]["packageExportId"] == "rpex_finalized"


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


def test_first_run_finalize_requires_server_pilot_handoff(monkeypatch) -> None:
    async def fake_card(*_args, **_kwargs):
        return {"data": {"schemaVersion": "h2ometa.first-run.validation-card.v1", "resultPackage": {}}}

    monkeypatch.setattr(
        "apps.api.workflow_first_run_finalize_service.build_first_run_validation_card_from_request",
        fake_card,
    )

    result = asyncio.run(
        finalize_first_run_from_request("run_first", WorkflowFirstRunFinalizeRequest(serverId="srv_first"))
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"]["code"] == "FIRST_RUN_PILOT_HANDOFF_REQUIRED"


def test_first_run_finalize_requires_server_evidence_bundle(monkeypatch) -> None:
    async def fake_card(*_args, **_kwargs):
        return {
            "data": {
                "schemaVersion": "h2ometa.first-run.validation-card.v1",
                "resultPackage": {},
                "pilotHandoff": {"schemaVersion": "h2ometa.first-run.single-user-lab-pilot-handoff.v1"},
            }
        }

    monkeypatch.setattr(
        "apps.api.workflow_first_run_finalize_service.build_first_run_validation_card_from_request",
        fake_card,
    )

    result = asyncio.run(
        finalize_first_run_from_request("run_first", WorkflowFirstRunFinalizeRequest(serverId="srv_first"))
    )["data"]

    assert result["status"] == "blocked"
    assert result["nextAction"] == {
        "code": "FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED",
        "detail": "FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED: first-run pilotHandoff must include evidenceBundle",
        "label": "重新生成首跑验证卡",
        "target": "/workflows/first-run#evidence-bundle",
    }


def test_first_run_validation_card_route_and_error_handler_are_registered() -> None:
    route_source = _source("apps/api/workflow_first_run_routes.py")
    finalize_source = _source("apps/api/workflow_first_run_finalize_service.py")
    service_source = _source("apps/api/workflow_first_run_service.py")
    markdown_source = _source("apps/api/workflow_first_run_markdown.py")
    main_source = _source("apps/api/main.py")
    route_errors = _source("apps/api/route_errors.py")

    assert '@router.get("/api/v1/first-run/runs/{run_id}/validation-card")' in route_source
    assert '@router.get("/api/v1/first-run/runs/{run_id}/validation-card.json")' in route_source
    assert '@router.get("/api/v1/first-run/runs/{run_id}/validation-card.md")' in route_source
    assert '@router.get("/api/v1/first-run/runs/{run_id}/pilot-handoff.md")' in route_source
    assert '@router.get("/api/v1/first-run/runs/{run_id}/evidence-bundle.zip")' in route_source
    assert "first_run_validation_card_markdown" in route_source
    assert "first_run_handoff_manifest_markdown" in route_source
    assert "zipfile.ZipFile" in route_source
    assert "_first_run_evidence_bundle_readme" in route_source
    assert "Content-Disposition" in route_source
    assert "private, no-store" in route_source
    assert "H2OMeta First Successful Run Validation Card" in markdown_source
    assert "H2OMeta First Successful Run Pilot Handoff" in markdown_source
    assert '@router.post("/api/v1/first-run/runs/{run_id}/finalize")' in route_source
    assert "build_first_run_validation_card_from_request" in route_source
    assert "finalize_first_run_from_request" in route_source
    assert "FIRST_RUN_FINALIZATION_SCHEMA_VERSION" in finalize_source
    assert "FIRST_RUN_PILOT_HANDOFF_REQUIRED" in finalize_source
    assert "FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED" in finalize_source
    assert "build_first_run_pilot_handoff" in service_source
    assert "pilotHandoff" in service_source
    assert 'target = "/workflows/first-run#run-report"' in finalize_source
    assert 'target = "/workflows/first-run#evidence-bundle"' in finalize_source
    assert 'target = "/workflows/first-run#report"' not in finalize_source
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
            "sampleDataPrepProof": _sample_data_prep_proof(),
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


def _sample_data_prep_proof() -> dict[str, Any]:
    return {
        "schemaVersion": "h2ometa.workflow-sample-data-prep-proof.v1",
        "source": "QIIME 2 Moving Pictures tutorial",
        "cachePolicy": "verified-sha256-local-cache",
        "items": [
            {
                "schemaVersion": "h2ometa.workflow-sample-data-prep-proof.v1",
                "role": item.role,
                "filename": item.filename,
                "sourceUrl": item.url,
                "sha256": item.expected_sha256,
                "expectedSha256": item.expected_sha256,
                "expectedSizeBytes": item.expected_size_bytes,
                "cacheStatus": "stored",
                "downloadStatus": "downloaded",
                "downloadAttempts": 1,
            }
            for item in MOVING_PICTURES_FILES
        ],
    }


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


def _previews_for_trust_case(preview_case: str) -> dict[str, dict[str, Any]]:
    previews = copy.deepcopy(_previews())
    summary_rows = previews["art_summary"]["preview"]["rows"]
    qc_rows = previews["art_qc"]["preview"]["rows"]
    if preview_case == "zero_passed_reads":
        summary_rows[0][5] = "0"
        summary_rows[1][5] = "0"
        _set_qc_metric(qc_rows, "passed_reads", "0")
    elif preview_case == "zero_unique_features":
        summary_rows[0][6] = "0"
        summary_rows[1][6] = "0"
        _set_qc_metric(qc_rows, "features", "0")
    elif preview_case == "missing_qc_samples_with_reads":
        previews["art_qc"]["preview"]["rows"] = [row for row in qc_rows if row[0] != "samples_with_reads"]
    elif preview_case == "missing_qc_features":
        previews["art_qc"]["preview"]["rows"] = [row for row in qc_rows if row[0] != "features"]
    elif preview_case == "qc_passed_reads_mismatch":
        _set_qc_metric(qc_rows, "passed_reads", "29")
    elif preview_case == "qc_samples_with_reads_mismatch":
        _set_qc_metric(qc_rows, "samples_with_reads", "1")
    elif preview_case == "qc_features_mismatch":
        _set_qc_metric(qc_rows, "features", "8")
    else:
        raise AssertionError(f"unknown preview case {preview_case}")
    return previews


def _set_qc_metric(rows: list[list[str]], metric_id: str, value: str) -> None:
    for row in rows:
        if row[0] == metric_id:
            row[1] = value
            return
    raise AssertionError(f"qc metric {metric_id} not found")


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
    if export_case == "empty-download-href":
        package = _package("rpex_empty_href")
        package["download"]["href"] = ""
        return [package]
    if export_case == "external-download-href":
        package = _package("rpex_external_href")
        package["download"]["href"] = "https://example.test/result.zip"
        return [package]
    if export_case == "wrong-download-api":
        package = _package("rpex_wrong_api")
        package["download"]["href"] = "/api/v1/first-run/runs/run_first/validation-card.json"
        return [package]
    if export_case == "wrong-download-result":
        package = _package("rpex_wrong_result")
        package["download"]["href"] = "/api/v1/results/res_other/exports/rpex_wrong_result/download"
        return [package]
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
            "href": f"/api/v1/results/res_run_first/exports/{package_export_id}/download",
            "filename": f"{package_export_id}.zip",
        }
    return item


def _expected_evidence_bundle(
    *,
    package_export_id: str = "rpex_full",
    sha256: str = "d" * 64,
    manifest_sha256: str = "e" * 64,
) -> dict[str, Any]:
    return {
        "schemaVersion": "h2ometa.first-run.evidence-bundle.v1",
        "status": "ready",
        "bundleId": "res_run_first.first-run-evidence",
        "purpose": "portable-first-successful-run-proof",
        "download": {
            "role": "evidence-bundle-zip",
            "filename": "res_run_first.first-run-evidence.zip",
            "source": "first-run-evidence-bundle-zip-api",
            "href": "/api/v1/first-run/runs/run_first/evidence-bundle.zip?serverId=srv_first",
        },
        "requiredFiles": [
            {
                "role": "result-package",
                "filename": f"{package_export_id}.zip",
                "source": "result-package-export-download",
                "packageExportId": package_export_id,
                "sha256": sha256,
                "manifestSha256": manifest_sha256,
                "artifactPayloadMode": "full",
                "includeArtifacts": True,
                "href": f"/api/v1/results/res_run_first/exports/{package_export_id}/download?serverId=srv_first",
            },
            {
                "role": "validation-card-json",
                "filename": "res_run_first.validation-card.json",
                "source": "first-run-validation-card-api",
                "schemaVersion": "h2ometa.first-run.validation-card.v1",
                "href": "/api/v1/first-run/runs/run_first/validation-card.json?serverId=srv_first",
            },
            {
                "role": "validation-card-markdown",
                "filename": "res_run_first.validation-card.md",
                "source": "first-run-validation-card-markdown-api",
                "schemaVersion": "h2ometa.first-run.validation-card.v1",
                "href": "/api/v1/first-run/runs/run_first/validation-card.md?serverId=srv_first",
            },
            {
                "role": "pilot-handoff",
                "filename": "res_run_first.pilot-handoff.md",
                "source": "first-run-pilot-handoff-markdown-api",
                "schemaVersion": "h2ometa.first-run.single-user-lab-pilot-handoff.v1",
                "href": "/api/v1/first-run/runs/run_first/pilot-handoff.md?serverId=srv_first",
            },
        ],
        "integrity": {
            "runId": "run_first",
            "resultId": "res_run_first",
            "workflowRevisionId": "wfrev_first",
            "packageExportId": package_export_id,
            "packageSha256": sha256,
            "manifestSha256": manifest_sha256,
            "validationChecksPassed": 10,
            "validationChecksTotal": 10,
        },
        "redaction": {
            "rawPathsExposed": False,
            "storageUrisExposed": False,
            "previewRowsEmbedded": False,
            "policy": "metrics-only",
        },
        "standards": {
            "workflowRunCrate": "https://www.researchobject.org/workflow-run-crate/",
            "w3cProv": "https://www.w3.org/TR/prov-o/",
        },
        "consumerChecklist": [
            "keep-result-package-validation-card-and-handoff-together",
            "verify-package-sha256-before-sharing",
            "verify-manifest-sha256-before-reusing-lineage",
        ],
    }


def _source(path: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
