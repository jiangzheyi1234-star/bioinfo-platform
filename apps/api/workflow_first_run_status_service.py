"""Read-only First Successful Run status aggregation."""

from __future__ import annotations

from typing import Any

from apps.api.execution_query_service import get_run_from_request, list_runs_from_request
from apps.api.ssh_control_service import (
    get_server_execution_diagnostics_from_request,
    list_servers_from_request,
)
from apps.api.workflow_catalog_service import get_workflow_catalog_from_request
from apps.api.workflow_first_run_completion_proof_contract import (
    latest_first_run_completion_proof_evidence,
)
from apps.api.workflow_first_run_finalize_service import FIRST_RUN_COMPLETION_PROOF_REQUIRED, first_run_next_action
from apps.api.workflow_first_run_report_interpretation import FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED
from apps.api.workflow_first_run_result_package_contract import (
    is_first_run_result_package_blocker,
    is_first_run_result_package_export_required,
    is_first_run_result_package_ledger_mismatch,
)
from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_validation_card_from_request,
)
from apps.api.workflow_first_run_status_report import (
    public_report_evidence,
    ready_report_evidence,
    report_blocked_code,
    report_evidence,
    report_evidence_for_package_blocker,
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
    completion_proof = (
        latest_first_run_completion_proof_evidence(
            server_id=normalized_server_id,
            run_id=normalized_run_id,
        )
        if normalized_server_id or normalized_run_id
        else {"ready": False}
    )
    if _completion_proof_matches_requested_run(completion_proof, run_id=normalized_run_id):
        return _completion_proof_status_response(
            completion_proof,
            sample_cache=sample_cache,
            server_id=normalized_server_id,
        )

    if not normalized_server_id:
        return _status_response(
            status="blocked",
            stage="connect_remote",
            next_action=_blocked_action(
                "CONNECT_REMOTE",
                "FIRST_RUN_SERVER_REQUIRED",
                "连接远端",
                "连接远端 runner 后继续首跑。",
                "#runner-readiness",
            ),
            sample_cache=sample_cache,
            latest_eligible_run=None,
            ignored_latest_run=None,
            run=None,
            server_id=normalized_server_id,
            server=_server_evidence(None, server_id=normalized_server_id, blocked_code="FIRST_RUN_SERVER_REQUIRED"),
            execution={"ready": False, "blockedCode": "FIRST_RUN_SERVER_REQUIRED"},
            workflow={"ready": False, "blockedCode": "FIRST_RUN_SERVER_REQUIRED"},
            completion_proof=completion_proof,
        )

    runner_gate = await _runner_readiness_gate(normalized_server_id, refresh=refresh)
    if runner_gate.get("blocked"):
        return _status_response(
            status="blocked",
            stage=str(runner_gate["stage"]),
            next_action=runner_gate["nextAction"],
            sample_cache=sample_cache,
            latest_eligible_run=None,
            ignored_latest_run=None,
            run=None,
            server_id=normalized_server_id,
            server=runner_gate.get("server"),
            execution=runner_gate.get("execution"),
            completion_proof=completion_proof,
        )
    server_evidence = runner_gate.get("server")
    execution_evidence = runner_gate.get("execution")

    workflow_gate = await _workflow_example_gate(refresh=refresh)
    workflow_evidence = workflow_gate.get("workflow")
    if workflow_gate.get("blocked"):
        return _status_response(
            status="blocked",
            stage="select_example",
            next_action=workflow_gate["nextAction"],
            sample_cache=sample_cache,
            latest_eligible_run=None,
            ignored_latest_run=None,
            run=None,
            server_id=normalized_server_id,
            server=server_evidence,
            execution=execution_evidence,
            workflow=workflow_evidence,
            completion_proof=completion_proof,
        )

    runs_payload = await list_runs_from_request(refresh)
    runs = _mapping_items(_unwrap_data(runs_payload, {}).get("items"))
    selected_run = await _selected_run(normalized_run_id, runs)
    latest_eligible_raw = _latest_run(
        [run for run in runs if _first_run_run_blocker(run, server_id=normalized_server_id) == ""]
    )
    latest_eligible_run = _run_summary(latest_eligible_raw) if latest_eligible_raw is not None else None
    ignored_latest_run = _ignored_latest_run(runs, latest_eligible_run, server_id=normalized_server_id)

    if selected_run is None:
        selected_run = latest_eligible_raw
    if selected_run is None:
        if sample_cache.get("status") == "ready":
            return _status_response(
                status="blocked",
                stage="submit_run",
                next_action=_action(
                    "SUBMIT_RUN",
                    "官方 Moving Pictures 16S 样例数据已就绪，提交首跑运行。",
                    "提交运行",
                    "#sample-data",
                ),
                sample_cache=sample_cache,
                latest_eligible_run=None,
                ignored_latest_run=ignored_latest_run,
                run=None,
                server_id=normalized_server_id,
                server=server_evidence,
                execution=execution_evidence,
                workflow=workflow_evidence,
                completion_proof=completion_proof,
            )
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
            server=server_evidence,
            execution=execution_evidence,
            workflow=workflow_evidence,
            completion_proof=completion_proof,
        )

    blocker = _first_run_run_blocker(selected_run, server_id=normalized_server_id)
    run_summary = _run_summary(selected_run)
    if blocker:
        if blocker == "FIRST_RUN_RUN_SERVER_MISMATCH":
            return _status_response(
                status="blocked",
                stage="submit_run",
                next_action=_blocked_action(
                    "SUBMIT_RUN",
                    blocker,
                    "在当前远端重新提交首跑",
                    "当前 run 不属于所选远端 runner，不能作为这个远端的首跑证据。",
                    "#sample-data",
                ),
                sample_cache=sample_cache,
                latest_eligible_run=latest_eligible_run,
                ignored_latest_run=ignored_latest_run,
                run=run_summary,
                server_id=normalized_server_id,
                server=server_evidence,
                execution=execution_evidence,
                workflow=workflow_evidence,
                completion_proof=completion_proof,
            )
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
            server=server_evidence,
            execution=execution_evidence,
            workflow=workflow_evidence,
            completion_proof=completion_proof,
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
            server=server_evidence,
            execution=execution_evidence,
            workflow=workflow_evidence,
            completion_proof=completion_proof,
        )

    try:
        card = (await build_first_run_validation_card_from_request(str(run_summary["runId"]), server_id=normalized_server_id))["data"]
    except WorkflowFirstRunValidationCardUnavailableError as exc:
        code = _error_code(exc)
        detail = str(exc)
        report = await report_evidence_for_package_blocker(
            code,
            run_id=str(run_summary["runId"]),
            server_id=normalized_server_id,
        )
        if not report.get("ready") and report_blocked_code(report):
            code = report_blocked_code(report)
            detail = str(report.get("detail") or detail)
        action = _action_for_validation_blocker(code, detail)
        return _status_response(
            status="blocked",
            stage=_stage_for_blocker(code),
            next_action=action,
            sample_cache=sample_cache,
            latest_eligible_run=latest_eligible_run,
            ignored_latest_run=ignored_latest_run,
            run=run_summary,
            server_id=normalized_server_id,
            server=server_evidence,
            execution=execution_evidence,
            workflow=workflow_evidence,
            report=public_report_evidence(report) if report else report_evidence(False, code),
            result_package=_result_package_evidence(False, code),
            validation={"ready": False, "blockedCode": code, "detail": detail},
            completion_proof=completion_proof,
        )

    if completion_proof.get("ready") is not True:
        proof_blocker = str(completion_proof.get("blockedCode") or "").strip()
        code = proof_blocker or FIRST_RUN_COMPLETION_PROOF_REQUIRED
        detail = str(completion_proof.get("detail") or "").strip() or "首跑验证卡、结果包和证据包均已就绪；请完成首跑以写入本地完成证明。"
        action = first_run_next_action(code, detail)
        action_code = "REFRESH_RUN" if proof_blocker == "FIRST_RUN_COMPLETION_PROOF_STORE_UNREADABLE" else "FINALIZE_FIRST_RUN"
        return _status_response(
            status="blocked",
            stage="validation_ready" if action_code == "REFRESH_RUN" else "export_result_package",
            next_action=_blocked_action(
                action_code,
                code,
                action["label"],
                action["detail"],
                _anchor_target(action["target"]),
            ),
            sample_cache=sample_cache,
            latest_eligible_run=latest_eligible_run,
            ignored_latest_run=ignored_latest_run,
            run=run_summary,
            server_id=normalized_server_id,
            server=server_evidence,
            execution=execution_evidence,
            workflow=workflow_evidence,
            report=ready_report_evidence(card),
            result_package=_ready_package_evidence(card),
            validation={
                "ready": False,
                "blockedCode": code,
                "detail": detail,
            },
            completion_proof=completion_proof,
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
        server=server_evidence,
        execution=execution_evidence,
        workflow=workflow_evidence,
        report=ready_report_evidence(card),
        result_package=_ready_package_evidence(card),
        validation=_ready_validation_evidence(card),
        completion_proof=completion_proof,
    )


def _completion_proof_matches_requested_run(
    completion_proof: dict[str, Any] | None,
    *,
    run_id: str,
) -> bool:
    if not completion_proof or completion_proof.get("ready") is not True:
        return False
    requested_run_id = str(run_id or "").strip()
    if not requested_run_id:
        return True
    return str(completion_proof.get("runId") or "").strip() == requested_run_id


def _completion_proof_status_response(
    completion_proof: dict[str, Any],
    *,
    sample_cache: dict[str, Any],
    server_id: str,
) -> dict[str, Any]:
    effective_server_id = server_id or str(completion_proof.get("serverId") or "").strip()
    run = _completion_proof_run_summary(completion_proof)
    return _status_response(
        status="ready",
        stage="validation_ready",
        next_action=_action(
            "COMPLETE",
            "首跑完成证明已保存；重新连接 runner 后可刷新下载完整证据包。",
            "查看已保存证明",
            "#evidence-bundle",
        ),
        sample_cache=sample_cache,
        latest_eligible_run=run,
        ignored_latest_run=None,
        run=run,
        server_id=effective_server_id,
        server={
            "ready": False,
            "serverId": effective_server_id,
            "detail": "saved completion proof; current runner was not inspected",
        },
        execution={"ready": False, "detail": "saved completion proof; current runner was not inspected"},
        workflow={"ready": False, "pipelineId": MOVING_PICTURES_PIPELINE_ID},
        report=_completion_proof_report_evidence(completion_proof),
        result_package=_completion_proof_package_evidence(completion_proof),
        validation=_completion_proof_validation_evidence(completion_proof),
        completion_proof=completion_proof,
    )


def _completion_proof_run_summary(completion_proof: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "runId": completion_proof.get("runId"),
            "serverId": completion_proof.get("serverId"),
            "status": "completed",
            "stage": "validation_ready",
            "workflowRevisionId": completion_proof.get("workflowRevisionId"),
            "resultId": completion_proof.get("resultId"),
            "finishedAt": completion_proof.get("validationCardGeneratedAt"),
            "lastUpdatedAt": completion_proof.get("savedAt"),
        }
    )


def _completion_proof_report_evidence(completion_proof: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "ready": completion_proof.get("reportReady") is True,
            "outputs": completion_proof.get("reportOutputNames") or [],
        }
    )


def _completion_proof_package_evidence(completion_proof: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "ready": True,
            "packageExportId": completion_proof.get("packageExportId"),
            "sha256": completion_proof.get("resultPackageSha256"),
            "manifestSha256": completion_proof.get("resultPackageManifestSha256"),
            "evidenceId": completion_proof.get("packageEvidenceId"),
            "artifactPayloadMode": "full",
            "includeArtifacts": True,
            "createdAt": completion_proof.get("validationCardGeneratedAt"),
        }
    )


def _completion_proof_validation_evidence(completion_proof: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "ready": True,
            "generatedAt": completion_proof.get("validationCardGeneratedAt"),
            "packageExportId": completion_proof.get("packageExportId"),
            "packageEvidenceId": completion_proof.get("packageEvidenceId"),
            "validationChecksPassed": completion_proof.get("validationChecksPassed"),
            "validationChecksTotal": completion_proof.get("validationChecksTotal"),
            "evidenceBundleReady": completion_proof.get("evidenceBundleReady"),
            "evidenceBundleId": completion_proof.get("evidenceBundleId"),
        }
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
    server: dict[str, Any] | None = None,
    execution: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    report: dict[str, Any] | None = None,
    result_package: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    completion_proof: dict[str, Any] | None = None,
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
                "server": server or {"ready": False},
                "execution": execution or {"ready": False},
                "workflow": workflow or {"ready": False},
                "sampleCache": sample_cache,
                "completionProof": (
                    completion_proof
                    if completion_proof is not None
                    else latest_first_run_completion_proof_evidence(
                        server_id=server_id,
                        run_id=str((run or {}).get("runId") or "").strip(),
                    )
                ),
                "run": run,
                "report": report or {"ready": False},
                "resultPackage": result_package or {"ready": False},
                "validation": validation or {"ready": False},
            },
        }
    }


async def _runner_readiness_gate(server_id: str, *, refresh: bool) -> dict[str, Any]:
    servers_payload = await list_servers_from_request(refresh)
    servers = _mapping_items(_require_wrapped_mapping(servers_payload, "FIRST_RUN_SERVER_LIST_RESPONSE_INVALID").get("items"))
    server = next((item for item in servers if str(item.get("serverId") or "").strip() == server_id), None)
    if server is None:
        server_evidence = _server_evidence(None, server_id=server_id, blocked_code="FIRST_RUN_SERVER_NOT_FOUND")
        return {
            "blocked": True,
            "stage": "connect_remote",
            "nextAction": _blocked_action(
                "CONNECT_REMOTE",
                "FIRST_RUN_SERVER_NOT_FOUND",
                "重新连接远端",
                "当前首跑绑定的远端 server 不存在或已被替换，请重新连接远端 runner。",
                "#runner-readiness",
            ),
            "server": server_evidence,
            "execution": {"ready": False, "blockedCode": "FIRST_RUN_SERVER_NOT_FOUND"},
        }

    server_evidence = _server_evidence(server, server_id=server_id)
    if not bool(server.get("connected")):
        server_evidence = {**server_evidence, "blockedCode": "FIRST_RUN_SERVER_NOT_CONNECTED"}
        return {
            "blocked": True,
            "stage": "connect_remote",
            "nextAction": _blocked_action(
                "CONNECT_REMOTE",
                "FIRST_RUN_SERVER_NOT_CONNECTED",
                "连接远端",
                "远端 runner 当前未连接，请重新连接后继续首跑。",
                "#runner-readiness",
            ),
            "server": server_evidence,
            "execution": {"ready": False, "blockedCode": "FIRST_RUN_SERVER_NOT_CONNECTED"},
        }

    if not bool(server.get("ready")):
        blocked_code = _runner_blocked_code(server)
        server_evidence = {**server_evidence, "blockedCode": blocked_code}
        return {
            "blocked": True,
            "stage": "runner_readiness",
            "nextAction": _blocked_action(
                "ENSURE_RUNNER",
                blocked_code,
                "准备 runner",
                _runner_blocked_detail(server),
                "#runner-readiness",
            ),
            "server": server_evidence,
            "execution": {"ready": False, "blockedCode": blocked_code},
        }

    diagnostics_payload = await get_server_execution_diagnostics_from_request(server_id)
    diagnostics = _require_wrapped_mapping(diagnostics_payload, "FIRST_RUN_EXECUTION_DIAGNOSTICS_RESPONSE_INVALID")
    execution_evidence = _execution_evidence(diagnostics)
    if not bool(execution_evidence.get("ready")):
        blocked_code = str(execution_evidence.get("blockedCode") or "FIRST_RUN_EXECUTION_DIAGNOSTICS_NOT_READY")
        return {
            "blocked": True,
            "stage": "runner_readiness",
            "nextAction": _blocked_action(
                "ENSURE_RUNNER",
                blocked_code,
                "准备 runner",
                str(execution_evidence.get("detail") or "execution diagnostics 未通过。"),
                "#runner-readiness",
            ),
            "server": server_evidence,
            "execution": execution_evidence,
        }

    return {
        "blocked": False,
        "server": server_evidence,
        "execution": execution_evidence,
    }


async def _workflow_example_gate(*, refresh: bool) -> dict[str, Any]:
    catalog_payload = await get_workflow_catalog_from_request(refresh)
    catalog_data = _require_wrapped_mapping(catalog_payload, "FIRST_RUN_WORKFLOW_CATALOG_RESPONSE_INVALID")
    items = _mapping_items(catalog_data.get("items"))
    workflow = next((item for item in items if str(item.get("id") or "").strip() == MOVING_PICTURES_PIPELINE_ID), None)
    evidence = _workflow_evidence(workflow)
    if evidence.get("ready"):
        return {"blocked": False, "workflow": evidence}
    blocked_code = str(evidence.get("blockedCode") or "FIRST_RUN_WORKFLOW_NOT_READY")
    return {
        "blocked": True,
        "workflow": evidence,
        "nextAction": _blocked_action(
            "REFRESH_WORKFLOW",
            blocked_code,
            "刷新首跑示例",
            str(evidence.get("detail") or "workflow catalog 未提供 WorkflowReady 的 Moving Pictures 16S 示例。"),
            "#sample-data",
        ),
    }


def _server_evidence(
    server: dict[str, Any] | None,
    *,
    server_id: str,
    blocked_code: str = "",
) -> dict[str, Any]:
    if not isinstance(server, dict):
        return _compact(
            {
                "ready": False,
                "serverId": server_id,
                "connected": False,
                "runnerReady": False,
                "blockedCode": blocked_code,
            }
        )
    runner = server.get("runner") if isinstance(server.get("runner"), dict) else {}
    return _compact(
        {
            "ready": bool(server.get("connected")) and bool(server.get("ready")),
            "serverId": server.get("serverId") or server_id,
            "label": server.get("label"),
            "connected": bool(server.get("connected")),
            "runnerReady": bool(server.get("ready")) or bool(runner.get("ready")),
            "reasonCode": server.get("reasonCode") or runner.get("reasonCode"),
            "detail": server.get("message") or runner.get("message"),
            "blockedCode": blocked_code,
        }
    )


def _workflow_evidence(workflow: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(workflow, dict):
        return {
            "ready": False,
            "pipelineId": MOVING_PICTURES_PIPELINE_ID,
            "blockedCode": "FIRST_RUN_WORKFLOW_NOT_FOUND",
            "detail": "workflow catalog 缺少 Moving Pictures 16S 首跑示例。",
        }
    ready = bool(workflow.get("runnable"))
    return _compact(
        {
            "ready": ready,
            "pipelineId": workflow.get("id") or MOVING_PICTURES_PIPELINE_ID,
            "name": workflow.get("name"),
            "status": workflow.get("status"),
            "source": workflow.get("source"),
            "version": workflow.get("version"),
            "blockedCode": "" if ready else "FIRST_RUN_WORKFLOW_NOT_READY",
            "detail": "" if ready else _workflow_blocked_detail(workflow),
        }
    )


def _workflow_blocked_detail(workflow: dict[str, Any]) -> str:
    detail = " / ".join(str(workflow.get(key) or "").strip() for key in ("status", "source", "version") if workflow.get(key))
    return detail or "Moving Pictures 16S 示例还未达到 WorkflowReady。"


def _runner_blocked_code(server: dict[str, Any]) -> str:
    runner = server.get("runner") if isinstance(server.get("runner"), dict) else {}
    return str(server.get("reasonCode") or runner.get("reasonCode") or "FIRST_RUN_RUNNER_NOT_READY")


def _runner_blocked_detail(server: dict[str, Any]) -> str:
    runner = server.get("runner") if isinstance(server.get("runner"), dict) else {}
    return str(server.get("message") or runner.get("message") or "远端 runner readiness 未通过，请先准备 runner。")


def _execution_evidence(diagnostics: Any) -> dict[str, Any]:
    data = diagnostics if isinstance(diagnostics, dict) else {}
    if data.get("schemaVersion") != "execution-diagnostics.v1":
        return {
            "ready": False,
            "blockedCode": "FIRST_RUN_EXECUTION_DIAGNOSTICS_SCHEMA_INVALID",
            "detail": "execution diagnostics response must use execution-diagnostics.v1.",
        }
    readiness = data.get("readiness") if isinstance(data.get("readiness"), dict) else {}
    if not readiness:
        return {
            "ready": False,
            "blockedCode": "FIRST_RUN_EXECUTION_DIAGNOSTICS_READINESS_INVALID",
            "detail": "execution diagnostics response must include readiness.",
        }
    blocking_reasons = _mapping_items(readiness.get("blockingReasons"))
    reason_code = str(
        readiness.get("reasonCode")
        or next((item.get("code") for item in blocking_reasons if str(item.get("code") or "").strip()), "")
        or ""
    )
    ready = bool(readiness.get("ok"))
    return _compact(
        {
            "ready": ready,
            "status": readiness.get("status"),
            "reasonCode": reason_code,
            "blockingReasons": blocking_reasons,
            "blockedCode": "" if ready else reason_code or "FIRST_RUN_EXECUTION_DIAGNOSTICS_NOT_READY",
            "detail": "" if ready else _execution_blocked_detail(readiness, blocking_reasons),
        }
    )


def _execution_blocked_detail(readiness: dict[str, Any], blocking_reasons: list[dict[str, Any]]) -> str:
    message = str(
        readiness.get("message")
        or next((item.get("message") for item in blocking_reasons if str(item.get("message") or "").strip()), "")
        or ""
    ).strip()
    if message:
        return f"execution diagnostics 未通过：{message}"
    reason_code = str(readiness.get("reasonCode") or "").strip()
    if reason_code:
        return f"execution diagnostics 未通过：{reason_code}"
    return "execution diagnostics 未通过。"


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


def _first_run_run_blocker(run: dict[str, Any], *, server_id: str) -> str:
    run_server_id = str(run.get("serverId") or "").strip()
    if run_server_id != server_id:
        return "FIRST_RUN_RUN_SERVER_MISMATCH"
    return _official_sample_run_blocker(run)


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
            "serverId": run.get("serverId"),
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


def _ignored_latest_run(
    runs: list[dict[str, Any]],
    latest_eligible_run: dict[str, Any] | None,
    *,
    server_id: str,
) -> dict[str, Any] | None:
    latest_raw = _latest_run(runs)
    if latest_raw is None:
        return None
    latest = _run_summary(latest_raw)
    if latest_eligible_run and latest.get("runId") == latest_eligible_run.get("runId"):
        return None
    return _compact({**latest, "blockingCode": _first_run_run_blocker(latest_raw, server_id=server_id)})


def _run_sort_key(run: dict[str, Any]) -> tuple[str, str]:
    timestamp = (
        str(run.get("lastUpdatedAt") or "")
        or str(run.get("finishedAt") or "")
        or str(run.get("startedAt") or "")
        or str(run.get("submittedAt") or "")
    )
    return (timestamp, str(run.get("runId") or ""))


def _ready_package_evidence(card: dict[str, Any]) -> dict[str, Any]:
    package = card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {}
    return _compact(
        {
            "ready": True,
            "packageExportId": package.get("packageExportId"),
            "sha256": package.get("sha256"),
            "manifestSha256": package.get("manifestSha256"),
            "evidenceId": package.get("evidenceId"),
            "artifactPayloadMode": package.get("artifactPayloadMode"),
            "includeArtifacts": package.get("includeArtifacts"),
            "createdAt": package.get("createdAt"),
            "download": _safe_download_evidence(package.get("download")),
        }
    )


def _safe_download_evidence(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    href = str(value.get("href") or "").strip()
    filename = str(value.get("filename") or "").strip()
    if not href:
        return None
    return _compact({"href": href, "filename": filename})


def _ready_validation_evidence(card: dict[str, Any]) -> dict[str, Any]:
    checks = _mapping_items(card.get("checks"))
    passed = [item for item in checks if item.get("status") == "passed"]
    handoff = card.get("pilotHandoff") if isinstance(card.get("pilotHandoff"), dict) else {}
    bundle = handoff.get("evidenceBundle") if isinstance(handoff.get("evidenceBundle"), dict) else {}
    package = card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {}
    return _compact(
        {
            "ready": True,
            "generatedAt": card.get("generatedAt"),
            "packageExportId": package.get("packageExportId"),
            "packageEvidenceId": package.get("evidenceId"),
            "validationChecksPassed": len(passed),
            "validationChecksTotal": len(checks),
            "evidenceBundleReady": bundle.get("status") == "ready",
            "evidenceBundleId": bundle.get("bundleId"),
        }
    )


def _result_package_evidence(ready: bool, code: str) -> dict[str, Any]:
    if not is_first_run_result_package_blocker(code):
        return {"ready": False}
    return {"ready": ready, "blockedCode": code}


def _action_for_validation_blocker(code: str, detail: str) -> dict[str, str]:
    if code in {"FIRST_RUN_SAMPLE_INPUTS_REQUIRED", "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH", "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"}:
        return _blocked_action("PREPARE_SAMPLE_DATA", code, "重新准备官方样例数据", detail, "#sample-data")
    if code == "FIRST_RUN_WORKFLOW_REVISION_REQUIRED":
        return _blocked_action("ENSURE_RUNNER", code, "升级 runner 并重新提交", detail, "#runner-readiness")
    if code in {
        "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED",
        "FIRST_RUN_REPORT_PREVIEW_REQUIRED",
        FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
        "FIRST_RUN_NOT_SUCCESSFUL",
    }:
        return _blocked_action("INSPECT_FAILED_RUN", code, "检查报告与失败定位", detail, "#run-report")
    if is_first_run_result_package_export_required(code):
        base = first_run_next_action(code, detail)
        return _blocked_action("FINALIZE_FIRST_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))
    if is_first_run_result_package_ledger_mismatch(code):
        base = first_run_next_action(code, detail)
        return _blocked_action("REFRESH_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))
    if code in {"FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED", "FIRST_RUN_PILOT_HANDOFF_REQUIRED"}:
        base = first_run_next_action(code, detail)
        return _blocked_action("FINALIZE_FIRST_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))
    base = first_run_next_action(code, detail)
    return _blocked_action("REFRESH_RUN", code, base["label"], base["detail"], _anchor_target(base["target"]))


def _stage_for_blocker(code: str) -> str:
    if code in {"FIRST_RUN_SAMPLE_INPUTS_REQUIRED", "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH", "FIRST_RUN_SAMPLE_PREP_PROOF_REQUIRED"}:
        return "prepare_sample_data"
    if code in {
        "FIRST_RUN_NOT_SUCCESSFUL",
        "FIRST_RUN_REPORT_PREVIEW_REQUIRED",
        "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED",
        FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
    }:
        return "inspect_failed_run"
    if is_first_run_result_package_blocker(code):
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


def _require_wrapped_mapping(payload: Any, code: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or "data" not in payload or not isinstance(payload.get("data"), dict):
        raise ValueError(code)
    return payload["data"]


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}
