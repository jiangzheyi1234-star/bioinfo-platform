from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .api_models import (
    WorkflowDesignDraftCreateRequest,
    WorkflowDesignDraftForkRequest,
    WorkflowDesignDraftUpdateRequest,
)
from .config import RemoteRunnerConfig
from .route_utils import authorized_config, data_response, request_payload, run_sync
from .workflow_design_compiler import compile_workflow_design_project
from .workflow_design_planner import plan_workflow_design_draft
from .workflow_design_storage import (
    create_workflow_design_draft,
    delete_workflow_design_draft,
    fork_workflow_design_draft,
    list_workflow_design_drafts,
    require_workflow_design_draft,
    update_workflow_design_draft,
)
from .workflow_revision_storage import create_or_fetch_workflow_revision


def create_workflow_design_draft_from_request(
    cfg: RemoteRunnerConfig,
    request: WorkflowDesignDraftCreateRequest,
) -> dict[str, Any]:
    return create_workflow_design_draft(
        cfg,
        request_payload(request.draft),
    )


def update_workflow_design_draft_from_request(
    cfg: RemoteRunnerConfig,
    draft_id: str,
    request: WorkflowDesignDraftUpdateRequest,
) -> dict[str, Any]:
    return update_workflow_design_draft(
        cfg,
        draft_id,
        request_payload(request.draft),
        expected_revision=request.expectedRevision,
    )


def fork_workflow_design_draft_from_request(
    cfg: RemoteRunnerConfig,
    draft_id: str,
    request: WorkflowDesignDraftForkRequest,
) -> dict[str, Any]:
    return fork_workflow_design_draft(cfg, draft_id, name=request.name)


async def list_workflow_design_drafts_from_request(authorization: str | None) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    items = await run_sync(list_workflow_design_drafts, cfg)
    return data_response({"items": items})


async def create_workflow_design_draft_response_from_request(
    request: WorkflowDesignDraftCreateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(create_workflow_design_draft_from_request, cfg, request)
    return data_response(item)


async def get_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(require_workflow_design_draft, cfg, draft_id)
    return data_response(item)


async def update_workflow_design_draft_response_from_request(
    draft_id: str,
    request: WorkflowDesignDraftUpdateRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(update_workflow_design_draft_from_request, cfg, draft_id, request)
    return data_response(item)


async def fork_workflow_design_draft_response_from_request(
    draft_id: str,
    request: WorkflowDesignDraftForkRequest,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(fork_workflow_design_draft_from_request, cfg, draft_id, request)
    return data_response(item)


async def delete_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    await run_sync(delete_workflow_design_draft, cfg, draft_id)
    return data_response({"draftId": draft_id, "deleted": True})


async def plan_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(plan_workflow_design_draft_preview, cfg, draft_id)
    return data_response(item)


async def compile_workflow_design_draft_from_request(
    draft_id: str,
    authorization: str | None,
) -> dict[str, Any]:
    cfg = authorized_config(authorization)
    item = await run_sync(compile_workflow_design_draft_export, cfg, draft_id)
    return data_response(item)


def plan_workflow_design_draft_preview(cfg: RemoteRunnerConfig, draft_id: str) -> dict[str, Any]:
    item = require_workflow_design_draft(cfg, draft_id)
    return plan_workflow_design_draft(
        cfg,
        item["draft"],
        preview_root=Path(cfg.work_dir) / "workflow-design-previews" / draft_id,
        draft_id=draft_id,
        revision=int(item["revision"]),
    )


def compile_workflow_design_draft_export(cfg: RemoteRunnerConfig, draft_id: str) -> dict[str, Any]:
    item = require_workflow_design_draft(cfg, draft_id)
    export_dir = Path(cfg.work_dir) / "workflow-design-exports" / draft_id / f"rev-{item['revision']}"
    compiled = compile_workflow_design_project(
        cfg,
        item["draft"],
        export_dir=export_dir,
        draft_id=draft_id,
        revision=int(item["revision"]),
    )
    workflow_revision = create_or_fetch_workflow_revision(
        cfg,
        draft_id=draft_id,
        draft_revision=int(item["revision"]),
        manifest=_workflow_revision_manifest(export_dir, compiled),
        graph_snapshot=_workflow_revision_graph_snapshot(compiled),
        runtime_lock=_workflow_revision_runtime_lock(cfg),
        compiler=_workflow_revision_compiler(),
    )
    compiled_run_spec = dict(compiled.get("runSpec") if isinstance(compiled.get("runSpec"), dict) else {})
    compiled_run_spec["workflowRevisionId"] = workflow_revision["workflowRevisionId"]
    return {
        **compiled,
        "runSpec": compiled_run_spec,
        "workflowRevisionId": workflow_revision["workflowRevisionId"],
        "workflowRevision": workflow_revision,
    }


def _workflow_revision_manifest(export_dir: Path, compiled: dict[str, Any]) -> dict[str, Any]:
    files = [
        {
            "path": path.relative_to(export_dir).as_posix(),
            "sha256": _sha256_file(path),
        }
        for path in sorted(export_dir.rglob("*"), key=lambda item: item.relative_to(export_dir).as_posix())
        if path.is_file()
    ]
    run_spec = compiled.get("runSpec") if isinstance(compiled.get("runSpec"), dict) else {}
    workflow = run_spec.get("workflow") if isinstance(run_spec.get("workflow"), dict) else {}
    nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
    bundle_audit_by_revision = {
        str(item.get("toolRevisionId") or "").strip(): item
        for item in (compiled.get("capabilityBundleAudit") or [])
        if isinstance(item, dict) and str(item.get("toolRevisionId") or "").strip()
    }
    return {
        "schemaVersion": "workflow-revision-manifest.v1",
        "layout": compiled.get("layout") if isinstance(compiled.get("layout"), dict) else {},
        "files": files,
        "runSpecSha256": _sha256_json(run_spec),
        "toolRevisions": [
            _tool_revision_manifest_entry(node, bundle_audit_by_revision=bundle_audit_by_revision)
            for node in nodes
            if isinstance(node, dict) and str(node.get("toolRevisionId") or "").strip()
        ],
    }


def _tool_revision_manifest_entry(
    node: dict[str, Any],
    *,
    bundle_audit_by_revision: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tool_revision_id = str(node.get("toolRevisionId") or "").strip()
    audit = bundle_audit_by_revision.get(tool_revision_id)
    if audit is not None:
        return dict(audit)
    raise ValueError(f"CAPABILITY_BUNDLE_AUDIT_REQUIRED: {tool_revision_id}")


def _workflow_revision_graph_snapshot(compiled: dict[str, Any]) -> dict[str, Any]:
    run_spec = compiled.get("runSpec") if isinstance(compiled.get("runSpec"), dict) else {}
    return {
        "schemaVersion": "workflow-graph-snapshot.v1",
        "runSpec": run_spec,
    }


def _workflow_revision_runtime_lock(cfg: RemoteRunnerConfig) -> dict[str, Any]:
    return {
        "schemaVersion": "workflow-runtime-lock.v1",
        "platform": "linux-64",
        "snakemakeCommand": str(cfg.snakemake_command or ""),
        "workflowProfileDir": str(cfg.workflow_profile_dir or ""),
        "releaseDir": str(cfg.release_dir or ""),
    }


def _workflow_revision_compiler() -> dict[str, Any]:
    return {
        "name": "h2ometa-workflow-design-compiler",
        "version": "2026.6.7",
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
