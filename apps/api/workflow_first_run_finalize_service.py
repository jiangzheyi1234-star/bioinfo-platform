"""First Successful Run finalization orchestration."""

from __future__ import annotations

from typing import Any

from apps.api.execution_query_service import export_result_package_from_request
from apps.api.models import ApiRequest, ResultPackageExportRequest
from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_validation_card_from_request,
)


FIRST_RUN_FINALIZATION_SCHEMA_VERSION = "h2ometa.first-run.finalization.v1"
_PACKAGE_RECOVERABLE_CODES = {
    "FIRST_RUN_FULL_RESULT_PACKAGE_REQUIRED",
    "FIRST_RUN_RESULT_PACKAGE_DOWNLOAD_REQUIRED",
    "FIRST_RUN_RESULT_PACKAGE_HASH_REQUIRED",
    "FIRST_RUN_RESULT_PACKAGE_REQUIRED",
}


class WorkflowFirstRunFinalizeRequest(ApiRequest):
    serverId: str | None = None
    actor: str | None = None


async def finalize_first_run_from_request(
    run_id: str,
    request: WorkflowFirstRunFinalizeRequest,
) -> dict[str, Any]:
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return _blocked("FIRST_RUN_RUN_ID_REQUIRED", "runId is required")

    server_id = request.serverId
    try:
        card = (await build_first_run_validation_card_from_request(normalized_run_id, server_id=server_id))["data"]
        return _ready(card, package_action="reused")
    except WorkflowFirstRunValidationCardUnavailableError as exc:
        code = _error_code(exc)
        if code not in _PACKAGE_RECOVERABLE_CODES:
            return _blocked(code, str(exc))

    result_id = _canonical_result_id_for_run(normalized_run_id)
    exported = await export_result_package_from_request(
        result_id,
        ResultPackageExportRequest(
            serverId=server_id,
            includeArtifacts=True,
            actor=request.actor or "first-run-finalize",
        ),
    )
    try:
        card = (await build_first_run_validation_card_from_request(normalized_run_id, server_id=server_id))["data"]
    except WorkflowFirstRunValidationCardUnavailableError as exc:
        return _blocked(_error_code(exc), str(exc), result_package=_unwrap_data(exported))
    return _ready(card, package_action="exported")


def _ready(card: dict[str, Any], *, package_action: str) -> dict[str, Any]:
    handoff = _pilot_handoff(card)
    return {
        "data": {
            "schemaVersion": FIRST_RUN_FINALIZATION_SCHEMA_VERSION,
            "status": "ready",
            "packageAction": package_action,
            "evidenceBundle": handoff["evidenceBundle"],
            "pilotHandoff": handoff,
            "resultPackage": card.get("resultPackage") if isinstance(card.get("resultPackage"), dict) else {},
            "validationCard": card,
        }
    }


def _blocked(code: str, detail: str, *, result_package: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schemaVersion": FIRST_RUN_FINALIZATION_SCHEMA_VERSION,
        "status": "blocked",
        "nextAction": _next_action(code, detail),
    }
    if result_package:
        data["resultPackage"] = result_package
    return {"data": data}


def _next_action(code: str, detail: str) -> dict[str, str]:
    if code == "FIRST_RUN_NOT_SUCCESSFUL":
        target = "/workflows/first-run#run-report"
        label = "等待首跑成功完成"
    elif code == "FIRST_RUN_WORKFLOW_REVISION_REQUIRED":
        target = "/workflows/first-run#runner-readiness"
        label = "升级 runner 并重新提交"
    elif code == "FIRST_RUN_REPORT_PREVIEW_REQUIRED":
        target = "/workflows/first-run#run-report"
        label = "检查报告预览"
    elif code == "FIRST_RUN_SAMPLE_INPUTS_REQUIRED" or code == "FIRST_RUN_SAMPLE_INPUTS_INTEGRITY_MISMATCH":
        target = "/workflows/first-run#sample-data"
        label = "重新准备官方样例数据"
    elif code == "FIRST_RUN_PILOT_HANDOFF_REQUIRED" or code == "FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED":
        target = "/workflows/first-run#evidence-bundle"
        label = "重新生成首跑验证卡"
    else:
        target = "/workflows/first-run"
        label = "返回首跑向导"
    return {
        "code": code or "FIRST_RUN_FINALIZATION_BLOCKED",
        "detail": detail,
        "label": label,
        "target": target,
    }


def _pilot_handoff(card: dict[str, Any]) -> dict[str, Any]:
    handoff = card.get("pilotHandoff") if isinstance(card.get("pilotHandoff"), dict) else None
    if handoff:
        if not isinstance(handoff.get("evidenceBundle"), dict):
            raise WorkflowFirstRunValidationCardUnavailableError(
                "FIRST_RUN_EVIDENCE_BUNDLE_REQUIRED: first-run pilotHandoff must include evidenceBundle"
            )
        return handoff
    raise WorkflowFirstRunValidationCardUnavailableError(
        "FIRST_RUN_PILOT_HANDOFF_REQUIRED: first-run validation card must include pilotHandoff"
    )


def _canonical_result_id_for_run(run_id: str) -> str:
    return run_id if run_id.startswith("res_") else f"res_{run_id}"


def _error_code(exc: WorkflowFirstRunValidationCardUnavailableError) -> str:
    return str(exc).split(":", 1)[0].strip() or "FIRST_RUN_FINALIZATION_BLOCKED"


def _unwrap_data(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}
