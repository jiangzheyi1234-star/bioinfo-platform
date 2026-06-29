"""Software environment evidence for First Successful Run validation cards."""

from __future__ import annotations

import hashlib
import json
from typing import Any


FIRST_RUN_SOFTWARE_ENVIRONMENT_SCHEMA_VERSION = "h2ometa.first-run.software-environment.v1"


def build_first_run_software_environment(workflow_revision: dict[str, Any]) -> dict[str, Any]:
    _require_text(workflow_revision.get("workflowRevisionId"), "FIRST_RUN_WORKFLOW_REVISION_ID_REQUIRED")
    _require_text(workflow_revision.get("contentHash"), "FIRST_RUN_WORKFLOW_REVISION_CONTENT_HASH_REQUIRED")
    manifest = _mapping(workflow_revision.get("manifest"))
    if not manifest:
        raise ValueError("FIRST_RUN_WORKFLOW_REVISION_MANIFEST_REQUIRED")
    runtime_lock = _mapping(workflow_revision.get("runtimeLock"))
    if not runtime_lock:
        raise ValueError("FIRST_RUN_WORKFLOW_RUNTIME_LOCK_REQUIRED")
    graph = _mapping(workflow_revision.get("graphSnapshot"))
    compiler = _compiler(workflow_revision.get("compiler"))
    if not compiler.get("name"):
        raise ValueError("FIRST_RUN_WORKFLOW_COMPILER_REQUIRED")
    return _compact(
        {
            "schemaVersion": FIRST_RUN_SOFTWARE_ENVIRONMENT_SCHEMA_VERSION,
            "status": "verified",
            "workflowRevisionId": workflow_revision.get("workflowRevisionId"),
            "contentHash": workflow_revision.get("contentHash"),
            "compiler": compiler,
            "runtime": _runtime(runtime_lock, workflow_revision.get("runtimeLockSha256")),
            "workflow": _workflow(manifest),
            "graph": _graph(graph),
            "toolRevisions": [_tool_revision(item) for item in _mapping_items(manifest.get("toolRevisions"))],
        }
    )


def _compiler(value: Any) -> dict[str, Any]:
    compiler = _mapping(value)
    return _compact({"name": compiler.get("name"), "version": compiler.get("version")})


def _runtime(runtime_lock: dict[str, Any], runtime_lock_sha256: Any) -> dict[str, Any]:
    return _compact(
        {
            "engine": runtime_lock.get("engine") or "snakemake",
            "platform": runtime_lock.get("platform"),
            "pipelineId": runtime_lock.get("pipelineId"),
            "pipelineVersion": runtime_lock.get("pipelineVersion"),
            "runtimeLockSha256": str(runtime_lock_sha256 or "").strip() or _sha256_json(runtime_lock),
        }
    )


def _workflow(manifest: dict[str, Any]) -> dict[str, Any]:
    files = [_source_file(item) for item in _mapping_items(manifest.get("files"))]
    if not files:
        raise ValueError("FIRST_RUN_WORKFLOW_SOURCE_FILES_REQUIRED")
    return _compact(
        {
            "source": manifest.get("source"),
            "pipelineId": manifest.get("pipelineId"),
            "pipelineVersion": manifest.get("pipelineVersion"),
            "snakefile": manifest.get("snakefile"),
            "runSpecSha256": manifest.get("runSpecSha256"),
            "sourceFileCount": len(files),
            "sourceFiles": _highlight_source_files(files),
        }
    )


def _source_file(item: dict[str, Any]) -> dict[str, Any]:
    return _compact({"path": item.get("path"), "sha256": item.get("sha256")})


def _highlight_source_files(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred = [
        item
        for item in files
        if str(item.get("path") or "").endswith(("Snakefile", ".smk", ".yaml", ".yml", ".py"))
    ]
    return preferred[:12] if preferred else files[:12]


def _graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = _mapping_items(graph.get("nodes"))
    run_spec = _mapping(graph.get("runSpec"))
    workflow = _mapping(run_spec.get("workflow"))
    workflow_nodes = _mapping_items(workflow.get("nodes"))
    selected = nodes or workflow_nodes
    return _compact(
        {
            "pipelineId": graph.get("pipelineId") or run_spec.get("pipelineId"),
            "nodeCount": len(selected),
            "ruleCount": _rule_count(selected),
        }
    )


def _rule_count(nodes: list[dict[str, Any]]) -> int:
    rules = [item for item in nodes if str(item.get("kind") or "").strip() == "rule"]
    return len(rules) if rules else len([item for item in nodes if item.get("toolRevisionId")])


def _tool_revision(item: dict[str, Any]) -> dict[str, Any]:
    environment_lock = _mapping(item.get("environmentLock"))
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


def _sha256_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _require_text(value: Any, code: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(code)
    return normalized


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}
