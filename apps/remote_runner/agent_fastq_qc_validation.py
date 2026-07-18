"""Remote canonical trust checks for deterministic FASTQ QC proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

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
    fastq_qc_manifest_digest,
)
from core.contracts.agent_session import AgentPlanProposal, AgentSessionModel

from .capability_bundle_audit import validate_capability_bundle_gate
from .config import RemoteRunnerConfig
from .tool_revisions import fetch_tool_revision
from .tool_rule_template_normalization import normalize_rule_template
from .upload_service import require_materialized_upload


class FastqQcMaterializedInputManifest(AgentSessionModel):
    """Path-free upload identity proven against the materialized bytes."""

    model_config = ConfigDict(frozen=True)

    uploadId: str
    role: Literal["reads"]
    filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sizeBytes: int = Field(ge=1)
    mimeType: Literal["text/plain"]


class FastqQcTrustedToolFact(AgentSessionModel):
    """Path-free identity facts retained after canonical ToolRevision validation."""

    model_config = ConfigDict(frozen=True)

    stepId: Literal["fastqc", "multiqc"]
    capabilityId: str
    toolId: str
    toolRevisionId: str
    name: str
    source: Literal["bioconda"]
    version: str
    packageSpec: str
    targetPlatform: Literal["linux-64"]
    profileId: Literal["fastqc", "multiqc"]
    profileVersion: int = Field(ge=1)
    packId: str
    wrapperIdentifier: str
    ruleTemplateSha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class FastqQcAuthoritySnapshot:
    """One coherent, typed observation of all FASTQ QC planning authority."""

    context: AgentFastqQcGoalContext
    materialized_input: FastqQcMaterializedInputManifest
    input_manifest_digest: str
    canonical_proposal: AgentPlanProposal
    trusted_tools: tuple[FastqQcTrustedToolFact, ...]


@dataclass(frozen=True, slots=True)
class _TrustedCapability:
    planner_capability: dict[str, Any]
    tool_fact: FastqQcTrustedToolFact


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
    raw_context = (
        raw_goal.get("context") if isinstance(raw_goal.get("context"), dict) else {}
    )
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
    _require_fastq_qc_authority_snapshot(cfg, session=session, normalized=normalized)


def require_fastq_qc_authority_snapshot(
    cfg: RemoteRunnerConfig,
    *,
    session: dict[str, Any],
    plan: AgentPlanProposal | dict[str, Any],
) -> FastqQcAuthoritySnapshot:
    """Require the exact FASTQ QC authority set and return its safe snapshot.

    Unlike the compatibility validator, this public observation boundary never
    treats a generic session or planner as an implicit no-op.
    """

    normalized = AgentPlanProposal.model_validate(plan)
    raw_goal = session.get("goal") if isinstance(session.get("goal"), dict) else {}
    raw_context = (
        raw_goal.get("context") if isinstance(raw_goal.get("context"), dict) else {}
    )
    fastq_context_claimed = (
        raw_context.get("schemaVersion") == AGENT_FASTQ_QC_GOAL_CONTEXT_VERSION
        or raw_context.get("analysis") == "fastq-qc"
    )
    fastq_adapter_claimed = normalized.planner.adapterId == AGENT_FASTQ_QC_ADAPTER_ID
    if not fastq_context_claimed or not fastq_adapter_claimed:
        raise ValueError("WORKFLOW_FASTQ_QC_ADAPTER_CONTEXT_MISMATCH")
    return _require_fastq_qc_authority_snapshot(
        cfg,
        session=session,
        normalized=normalized,
    )


def _require_fastq_qc_authority_snapshot(
    cfg: RemoteRunnerConfig,
    *,
    session: dict[str, Any],
    normalized: AgentPlanProposal,
) -> FastqQcAuthoritySnapshot:
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
    materialized_input = FastqQcMaterializedInputManifest.model_validate(
        {
            "uploadId": actual_upload["uploadId"],
            "role": "reads",
            "filename": actual_upload["filename"],
            "sha256": actual_upload["sha256"],
            "sizeBytes": actual_upload["sizeBytes"],
            "mimeType": actual_upload["mimeType"],
        }
    )

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
        fastqc=fastqc.planner_capability,
        multiqc=multiqc.planner_capability,
    )
    if not _strict_json_equal(
        normalized.runtime_payload(),
        expected.runtime_payload(),
    ):
        raise ValueError("WORKFLOW_FASTQ_QC_PLAN_NOT_CANONICAL")
    return FastqQcAuthoritySnapshot(
        context=context,
        materialized_input=materialized_input,
        input_manifest_digest=fastq_qc_manifest_digest(context),
        canonical_proposal=expected,
        trusted_tools=(fastqc.tool_fact, multiqc.tool_fact),
    )


def _trusted_capability(
    cfg: RemoteRunnerConfig,
    *,
    profile_id: str,
    tool_revision_id: str,
) -> _TrustedCapability:
    tool = fetch_tool_revision(cfg, tool_revision_id)
    profile = AGENT_FASTQ_QC_TOOL_PROFILES[profile_id]
    expected_version = AGENT_FASTQ_QC_TOOL_VERSIONS[profile_id]
    expected_tool_id = f"bioconda::{profile_id}"
    if tool is None:
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_IDENTITY_INVALID")
    draft = (
        tool.get("ruleSpecDraft") if isinstance(tool.get("ruleSpecDraft"), dict) else {}
    )
    lock = draft.get("lock") if isinstance(draft.get("lock"), dict) else {}
    expected_identity = {
        "toolId": expected_tool_id,
        "toolRevisionId": tool_revision_id,
        "name": profile_id,
        "source": "bioconda",
        "version": expected_version,
        "packageSpec": profile["packageSpec"],
        "targetPlatform": "linux-64",
        "profileId": profile_id,
        "profileVersion": profile["profileVersion"],
        "packId": FASTQ_QC_CAPABILITY_PACK_ID,
    }
    stored_identity = {
        "id": tool.get("id"),
        "toolId": tool.get("toolId"),
        "toolRevisionId": tool.get("toolRevisionId"),
        "name": tool.get("name"),
        "source": tool.get("source"),
        "version": tool.get("version"),
        "packageSpec": tool.get("packageSpec"),
        "targetPlatform": tool.get("targetPlatform"),
        "profileId": tool.get("profileId"),
        "profileVersion": tool.get("profileVersion"),
        "packId": tool.get("packId"),
    }
    expected_stored_identity = {
        "id": expected_tool_id,
        **expected_identity,
    }
    if not _strict_json_equal(stored_identity, expected_stored_identity):
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_IDENTITY_INVALID")
    if tool.get("environmentSpec") not in (None, {}) or tool.get(
        "environmentLock"
    ) not in (
        None,
        {},
    ):
        raise ValueError("WORKFLOW_FASTQ_QC_TOOL_ENVIRONMENT_LOCK_INVALID")
    stored_lock_identity = {
        "type": lock.get("type"),
        "profileId": lock.get("profileId"),
        "profileVersion": lock.get("profileVersion"),
        "packageSpec": lock.get("packageSpec"),
        "version": lock.get("version"),
        "source": lock.get("source"),
        "packageName": lock.get("packageName"),
        "wrapperIdentifier": lock.get("wrapperIdentifier"),
    }
    expected_lock_identity = {
        "type": "h2ometa-tool-profile",
        "profileId": profile_id,
        "profileVersion": profile["profileVersion"],
        "packageSpec": profile["packageSpec"],
        "version": expected_version,
        "source": "bioconda",
        "packageName": profile_id,
        "wrapperIdentifier": profile["wrapper"],
    }
    if (
        draft.get("source") != "h2ometa-tool-profile"
        or draft.get("requiresUserCompletion") is not False
        or not _strict_json_equal(stored_lock_identity, expected_lock_identity)
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
    capability_id = fastq_qc_capability_id(profile_id, tool_revision_id)
    planner_capability = {
        "profileId": profile_id,
        "toolRevisionId": tool_revision_id,
        "version": expected_version,
        "capabilityId": capability_id,
        "inputs": _ports(rule_template.get("inputs")),
        "outputs": _ports(rule_template.get("outputs")),
        "parameters": dict(rule_template.get("params") or {}),
    }
    tool_fact = FastqQcTrustedToolFact.model_validate(
        {
            "stepId": profile_id,
            "capabilityId": capability_id,
            **expected_identity,
            "wrapperIdentifier": str(profile["wrapper"]),
            "ruleTemplateSha256": expected_digest,
        }
    )
    return _TrustedCapability(
        planner_capability=planner_capability,
        tool_fact=tool_fact,
    )


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
    raw = _canonical_json(value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return _canonical_json(left) == _canonical_json(right)
    except (TypeError, ValueError):
        return False


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "FastqQcAuthoritySnapshot",
    "FastqQcMaterializedInputManifest",
    "FastqQcTrustedToolFact",
    "require_fastq_qc_authority_snapshot",
    "validate_fastq_qc_materialized_plan",
]
