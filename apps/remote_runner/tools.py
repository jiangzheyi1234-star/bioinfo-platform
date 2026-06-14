from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .evidence_storage import append_evidence_event
from .production_evidence import normalize_production_evidence_type, validate_production_evidence_run
from .storage import delete_tool, fetch_tool, get_connection, list_tools, now_iso, upsert_tool
from .tool_capability_normalization import normalize_tool_capabilities
from .tool_rule_template_normalization import normalize_rule_template
from .tool_contract import build_tool_contract, default_contract_status, normalize_contract_status
from .tool_package_identity import normalize_package_identity
from .tools_errors import ToolNotFoundError, ToolProductionConflictError, ToolRegistryError


ALLOWED_SOURCES = {"bioconda", "conda-forge"}


def list_registered_tools(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    return list_tools(cfg)


def add_registered_tool(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_tool_manifest(payload)
    item["ruleTemplate"] = normalize_rule_template(item.get("ruleTemplate"), required=False)
    if _rule_spec_draft_requires_completion(item.get("ruleSpecDraft")) and item["ruleTemplate"]:
        raise ToolRegistryError("TOOL_RULE_DRAFT_CANNOT_HAVE_CONFIRMED_TEMPLATE")
    item["capabilities"] = normalize_tool_capabilities(item.get("capabilities"))
    item["contractStatus"] = default_contract_status()
    item["status"] = "declared"
    item["message"] = "Tool declared."
    _classify_added_tool(item)
    return upsert_tool(cfg, item)


def update_registered_tool_rule_template(
    cfg: RemoteRunnerConfig,
    tool_id: str,
    rule_template: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    item = fetch_tool(cfg, normalized)
    if item is None:
        raise ToolNotFoundError("TOOL_NOT_FOUND")
    item["ruleTemplate"] = normalize_rule_template(rule_template, required=True)
    item["ruleSpecDraft"] = {}
    item["contractStatus"] = default_contract_status()
    item["status"] = "declared"
    item["message"] = "RuleSpec saved."
    item["toolRevisionId"] = ""
    item["revision"] = 0
    item["publishedAt"] = None
    return upsert_tool(cfg, item)


def remove_registered_tool(cfg: RemoteRunnerConfig, tool_id: str) -> None:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    try:
        delete_tool(cfg, normalized)
    except KeyError as exc:
        raise ToolNotFoundError("TOOL_NOT_FOUND") from exc


def mark_registered_tool_production_enabled(
    cfg: RemoteRunnerConfig,
    tool_id: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(tool_id or "").strip()
    if not normalized:
        raise ToolRegistryError("TOOL_ID_REQUIRED")
    item = fetch_tool(cfg, normalized)
    if item is None:
        raise ToolNotFoundError("TOOL_NOT_FOUND")

    status = normalize_contract_status(item.get("contractStatus"))
    item["contractStatus"] = status
    contract = build_tool_contract(item)
    output_status = str(status.get("outputValidation", {}).get("status") or "")
    if not bool((contract.get("requirements") or {}).get("outputValidated")) and output_status != "passed":
        raise ToolProductionConflictError("TOOL_PRODUCTION_REQUIRES_OUTPUT_VALIDATION")
    if not bool(contract.get("workflowReady")):
        raise ToolProductionConflictError("TOOL_PRODUCTION_REQUIRES_WORKFLOW_READY")

    accepted = dict(evidence or {})
    run_id = str(accepted.get("runId") or "").strip()
    if not run_id:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_RUN_ID_REQUIRED")
    message = str(accepted.get("message") or "").strip()
    if not message:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_MESSAGE_REQUIRED")
    evidence_type = normalize_production_evidence_type(accepted.get("evidenceType"))
    accepted["evidenceType"] = evidence_type
    tool_revision_id = str(item.get("toolRevisionId") or "").strip()
    if not tool_revision_id:
        raise ToolProductionConflictError("TOOL_PRODUCTION_REQUIRES_TOOL_REVISION")
    artifact_summary = validate_production_evidence_run(
        cfg,
        accepted,
        tool_revision_id=tool_revision_id,
    )
    checked_at = now_iso()
    evidence_event = _record_production_evidence_event(
        cfg,
        tool_id=normalized,
        tool_revision_id=tool_revision_id,
        accepted=accepted,
        artifact_summary=artifact_summary,
        checked_at=checked_at,
    )
    production = {
        "status": "passed",
        "code": "PRODUCTION_ACCEPTED",
        "message": message,
        "checkedAt": checked_at,
        "runId": run_id,
        "evidenceId": evidence_event["eventId"],
    }
    for key in (
        "logPath",
        "evidenceType",
        "databaseId",
        "templateId",
        "role",
        "artifactName",
    ):
        value = str(accepted.get(key) or "").strip()
        if value:
            production[key] = value
    production.update(artifact_summary)
    status["production"] = production
    item["contractStatus"] = status
    item["status"] = "declared"
    item["message"] = message
    return upsert_tool(cfg, item)


def _record_production_evidence_event(
    cfg: RemoteRunnerConfig,
    *,
    tool_id: str,
    tool_revision_id: str,
    accepted: dict[str, Any],
    artifact_summary: dict[str, str],
    checked_at: str,
) -> dict[str, Any]:
    payload = {
        "toolId": tool_id,
        "toolRevisionId": tool_revision_id,
        "runId": str(accepted.get("runId") or ""),
        "evidenceType": str(accepted.get("evidenceType") or ""),
        "message": str(accepted.get("message") or ""),
        "logPath": str(accepted.get("logPath") or ""),
        "databaseId": str(accepted.get("databaseId") or ""),
        "templateId": str(accepted.get("templateId") or ""),
        "role": str(accepted.get("role") or ""),
        "artifactName": str(accepted.get("artifactName") or ""),
        "targetPlatform": str(accepted.get("targetPlatform") or ""),
        "environmentLock": accepted.get("environmentLock") if isinstance(accepted.get("environmentLock"), dict) else {},
        "inputScope": accepted.get("inputScope") if isinstance(accepted.get("inputScope"), dict) else {},
        "artifactDigest": str(accepted.get("artifactDigest") or ""),
        "policyVersion": str(accepted.get("policyVersion") or ""),
        **artifact_summary,
    }
    with get_connection(cfg) as connection:
        event = append_evidence_event(
            connection,
            event_type="tool.production.acceptance.v1",
            schema_name="ToolProductionAcceptanceEvidence",
            subject_kind="tool",
            subject_id=tool_id,
            payload=payload,
            occurred_at=checked_at,
        )
        connection.commit()
    return event


def _normalize_tool_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "").strip()
    name = str(payload.get("name") or "").strip()
    if source not in ALLOWED_SOURCES:
        raise ToolRegistryError("TOOL_SOURCE_UNSUPPORTED")
    if not name:
        raise ToolRegistryError("TOOL_NAME_REQUIRED")

    package_identity = normalize_package_identity(
        source=source,
        name=name,
        version=str(payload.get("version") or ""),
        package_spec=str(payload.get("packageSpec") or ""),
    )

    tool_id = str(payload.get("id") or f"{source}::{name}").strip()
    return {
        "id": tool_id,
        "name": name,
        "source": source,
        "sourceLabel": str(payload.get("sourceLabel") or source),
        "version": package_identity["version"],
        "packageSpec": package_identity["packageSpec"],
        "summary": str(payload.get("summary") or ""),
        "targetPlatform": str(payload.get("targetPlatform") or "linux-64"),
        "targetPlatformSupported": bool(payload.get("targetPlatformSupported")),
        "platforms": [str(item) for item in (payload.get("platforms") or []) if str(item).strip()],
        "sourceUrl": str(payload.get("sourceUrl") or ""),
        "testCommand": str(payload.get("testCommand") or ""),
        "ruleTemplate": payload.get("ruleTemplate") or {},
        "ruleSpecDraft": payload.get("ruleSpecDraft") or {},
        "capabilities": payload.get("capabilities") or [],
        "snakemakeWrappers": list(payload.get("snakemakeWrappers") or []),
        "status": str(payload.get("status") or "declared"),
        "message": str(payload.get("message") or "Tool declared."),
    }


def _rule_spec_draft_requires_completion(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("requiresUserCompletion") is True


def _classify_added_tool(item: dict[str, Any]) -> None:
    draft = item.get("ruleSpecDraft") if isinstance(item.get("ruleSpecDraft"), dict) else {}
    if not _rule_spec_draft_requires_completion(draft):
        return
    source = str(draft.get("source") or "").strip()
    if source == "snakemake-wrapper":
        item["status"] = "wrapper_draft"
        item["message"] = "Wrapper draft saved. Complete RuleSpec before validation."
    elif source == "conda-package":
        item["status"] = "dependency_only"
        item["message"] = "Dependency saved without runnable RuleSpec."
