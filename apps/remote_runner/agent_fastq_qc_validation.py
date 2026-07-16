"""Remote canonical trust checks for deterministic FASTQ QC proposals."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from core.agent_fastq_qc_planner import (
    FASTQ_QC_CAPABILITY_PACK_ID,
    build_fastq_qc_plan_proposal_from_capabilities,
    fastq_qc_capability_id,
)
from core.contracts.agent_fastq_qc import (
    AGENT_FASTQ_QC_ADAPTER_ID,
    AGENT_FASTQ_QC_ADAPTER_VERSION,
    AGENT_FASTQ_QC_GOAL_CONTEXT_VERSION,
    AGENT_FASTQ_QC_MODEL_REF,
    AGENT_FASTQ_QC_TOOL_PROFILES,
    AGENT_FASTQ_QC_TOOL_VERSIONS,
    AgentFastqQcGoalContext,
)
from core.contracts.agent_session import AgentPlanProposal

from .capability_bundle_audit import validate_capability_bundle_gate
from .config import RemoteRunnerConfig
from .tool_revisions import fetch_tool_revision
from .tool_rule_template_normalization import normalize_rule_template
from .upload_service import require_materialized_upload


def validate_fastq_qc_materialized_plan(
    cfg: RemoteRunnerConfig,
    *,
    session: dict[str, Any],
    proposal: AgentPlanProposal | dict[str, Any],
    replan: bool = False,
) -> None:
    """Rebuild the canonical draft from trusted ledgers and require exact equality."""

    normalized = AgentPlanProposal.model_validate(proposal)
    raw_goal = session.get("goal") if isinstance(session.get("goal"), dict) else {}
    raw_context = raw_goal.get("context") if isinstance(raw_goal.get("context"), dict) else {}
    fastq_context_claimed = (
        raw_context.get("schemaVersion") == AGENT_FASTQ_QC_GOAL_CONTEXT_VERSION
        or raw_context.get("analysis") == "fastq-qc"
    )
    fastq_adapter_claimed = normalized.planner.adapterId == AGENT_FASTQ_QC_ADAPTER_ID
    if not fastq_context_claimed and not fastq_adapter_claimed:
        return
    if not fastq_context_claimed or not fastq_adapter_claimed:
        raise ValueError("WORKFLOW_FASTQ_QC_ADAPTER_CONTEXT_MISMATCH")
    if replan:
        raise ValueError("WORKFLOW_FASTQ_QC_REPLAN_ADJUSTMENT_UNSUPPORTED")
    if (
        normalized.planner.adapterVersion != AGENT_FASTQ_QC_ADAPTER_VERSION
        or normalized.planner.modelRef != AGENT_FASTQ_QC_MODEL_REF
    ):
        raise ValueError("WORKFLOW_FASTQ_QC_ADAPTER_IDENTITY_INVALID")
    try:
        context = AgentFastqQcGoalContext.model_validate(session["goal"]["context"])
    except (KeyError, TypeError, ValidationError) as exc:
        raise ValueError("INPUT_FASTQ_QC_GOAL_CONTEXT_INVALID") from exc

    expected_upload = context.inputs[0].runtime_payload()
    actual_upload = require_materialized_upload(cfg, context.inputs[0].uploadId)
    if any(actual_upload.get(key) != value for key, value in expected_upload.items()):
        raise ValueError("INPUT_FASTQ_QC_UPLOAD_MANIFEST_MISMATCH")

    if [node.id for node in normalized.draft.nodes] != ["fastqc", "multiqc"]:
        raise ValueError("WORKFLOW_FASTQ_QC_PLAN_NOT_CANONICAL")
    fastqc = _trusted_capability(
        cfg,
        profile_id="fastqc",
        tool_revision_id=normalized.draft.nodes[0].toolRevisionId,
    )
    multiqc = _trusted_capability(
        cfg,
        profile_id="multiqc",
        tool_revision_id=normalized.draft.nodes[1].toolRevisionId,
    )
    expected = build_fastq_qc_plan_proposal_from_capabilities(
        session=session,
        fastqc=fastqc,
        multiqc=multiqc,
    )
    if normalized.runtime_payload() != expected.runtime_payload():
        raise ValueError("WORKFLOW_FASTQ_QC_PLAN_NOT_CANONICAL")


def _trusted_capability(
    cfg: RemoteRunnerConfig,
    *,
    profile_id: str,
    tool_revision_id: str,
) -> dict[str, Any]:
    tool = fetch_tool_revision(cfg, tool_revision_id)
    profile = AGENT_FASTQ_QC_TOOL_PROFILES[profile_id]
    expected_version = AGENT_FASTQ_QC_TOOL_VERSIONS[profile_id]
    expected_tool_id = f"bioconda::{profile_id}"
    if tool is None:
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_IDENTITY_INVALID")
    draft = tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {}
    lock = draft.get("lock") if isinstance(draft.get("lock"), dict) else {}
    identity = {
        "toolId": str(tool.get("id") or tool.get("toolId") or ""),
        "toolRevisionId": str(tool.get("toolRevisionId") or ""),
        "name": str(tool.get("name") or ""),
        "source": str(tool.get("source") or ""),
        "version": str(tool.get("version") or ""),
        "packageSpec": str(tool.get("packageSpec") or ""),
        "targetPlatform": str(tool.get("targetPlatform") or ""),
        "profileId": str(tool.get("profileId") or ""),
        "profileVersion": tool.get("profileVersion"),
        "packId": str(tool.get("packId") or ""),
    }
    expected_identity = {
        "toolId": expected_tool_id,
        "toolRevisionId": tool_revision_id,
        "name": profile_id,
        "source": "bioconda",
        "version": expected_version,
        "packageSpec": str(profile["packageSpec"]),
        "targetPlatform": "linux-64",
        "profileId": profile_id,
        "profileVersion": profile["profileVersion"],
        "packId": FASTQ_QC_CAPABILITY_PACK_ID,
    }
    if identity != expected_identity:
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_IDENTITY_INVALID")
    if tool.get("environmentSpec") not in (None, {}) or tool.get("environmentLock") not in (
        None,
        {},
    ):
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_ENVIRONMENT_LOCK_INVALID")
    if (
        draft.get("source") != "h2ometa-tool-profile"
        or draft.get("requiresUserCompletion") is not False
        or lock.get("type") != "h2ometa-tool-profile"
        or lock.get("profileId") != profile_id
        or lock.get("profileVersion") != profile["profileVersion"]
        or lock.get("packageSpec") != profile["packageSpec"]
        or lock.get("version") != expected_version
        or lock.get("source") != "bioconda"
        or lock.get("packageName") != profile_id
        or lock.get("wrapperIdentifier") != profile["wrapper"]
    ):
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_PROFILE_LOCK_INVALID")

    rule_template = normalize_rule_template(tool.get("ruleTemplate"), required=True)
    draft_template = normalize_rule_template(draft.get("ruleTemplate"), required=True)
    expected_digest = str(profile["ruleTemplateSha256"])
    if (
        _canonical_digest(rule_template) != expected_digest
        or _canonical_digest(draft_template) != expected_digest
    ):
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_PROFILE_LOCK_INVALID")
    validate_capability_bundle_gate(tool)
    return {
        "profileId": profile_id,
        "toolRevisionId": tool_revision_id,
        "version": expected_version,
        "capabilityId": fastq_qc_capability_id(profile_id, tool_revision_id),
        "inputs": _ports(rule_template.get("inputs")),
        "outputs": _ports(rule_template.get("outputs")),
        "parameters": dict(rule_template.get("params") or {}),
    }


def _ports(value: Any) -> list[dict[str, Any]]:
    ports: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        port = {
            "name": str(item.get("name") or "").strip(),
            "type": str(item.get("type") or "").strip(),
            "kind": str(item.get("kind") or "").strip(),
            "mimeType": str(item.get("mimeType") or "").strip(),
            "data": str(item.get("data") or "").strip(),
            "format": str(item.get("format") or "").strip(),
            "operation": str(item.get("operation") or "").strip(),
            "resource": str(item.get("resource") or "").strip(),
            "required": bool(item.get("required")),
        }
        path = str(item.get("path") or "").strip()
        if path:
            port["path"] = path
        ports.append(port)
    return ports


def _canonical_digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = ["validate_fastq_qc_materialized_plan"]
