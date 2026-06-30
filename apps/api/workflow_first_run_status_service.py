"""Read-only First Successful Run status aggregation."""

from __future__ import annotations

from typing import Any

from apps.api.execution_query_service import get_run_from_request, list_runs_from_request
from apps.api.workflow_first_run_finalize_service import first_run_next_action
from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_validation_card_from_request,
)
from apps.api.workflow_sample_data_service import (
    MOVING_PICTURES_FILES,
    MOVING_PICTURES_PIPELINE_ID,
    WORKFLOW_SAMPLE_DATA_CACHE_POLICY,
    WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA,
    WORKFLOW_SAMPLE_DATA_SOURCE,
    inspect_workflow_sample_data_status,
)


FIRST_RUN_STATUS_SCHEMA_VERSION = "h2ometa.first-run.status.v1"
FIRST_RUN_PIPELINE_NAME = "Moving Pictures 16S"
_FAILED_RUN_STATUSES = {"failed", "error", "canceled", "cancelled"}


async def build_first_run_status_from_request(
    *,
    server_id: str | None = None,
    run_id: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    normalized_server_id = str(server_id or "").strip()
    normalized_run_id = str(run_id or "").strip()
    sample_cache = _sample_cache_summary(
        _unwrap_data(await inspect_workflow_sample_data_status(MOVING_PICTURES_PIPELINE_ID), {})
    )
    runs_payload = await list_runs_from_request(refresh)
    runs = _mapping_items(_unwrap_data(runs_payload, {}).get("items"))
    selected_run = await _selected_run(normalized_run_id, runs)
    latest_eligible_raw = _latest_run([run for run in runs if _official_sample_run_blocker(run) == ""])
    latest_eligible_run = _run_summary(latest_eligible_raw) if latest_eligible_raw is not None else None
    ignored_latest_run = _ignored_latest_run(runs, latest_eligible_run)

    if not normalized_server_id:
        return _status_response(
            status="blocked",
            stage="connect_remote",
            next_action=_action("CONNECT_REMOTE", "连接远端 runner 后继续首跑。", "连接远端", "#runner-readiness"),
            sample_cache=sample_cache,
            latest_eligible_run=latest_eligible_run,
            ignored_latest_run=ignored_latest_run,
            run=None,
            server_id=normalized_server_id,
        )

    if selected_run is None:
        selected_run = latest_eligible_raw
    if selected_run is None:
        action = _action("PREPARE_SAMPLE_DATA", "准备并上传官方 Moving Pictures 16S 样例数据。", "准备示例数据", "#sample-data")
        if sample_cache.get("status") == "blocked":
            action["blockedCode"] = str((sample_cache.get("blockerCodes") or ["WORKFLOW_SAMPLE_DATA_BLOCKED"])[0])
        return _status_response(
            status="blocked",
            stage="prepare_sample_data",
            next_action=action,
            sample_cache=sample_cache,
            latest_eligible_run=None,
            ignored_latest_run=ignored_latest_run,
            run=None,
            server_id=normalized_server_id,
        )

    blocker = _official_sample_run_blocker(selected_run)
    run_summary = _run_summary(selected_run)
    if blocker:
        return _status_response(
            status="blocked",
            stage="prepare_sample_data",
            next_action=_blocked_action(
                "PREPARE_SAMPLE_DATA",
                blocker,
                "重新准备官方样例数据",
                "当前 run 不是官方 Moving Pictures 首跑样例运行。",
                "#sample-data",
            ),
            sample_cache=sample_cache,
            latest_eligible_run=latest_eligible_run,
            ignored_latest_run=ignored_latest_run,
            run=run_summary,
            server_id=normalized_server_id,
        )

    run_status = str(run_summary.get("status") or "").strip()
    if run_status != "completed":
        if run_status in _FAILED_RUN_STATUSES:
            status = "blocked"
            stage = "inspect_failed_run"
            action = _blocked_action(
                "INSPECT_FAILED_RUN",
                "FIRST_RUN_NOT_SUCCESSFUL",
                "定位失败原因",
                f"官方样例首跑状态为 {run_status}。",
                "#run-report",
            )
        else:
            status = "waiting"
            stage = "run_in_progress"
            action = _action("REFRESH_RUN", f"官方样例首跑状态为 {run_status or 'unknown'}。", "刷新运行状态", "#run-report")
        return _status_response(
            status=status,
            stage=stage,
            next_action=action,
            sample_cache=sample_cache,
            latest_eligible_run=latest_eligible_run,
            ignored_latest_run=ignored_latest_run,
            run=run_summary,
            server_id=normalized_server_id,
        )

    try:
        card = (await build_first_run_validation_card_from_request(str(run_summary["runId"]), server_id=normalized_server_id))["data"]
    except WorkflowFirstRunValidationCardUnavailableError as exc:
        code = _error_code(exc)
        action = _action_for_validation_blocker(code, str(exc))
        return _status_response(
            status="blocked",
            stage=_stage_for_blocker(code),
            next_action=action,
            sample_cache=sample_cache,
            latest_eligible_run=latest_eligible_run,
            ignored_latest_run=ignored_latest_run,
            run=run_summary,
            server_id=normalized_server_id,
            report=_report_evidence(False, code),
            result_package=_result_package_evidence(False, code),
            validation={"ready": False, "blockedCode": code, "detail": str(exc)},
        )

    return _status_response(
        status="ready",
        stage="validation_ready",
        next_action=_action("COMPLETE", "首跑验证卡、结果包和证据包均已就绪。", "下载/分享证据包", "#evidence-bundle"),
        sample_cache=sample_cache,
        latest_eligible_run=latest_eligible_run,
        ignored_latest_run=ignored_latest_run,
        run=run_summary,
        server_id=normalized_server_id,
        report=_ready_report_evidence(card),
        result_package=_ready_package_evidence(card),
        validation=_ready_validation_evidence(card),
    )


async def _selected_run(run_id: str, runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not run_id:
        return None
    listed = next((run for run in runs if str(run.get("runId") or "") == run_id), None)
    if listed is not None:
        return listed
    payload = await get_run_from_request(run_id)
    data = _unwrap_data(payload, {})
    return data if isinstance(data, dict) else None


def _status_response(
    *,
    status: str,
    stage: str,
    next_action: dict[str, str],
    sample_cache: dict[str, Any],
    latest_eligible_run: dict[str, Any] | None,
    ignored_latest_run: dict[str, Any] | None,
    run: dict[str, Any] | None,
    server_id: str,
    report: dict[str, Any] | None = None,
    result_package: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "schemaVersion": FIRST_RUN_STATUS_SCHEMA_VERSION,
            "scenario": {
                "pipelineId": MOVING_PICTURES_PIPELINE_ID,
                "pipelineName": FIRST_RUN_PIPELINE_NAME,
                "expectedSampleRoles": [item.role for item in MOVING_PICTURES_FILES],
            },
            "serverId": server_id,
            "status": status,
            "stage": stage,
            "nextAction": next_action,
            "latestEligibleRun": latest_eligible_run,
            "ignoredLatestRun": ignored_latest_run,
            "evidence": {
                "sampleCache": sample_cache,
                "run": run,
                "report": report or {"ready": False},
                "resultPackage": result_package or {"ready": False},
                "validation": validation or {"ready": False},
            },
        }
    }


def _sample_cache_summary(status: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "status": status.get("status"),
            "verifiedCacheCount": status.get("verifiedCacheCount"),
            "itemCount": status.get("itemCount"),
            "missingCacheCount": status.get("missingCacheCount"),
            "sourceRequired": status.get("sourceRequired"),
            "blockerCodes": status.get("blockerCodes") if isinstance(status.get("blockerCodes"), list) else None,
        }
    )


def _official_sample_run_blocker(run: dict[str, Any]) -> str:
    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    pipeline_id = str(run_spec.get("pipelineId") or "").strip()
    if pipeline_id != MOVING_PICTURES_PIPELINE_ID:
        return "FIRST_RUN_PIPELINE_UNSUPPORTED"
    proof = run_spec.get("sampleDataPrepProof") if isinstance(run_spec.get("sampleDataPrepProof"), dict) else {}
    if proof.get("schemaVersion") != WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA:
        return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
    if proof.get("source") != WORKFLOW_SAMPLE_DATA_SOURCE:
        return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
    if proof.get("cachePolicy") != WORKFLOW_SAMPLE_DATA_CACHE_POLICY:
        return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
    proof_items = _mapping_items(proof.get("items"))
    input_items = _mapping_items(run_spec.get("inputs"))
    expected_roles = {item.role for item in MOVING_PICTURES_FILES}
    proof_roles = [str(item.get("role") or "") for item in proof_items]
    input_roles = [str(item.get("role") or "") for item in input_items]
    if sorted(proof_roles) != sorted(expected_roles) or len(set(proof_roles)) != len(proof_roles):
        return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
    if sorted(input_roles) != sorted(expected_roles) or len(set(input_roles)) != len(input_roles):
        return "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"
    proof_by_role = {str(item.get("role") or ""): item for item in proof_items}
    inputs_by_role = {str(item.get("role") or ""): item for item in input_items}
    for expected in MOVING_PICTURES_FILES:
        proof_item = proof_by_role.get(expected.role)
        input_item = inputs_by_role.get(expected.role)
        if not isinstance(proof_item, dict) or not isinstance(input_item, dict):
            return "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"
        if not str(input_item.get("uploadId") or "").strip():
            return "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"
        if str(input_item.get("filename") or "") != expected.filename:
            return "FIRST_RUN_SAMPLE_INPUTS_REQUIRED"
        if proof_item.get("schemaVersion") != WORKFLOW_SAMPLE_DATA_PREP_PROOF_SCHEMA:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if str(proof_item.get("filename") or "") != expected.filename:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if str(proof_item.get("sourceUrl") or "") != expected.url:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if str(proof_item.get("expectedSha256") or "") != expected.expected_sha256:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if proof_item.get("expectedSizeBytes") != expected.expected_size_bytes:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if str(proof_item.get("sha256") or "") != expected.expected_sha256:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if str(proof_item.get("cacheStatus") or "") not in {"stored", "hit", "write-failed"}:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
        if str(proof_item.get("downloadStatus") or "") not in {"downloaded", "skipped-cache-hit"}:
            return "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"
    return ""


def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
    run_spec = run.get("runSpec") if isinstance(run.get("runSpec"), dict) else {}
    return _compact(
        {
            "runId": run.get("runId"),
            "status": run.get("status"),
            "stage": run.get("stage"),
            "workflowRevisionId": run.get("workflowRevisionId") or run_spec.get("workflowRevisionId"),
            "resultId": _canonical_result_id(str(run.get("runId") or "")),
            "submittedAt": run.get("submittedAt"),
            "startedAt": run.get("startedAt"),
            "finishedAt": run.get("finishedAt"),
            "lastUpdatedAt": run.get("lastUpdatedAt"),
        }
    )


def _latest_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    return sorted(runs, key=_run_sort_key, reverse=True)[0]


def _ignored_latest_run(runs: list[dict[str, Any]], latest_eligible_run: dict[str, Any] | None) -> dict[str, Any] | None:
    latest_raw = _latest_run(runs)
    if latest_raw is None:
        return None
    latest = _run_summary(latest_raw)
    if latest_eligible_run and latest.get("runId") == latest_eligible_run.get("runId"):
        return None
    return _compact({**latest, "blockingCode": _official_sample_run_blocker(latest_raw)})


def _run_sort_key(run: dict[str, Any]) -> tuple[str, str]:
    timestamp = (
        str(run.get("lastUpdatedAt") or "")
        or str(run.get("finishedAt") or "")
        or str(run.get("startedAt") or "")
        or str(run.get("submittedAt") or "")
    )
    return (timestamp, str(run.get("runId") or ""))


def _ready_report_evidence(card: dict[str, Any]) -> dict[str, Any]:
    interpretation = card.get("reportInterpretation") if isinstance(card.get("reportInterpretation"), dict) else {}
    outputs = _mapping_items(interpretation.get("outputs"))
    return {"ready": interpretation.get("status") == "ready", "outputs": [item.get("name") for item in outputs]}


def _ready_package_evidence(card: dict[str, Any]) -> dict[str, Any]:
    package = card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {}
    return _compact(
        {
            "ready": True,
            "packageExportId": package.get("packageExportId"),
            "sha256": package.get("sha256"),
            "manifestSha256": package.get("manifestSha256"),
            "artifactPayloadMode": package.get("artifactPayloadMode"),
            "includeArtifacts": package.get("includeArtifacts"),
        }
    )


def _ready_validation_evidence(card: dict[str, Any]) -> dict[str, Any]:
    checks = _mapping_items(card.get("checks"))
    passed = [item for item in checks if item.get("status") == "passed"]
    handoff = card.get("pilotHandoff") if isinstance(card.get("pilotHandoff"), dict) else {}
    bundle = handoff.get("evidenceBundle") if isinstance(handoff.get("evidenceBundle"), dict) else {}
    return _compact(
        {
            "ready": True,
            "validationChecksPassed": len(passed),
            "validationChecksTotal": len(checks),
            "evidenceBundleReady": bundle.get("status") == "ready",
            "evidenceBundleId": bundle.get("bundleId"),
        }
    )


def _report_evidence(ready: bool, code: str) -> dict[str, Any]:
    if code not in {"FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED", "FIRST_RUN_REPORT_PREVIEW_REQUIRED"}:
        return {"ready": False}
    return {"ready": ready, "blockedCode": code}


def _result_package_evidence(ready: bool, code: str) -> dict[str, Any]:
    if not (code.startswith("FIRST_RUN_RESULT_PACKAGE") or code == "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED"):
        return {"ready": False}
    return {"ready": ready, "blockedCode": code}


def _action_for_validation_blocker(code: str, detail: str) -> dict[str, str]:
    if code in {"FIRST_RUN_SAMPLE_INPUTS_REQUIRED", "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH", "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"}:
        return _blocked_action("PREPARE_SAMPLE_DATA", code, "重新准备官方样例数据", detail, "#sample-data")
    if code == "FIRST_RUN_WORKFLOW_REVISION_REQUIRED":
        return _blocked_action("ENSURE_RUNNER", code, "升级 runner 并重新提交", detail, "#runner-readiness")
    if code in {"FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED", "FIRST_RUN_REPORT_PREVIEW_REQUIRED", "FIRST_RUN_NOT_SUCCESSFUL"}:
        return _blocked_action("INSPECT_FAILED_RUN", code, "检查报告与失败定位", detail, "#run-report")
    if code.startswith("FIRST_RUN_RESULT_PACKAGE") or code == "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED":
        base = first_run_next_action(code, detail)
        return _blocked_action("FINALIZE_FIRST_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))
    if code in {"FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED", "FIRST_RUN_PILOT_HANDOFF_REQUIRED"}:
        base = first_run_next_action(code, detail)
        return _blocked_action("FINALIZE_FIRST_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))
    base = first_run_next_action(code, detail)
    return _blocked_action("REFRESH_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))


def _stage_for_blocker(code: str) -> str:
    if code in {"FIRST_RUN_SAMPLE_INPUTS_REQUIRED", "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH", "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"}:
        return "prepare_sample_data"
    if code in {"FIRST_RUN_NOT_SUCCESSFUL", "FIRST_RUN_REPORT_PREVIEW_REQUIRED", "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"}:
        return "inspect_failed_run"
    if code.startswith("FIRST_RUN_RESULT_PACKAGE") or code == "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED":
        return "export_result_package"
    if code in {"FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED", "FIRST_RUN_PILOT_HANDOFF_REQUIRED"}:
        return "validation_ready"
    if code == "FIRST_RUN_WORKFLOW_REVISION_REQUIRED":
        return "runner_readiness"
    return "run_in_progress"


def _action(code: str, detail: str, label: str, target: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "label": label, "target": target}


def _blocked_action(code: str, blocked_code: str, label: str, detail: str, target: str) -> dict[str, str]:
    return {"code": code, "blockedCode": blocked_code, "detail": detail, "label": label, "target": target}


def _canonical_result_id(run_id: str) -> str:
    return run_id if run_id.startswith("res_") else f"res_{run_id}"


def _anchor_target(target: str) -> str:
    text = str(target or "").strip()
    return "#" + text.split("#", 1)[1] if "#" in text else text


def _error_code(exc: WorkflowFirstRunValidationCardUnavailableError) -> str:
    return str(exc).split(":", 1)[0].strip() or "FIRST_RUN_STATUS_BLOCKED"


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
