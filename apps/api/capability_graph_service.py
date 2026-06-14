"""Unified capability graph snapshot for tool discovery and selection."""

from __future__ import annotations

from typing import Any

from apps.api.bio_tool_pack_capability_graph import semantic_capability_graph
from apps.api.tool_candidate_catalog import search_tool_candidates
from apps.api.tool_profile_sources import all_tool_profiles
from apps.api.tool_registry_payload import registered_tools_from_runtime_payload


class CapabilityGraphService:
    """Build a single tool capability view for UI, agents, and validation queues."""

    def snapshot(
        self,
        *,
        query: str = "",
        target_platform: str = "linux-64",
        page: int = 1,
        page_size: int = 50,
        registered_tools: list[dict[str, Any]] | None = None,
        catalog: dict[str, Any] | None = None,
        target_acceptance: dict[str, Any] | None = None,
        prepare_job_queue: dict[str, Any] | None = None,
        agent_selectable_only: bool = False,
    ) -> dict[str, Any]:
        profiles = all_tool_profiles()
        registered = registered_tools or []
        candidate_catalog = catalog if isinstance(catalog, dict) else search_tool_candidates(
            query,
            target_platform=target_platform,
            page=page,
            page_size=page_size,
        )
        graph = semantic_capability_graph(
            profiles=profiles,
            registered_tools=registered,
            agent_selectable_only=agent_selectable_only,
        )
        registered_tools_view = _registered_tools_view(registered)
        agent_selectable_tools = _agent_selectable_tools(registered_tools_view)
        snapshot = {
            "contractVersion": "capability-graph-snapshot-v1",
            "query": str(query or "").strip(),
            "targetPlatform": str(target_platform or "linux-64").strip() or "linux-64",
            "profileCount": len(profiles),
            "packIds": _pack_ids(profiles),
            "catalog": candidate_catalog,
            "semanticGraph": graph,
            "registeredTools": registered_tools_view,
            "registeredToolCounts": _registered_tool_counts(registered),
            "agentSelectableTools": agent_selectable_tools,
            "agentSelectableProfileIds": graph.get("agentSelectableProfileIds", []),
            "selectionPolicy": {
                "sourceOfTruth": "CapabilityGraphSnapshot",
                "readinessSourceOfTruth": "registeredTool.toolContract",
                "canAddStepStates": ["WorkflowReady", "ProductionEnabled"],
                "blockedReason": "WORKFLOW_TOOL_NOT_READY",
            },
        }
        if isinstance(target_acceptance, dict):
            snapshot["targetAcceptance"] = target_acceptance
            snapshot["targetSummary"] = _target_summary(target_acceptance)
            validation_queue = target_acceptance.get("validationQueue")
            if isinstance(validation_queue, dict):
                snapshot["validationQueue"] = validation_queue
            production_queue = target_acceptance.get("productionQueue")
            if isinstance(production_queue, dict):
                snapshot["productionQueue"] = production_queue
        if isinstance(prepare_job_queue, dict):
            snapshot["prepareJobQueue"] = prepare_job_queue
        return snapshot

    def snapshot_from_runtime(
        self,
        *,
        runtime: Any,
        query: str = "",
        target_platform: str = "linux-64",
        page: int = 1,
        page_size: int = 50,
        registered_tools: list[dict[str, Any]] | None = None,
        catalog: dict[str, Any] | None = None,
        target_acceptance: dict[str, Any] | None = None,
        prepare_job_queue: dict[str, Any] | None = None,
        agent_selectable_only: bool = False,
    ) -> dict[str, Any]:
        registered = registered_tools
        if registered is None:
            registered = registered_tools_from_runtime_payload(runtime.list_tools())
        return self.snapshot(
            query=query,
            target_platform=target_platform,
            page=page,
            page_size=page_size,
            registered_tools=registered,
            catalog=catalog,
            target_acceptance=target_acceptance,
            prepare_job_queue=prepare_job_queue,
            agent_selectable_only=agent_selectable_only,
        )


DEFAULT_CAPABILITY_GRAPH_SERVICE = CapabilityGraphService()


def _pack_ids(profiles: tuple[Any, ...]) -> list[str]:
    return sorted({str(profile.pack_id or "builtin").strip() for profile in profiles})


def _registered_tool_counts(tools: list[dict[str, Any]]) -> dict[str, int]:
    valid = [tool for tool in tools if isinstance(tool, dict)]
    workflow_ready = 0
    production_enabled = 0
    for tool in valid:
        contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
        state = str(contract.get("state") or "").strip()
        if contract.get("workflowReady") is True or state in {"WorkflowReady", "ProductionEnabled"}:
            workflow_ready += 1
        if contract.get("productionEnabled") is True or state == "ProductionEnabled":
            production_enabled += 1
    return {
        "total": len(valid),
        "workflowReady": workflow_ready,
        "productionEnabled": production_enabled,
    }


def _registered_tools_view(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(tool) for tool in tools if isinstance(tool, dict)]


def _agent_selectable_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tool for tool in tools if _tool_can_add_step(tool)]


def _tool_can_add_step(tool: dict[str, Any]) -> bool:
    contract = tool.get("toolContract") if isinstance(tool.get("toolContract"), dict) else {}
    state = str(contract.get("state") or "").strip()
    has_revision = bool(str(tool.get("toolRevisionId") or contract.get("toolRevisionId") or "").strip())
    return has_revision and (contract.get("workflowReady") is True or state in {"WorkflowReady", "ProductionEnabled"})


def _target_summary(target_acceptance: dict[str, Any]) -> dict[str, Any]:
    targets = target_acceptance.get("targets") if isinstance(target_acceptance.get("targets"), dict) else {}
    return {
        "complete": bool(target_acceptance.get("complete")),
        "blockedTargets": list(target_acceptance.get("blockedTargets") or []),
        "targets": targets,
    }
