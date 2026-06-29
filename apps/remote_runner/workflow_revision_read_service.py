"""Read API for immutable WorkflowRevision evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .route_utils import authorized_config, data_response, run_sync
from .route_headers import AuthorizationHeader
from .workflow_revision_storage import fetch_workflow_revision


async def get_workflow_revision_from_request(
    workflow_revision_id: str,
    authorization: AuthorizationHeader = None,
) -> dict[str, Any]:
    cfg = await authorized_config(authorization, action="workflow_revision.read")
    revision = await run_sync(fetch_workflow_revision, cfg, workflow_revision_id)
    if revision is None:
        raise ValueError(f"WORKFLOW_REVISION_NOT_FOUND: {workflow_revision_id}")
    return data_response(_public_workflow_revision(revision))


def _public_workflow_revision(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflowRevisionId": revision.get("workflowRevisionId"),
        "contentHash": revision.get("contentHash"),
        "runtimeLockSha256": _sha256_json(revision.get("runtimeLock")) if isinstance(revision.get("runtimeLock"), dict) else "",
        "draftId": revision.get("draftId"),
        "draftRevision": revision.get("draftRevision"),
        "manifest": _public_manifest(revision.get("manifest")),
        "graphSnapshot": _public_graph_snapshot(revision.get("graphSnapshot")),
        "runtimeLock": _public_runtime_lock(revision.get("runtimeLock")),
        "compiler": revision.get("compiler") if isinstance(revision.get("compiler"), dict) else {},
        "createdBy": revision.get("createdBy"),
        "createdAt": revision.get("createdAt"),
    }


def _public_manifest(value: Any) -> dict[str, Any]:
    manifest = value if isinstance(value, dict) else {}
    return {
        "schemaVersion": manifest.get("schemaVersion"),
        "pipelineId": manifest.get("pipelineId"),
        "pipelineVersion": manifest.get("pipelineVersion"),
        "source": manifest.get("source"),
        "snakefile": manifest.get("snakefile"),
        "layout": manifest.get("layout") if isinstance(manifest.get("layout"), dict) else None,
        "runSpecSha256": manifest.get("runSpecSha256"),
        "files": [_public_file(item) for item in _mapping_items(manifest.get("files"))],
        "toolRevisions": [_public_tool_revision(item) for item in _mapping_items(manifest.get("toolRevisions"))],
    }


def _public_file(item: dict[str, Any]) -> dict[str, Any]:
    return _compact(
        {
            "path": item.get("path"),
            "sha256": item.get("sha256"),
        }
    )


def _public_tool_revision(item: dict[str, Any]) -> dict[str, Any]:
    environment_lock = item.get("environmentLock") if isinstance(item.get("environmentLock"), dict) else {}
    return _compact(
        {
            "toolRevisionId": item.get("toolRevisionId"),
            "toolId": item.get("toolId"),
            "name": item.get("name"),
            "version": item.get("version"),
            "packageSpec": item.get("packageSpec"),
            "environmentLock": _compact(
                {
                    "packageSpec": environment_lock.get("packageSpec"),
                    "dependencies": environment_lock.get("dependencies")
                    if isinstance(environment_lock.get("dependencies"), list)
                    else None,
                }
            ),
        }
    )


def _public_graph_snapshot(value: Any) -> dict[str, Any]:
    graph = value if isinstance(value, dict) else {}
    nodes = _mapping_items(graph.get("nodes"))
    run_spec = graph.get("runSpec") if isinstance(graph.get("runSpec"), dict) else {}
    workflow = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    workflow_nodes = _mapping_items(workflow.get("nodes"))
    return _compact(
        {
            "schemaVersion": graph.get("schemaVersion"),
            "pipelineId": graph.get("pipelineId") or run_spec.get("pipelineId"),
            "nodeCount": len(nodes) or len(workflow_nodes),
            "ruleCount": _rule_count(nodes or workflow_nodes),
        }
    )


def _public_runtime_lock(value: Any) -> dict[str, Any]:
    runtime_lock = value if isinstance(value, dict) else {}
    return _compact(
        {
            "schemaVersion": runtime_lock.get("schemaVersion"),
            "engine": runtime_lock.get("engine"),
            "platform": runtime_lock.get("platform"),
            "pipelineId": runtime_lock.get("pipelineId"),
            "pipelineVersion": runtime_lock.get("pipelineVersion"),
        }
    )


def _rule_count(nodes: list[dict[str, Any]]) -> int:
    explicit_rules = [item for item in nodes if str(item.get("kind") or "").strip() == "rule"]
    if explicit_rules:
        return len(explicit_rules)
    return len([item for item in nodes if item.get("toolRevisionId")])


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _sha256_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}
