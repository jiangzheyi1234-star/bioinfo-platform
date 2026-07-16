"""Local selection adapter for the shared deterministic FASTQ QC planner."""

from __future__ import annotations

from typing import Any

from core.agent_fastq_qc_planner import build_fastq_qc_plan_proposal_from_capabilities
from core.contracts.agent_fastq_qc import AGENT_FASTQ_QC_TOOL_VERSIONS
from core.contracts.agent_session import AgentPlanProposal, AgentSessionRecord
from core.contracts.capability_bundle import validate_capability_bundle_contract


FASTQ_QC_SUPPORTED_TOOL_VERSIONS = AGENT_FASTQ_QC_TOOL_VERSIONS


def build_fastq_qc_plan_proposal(
    *,
    session: AgentSessionRecord | dict[str, Any],
    capability_graph: dict[str, Any],
) -> AgentPlanProposal:
    """Select exact bundles, then construct the byte-stable canonical proposal."""

    normalized_session = AgentSessionRecord.model_validate(session)
    allowed = set(normalized_session.constraints.allowedToolRevisionIds)
    bundles = capability_graph.get("capabilityBundles")
    if not isinstance(bundles, list):
        raise ValueError("CAPABILITY_BUNDLE_NOT_SELECTABLE: capability graph unavailable")
    fastqc = _select_exact_bundle("fastqc", bundles, allowed)
    multiqc = _select_exact_bundle("multiqc", bundles, allowed)
    return build_fastq_qc_plan_proposal_from_capabilities(
        session=normalized_session,
        fastqc=fastqc,
        multiqc=multiqc,
    )


def _select_exact_bundle(
    profile_id: str,
    bundles: list[Any],
    allowed_revision_ids: set[str],
) -> dict[str, Any]:
    expected_version = FASTQ_QC_SUPPORTED_TOOL_VERSIONS[profile_id]
    matching: list[dict[str, Any]] = []
    for candidate in bundles:
        if not isinstance(candidate, dict) or candidate.get("profileId") != profile_id:
            continue
        validate_capability_bundle_contract(candidate)
        revision_id = str(candidate.get("toolRevisionId") or "").strip()
        if candidate.get("agentSelectable") is not True:
            continue
        if str(candidate.get("version") or "").strip() != expected_version:
            continue
        if allowed_revision_ids and revision_id not in allowed_revision_ids:
            continue
        matching.append(candidate)
    if not matching:
        raise ValueError(
            f"CAPABILITY_BUNDLE_NOT_SELECTABLE: {profile_id}={expected_version}"
        )
    if len(matching) > 1:
        raise ValueError(f"CAPABILITY_BUNDLE_NOT_SELECTABLE: {profile_id} revision ambiguous")
    return matching[0]


__all__ = ["FASTQ_QC_SUPPORTED_TOOL_VERSIONS", "build_fastq_qc_plan_proposal"]
