"""Safe report evidence projection for First Successful Run status."""

from __future__ import annotations

from typing import Any

from apps.api.workflow_first_run_report_interpretation import FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED
from apps.api.workflow_first_run_result_package_contract import is_first_run_result_package_export_required
from apps.api.workflow_first_run_service import (
    WorkflowFirstRunValidationCardUnavailableError,
    build_first_run_report_evidence_from_request,
)


def ready_report_evidence(card: dict[str, Any]) -> dict[str, Any]:
    interpretation = card.get("reportInterpretation") if isinstance(card.get("reportInterpretation"), dict) else {}
    outputs = mapping_items(interpretation.get("outputs"))
    return public_report_evidence(
        {
            "ready": interpretation.get("status") == "ready",
            "outputs": [item.get("name") for item in outputs],
            "metrics": mapping_items(interpretation.get("metrics")),
        }
    )


def report_evidence(ready: bool, code: str) -> dict[str, Any]:
    if code not in {
        "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED",
        "FIRST_RUN_REPORT_PREVIEW_REQUIRED",
        FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
    }:
        return {"ready": False}
    return {"ready": ready, "blockedCode": code}


async def report_evidence_for_package_blocker(
    code: str,
    *,
    run_id: str,
    server_id: str,
) -> dict[str, Any]:
    if not is_first_run_result_package_export_required(code):
        return report_evidence(False, code)
    try:
        return unwrap_data(
            await build_first_run_report_evidence_from_request(run_id, server_id=server_id),
            {},
        )
    except WorkflowFirstRunValidationCardUnavailableError as exc:
        blocked_code = error_code(exc)
        return {**report_evidence(False, blocked_code), "detail": str(exc)}


def public_report_evidence(report: dict[str, Any]) -> dict[str, Any]:
    metrics = [
        compact(
            {
                "metricId": item.get("metricId"),
                "label": item.get("label"),
                "value": item.get("value"),
                "displayValue": item.get("displayValue"),
                "source": item.get("source"),
            }
        )
        for item in mapping_items(report.get("metrics"))
    ]
    return compact(
        {
            "ready": report.get("ready") is True,
            "blockedCode": report.get("blockedCode"),
            "outputs": [str(item) for item in report.get("outputs") or [] if str(item or "").strip()],
            "metrics": metrics,
        }
    )


def report_blocked_code(report: dict[str, Any]) -> str:
    code = str(report.get("blockedCode") or "")
    return code if code in {
        "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED",
        "FIRST_RUN_REPORT_PREVIEW_REQUIRED",
        FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
    } else ""


def mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in ("", None, [], {})}


def unwrap_data(payload: Any, default: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload if payload is not None else default


def error_code(exc: WorkflowFirstRunValidationCardUnavailableError) -> str:
    return str(exc).split(":", 1)[0].strip() or "FIRST_RUN_STATUS_BLOCKED"
