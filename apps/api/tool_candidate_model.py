"""Shared candidate fields for heterogeneous tool catalog sources."""

from __future__ import annotations

from typing import Any


def conda_tool_candidate_fields(tool: dict[str, Any], *, rule_spec_draft: dict[str, Any] | None) -> dict[str, Any]:
    source = str(tool.get("source") or "").strip()
    name = str(tool.get("name") or "").strip()
    candidate_id = str(tool.get("id") or "").strip() or f"{source}::{name}"
    source_ref = {
        "type": "conda-package",
        "channel": source,
        "name": name,
    }
    source_url = str(tool.get("sourceUrl") or "").strip()
    if source_url:
        source_ref["url"] = source_url
    return {
        "candidateId": candidate_id,
        "candidateKind": "conda-package",
        "sourceRef": source_ref,
        "contractState": contract_state(tool, rule_spec_draft=rule_spec_draft),
        "qualityTier": quality_tier(tool, rule_spec_draft=rule_spec_draft),
    }


def snakemake_wrapper_candidate_fields(wrapper: dict[str, Any]) -> dict[str, Any]:
    wrapper_identifier = str(wrapper.get("wrapperIdentifier") or "").strip()
    wrapper_repository = str(wrapper.get("wrapperRepository") or "").strip()
    wrapper_ref = str(wrapper.get("wrapperRef") or "").strip()
    wrapper_path = str(wrapper.get("wrapperPath") or "").strip()
    source_ref = {
        "type": "snakemake-wrapper",
        "repository": wrapper_repository,
        "ref": wrapper_ref,
        "path": wrapper_path,
    }
    wrapper_url = str(wrapper.get("wrapperUrl") or "").strip()
    if wrapper_url:
        source_ref["url"] = wrapper_url
    draft = wrapper.get("ruleSpecDraft") if isinstance(wrapper.get("ruleSpecDraft"), dict) else None
    return {
        "candidateId": f"snakemake-wrapper::{wrapper_identifier}",
        "candidateKind": "snakemake-wrapper",
        "sourceRef": source_ref,
        "contractState": contract_state(wrapper, rule_spec_draft=draft),
        "qualityTier": quality_tier(wrapper, rule_spec_draft=draft),
    }


def tool_profile_candidate_fields(profile: Any) -> dict[str, Any]:
    profile_id = str(profile.profile_id).strip()
    version = str(profile.version).strip()
    return {
        "candidateId": f"h2ometa-tool-profile::{profile_id}",
        "candidateKind": "h2ometa-tool-profile",
        "sourceRef": {
            "type": "h2ometa-tool-profile",
            "profileId": profile_id,
            "version": version,
        },
        "contractState": "SnakemakeRenderable",
        "qualityTier": "draft-runnable",
    }


def quality_tier(record: dict[str, Any], *, rule_spec_draft: dict[str, Any] | None) -> str:
    contract = record.get("toolContract")
    if isinstance(contract, dict):
        if contract.get("productionEnabled") is True or contract.get("state") == "ProductionEnabled":
            return "production-enabled"
        if contract.get("workflowReady") is True or contract.get("state") == "WorkflowReady":
            return "workflow-ready"
    if rule_spec_draft and rule_spec_draft.get("requiresUserCompletion") is False:
        return "draft-runnable"
    return "discovered"


def contract_state(record: dict[str, Any], *, rule_spec_draft: dict[str, Any] | None) -> str:
    contract = record.get("toolContract")
    if isinstance(contract, dict):
        state = str(contract.get("state") or "").strip()
        if state:
            return state
        if contract.get("productionEnabled") is True:
            return "ProductionEnabled"
        if contract.get("workflowReady") is True:
            return "WorkflowReady"
    if rule_spec_draft and rule_spec_draft.get("requiresUserCompletion") is False:
        return "SnakemakeRenderable"
    return "Discovered"
