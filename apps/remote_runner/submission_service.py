from __future__ import annotations

import hashlib
from pathlib import Path
import time
from typing import Any

from .api_models import RunCreateRequest
from .config import RemoteRunnerConfig
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from .governance_audit import record_governance_audit_event
from .health_service import ensure_execution_admission_ready, ensure_submission_ready
from .pipeline import PipelineDefinition, get_pipeline, validate_run_spec_for_pipeline
from .preflight import preflight_run_spec
from .route_utils import request_payload
from .storage import canonical_payload_hash, create_run_record
from .workflow_revision_storage import create_or_fetch_workflow_revision


def create_run_from_request(
    cfg: RemoteRunnerConfig,
    request: RunCreateRequest,
    *,
    idempotency_key: str | None,
    x_request_id: str | None,
) -> dict[str, Any]:
    ensure_submission_ready(cfg)
    run_spec = request_payload(request.runSpec)
    pipeline_id = request.runSpec.pipelineId
    pipeline_version = request.runSpec.pipelineVersion
    request_id = str(request.requestId or x_request_id or f"req_{int(time.time() * 1000)}")
    server_id = str(request.serverId)
    idem_key = str(idempotency_key or f"idem_{request_id}")
    pipeline = get_pipeline(cfg, pipeline_id)
    validate_run_spec_for_pipeline(pipeline, run_spec)
    preflight_run_spec(cfg, pipeline, run_spec)
    ensure_execution_admission_ready(cfg)
    if (
        pipeline_id != GENERATED_TOOL_RUN_PIPELINE_ID
        and not str(pipeline_version or "").strip()
    ):
        run_spec["pipelineVersion"] = pipeline.version
    if pipeline_id != GENERATED_TOOL_RUN_PIPELINE_ID and not str(run_spec.get("workflowRevisionId") or "").strip():
        run_spec["workflowRevisionId"] = _workflow_revision_for_bundled_pipeline(cfg, pipeline)["workflowRevisionId"]
    payload_hash = canonical_payload_hash({"serverId": server_id, "runSpec": run_spec})
    run_create = create_run_record(
        cfg,
        server_id=server_id,
        request_id=request_id,
        run_spec=run_spec,
        idempotency_key=idem_key,
        payload_hash=payload_hash,
    )
    run = run_create.run
    record_governance_audit_event(
        cfg,
        action="run.submit",
        subject_kind="run",
        subject_id=str(run["runId"]),
        details={
            "serverId": server_id,
            "requestId": run["requestId"],
            "pipelineId": pipeline_id,
            "pipelineVersion": str(run_spec.get("pipelineVersion") or ""),
            "projectId": str(run_spec.get("projectId") or ""),
            "runSpecVersion": str(run_spec.get("runSpecVersion") or ""),
            "workflowRevisionId": str(run_spec.get("workflowRevisionId") or ""),
            "idempotencyReplay": not run_create.created,
        },
    )
    return {
        "data": {
            "requestId": run["requestId"],
            "runId": run["runId"],
            "status": run["status"],
            "stage": run["stage"],
            "message": run["message"],
            "lastUpdatedAt": run["lastUpdatedAt"],
        },
        "location": f"/api/v1/runs/{run['runId']}",
        "retryAfter": 2,
        "requestId": run["requestId"],
    }


def _workflow_revision_for_bundled_pipeline(cfg: RemoteRunnerConfig, pipeline: PipelineDefinition) -> dict:
    return create_or_fetch_workflow_revision(
        cfg,
        draft_id=f"bundled-pipeline:{pipeline.pipeline_id}",
        draft_revision=None,
        manifest=_bundled_pipeline_revision_manifest(pipeline),
        graph_snapshot=_bundled_pipeline_graph_snapshot(pipeline),
        runtime_lock=_bundled_pipeline_runtime_lock(pipeline),
        compiler={
            "schemaVersion": "bundled-pipeline-compiler.v1",
            "name": "h2ometa-remote-runner-bundled-pipeline",
        },
        created_by="remote-runner",
    )


def _bundled_pipeline_revision_manifest(pipeline: PipelineDefinition) -> dict:
    files = [
        {
            "path": path.relative_to(pipeline.root_dir).as_posix(),
            "sha256": _sha256_file(path),
        }
        for path in sorted(pipeline.root_dir.rglob("*"), key=lambda item: item.relative_to(pipeline.root_dir).as_posix())
        if _is_revision_source_file(path, root=pipeline.root_dir)
    ]
    return {
        "schemaVersion": "bundled-pipeline-workflow-revision-manifest.v1",
        "pipelineId": pipeline.pipeline_id,
        "pipelineVersion": pipeline.version,
        "source": "remote-runner-pipeline-registry",
        "snakefile": pipeline.snakefile.relative_to(pipeline.root_dir).as_posix(),
        "files": files,
    }


def _bundled_pipeline_graph_snapshot(pipeline: PipelineDefinition) -> dict:
    graph = pipeline.ui_schema.get("graph") if isinstance(pipeline.ui_schema, dict) else {}
    graph = graph if isinstance(graph, dict) else {}
    return {
        "schemaVersion": "bundled-pipeline-graph-snapshot.v1",
        "pipelineId": pipeline.pipeline_id,
        "nodes": graph.get("nodes") if isinstance(graph.get("nodes"), list) else [],
        "edges": graph.get("edges") if isinstance(graph.get("edges"), list) else [],
    }


def _bundled_pipeline_runtime_lock(pipeline: PipelineDefinition) -> dict:
    return {
        "schemaVersion": "bundled-pipeline-runtime-lock.v1",
        "engine": "snakemake",
        "pipelineId": pipeline.pipeline_id,
        "pipelineVersion": pipeline.version,
        "inputsSchema": pipeline.input_schema,
        "paramsSchema": pipeline.params_schema,
        "resources": pipeline.resource_schema,
        "outputSchema": pipeline.output_schema,
    }


def _is_revision_source_file(path: Path, *, root: Path) -> bool:
    if not path.is_file():
        return False
    relative_parts = path.relative_to(root).parts
    if any(part == "__pycache__" or part.startswith(".") for part in relative_parts):
        return False
    return path.suffix not in {".pyc", ".pyo"}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
