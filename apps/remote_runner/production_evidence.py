from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .database_layers import production_evidence_database_layer_supported
from .databases import fetch_reference_database
from .generated_workflow_constants import GENERATED_TOOL_RUN_PIPELINE_ID
from .storage import fetch_run, fetch_run_results
from .tools_errors import ToolProductionConflictError, ToolRegistryError

PRODUCTION_EVIDENCE_TYPES = {
    "real-data-acceptance",
    "real-database-acceptance",
}


def normalize_production_evidence_type(raw: Any) -> str:
    evidence_type = str(raw or "").strip()
    if not evidence_type:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_TYPE_REQUIRED")
    if evidence_type not in PRODUCTION_EVIDENCE_TYPES:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_TYPE_INVALID")
    return evidence_type


def validate_production_evidence_run(
    cfg: RemoteRunnerConfig,
    evidence: dict[str, Any],
    *,
    tool_revision_id: str,
) -> dict[str, str]:
    run_id = str(evidence.get("runId") or "").strip()
    run = fetch_run(cfg, run_id)
    if run is None:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_RUN_NOT_FOUND")
    if str(run.get("status") or "") != "completed":
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_RUN_NOT_COMPLETED")
    if str(run.get("pipelineId") or "") != GENERATED_TOOL_RUN_PIPELINE_ID:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_PIPELINE_MISMATCH")
    run_tool_ids = _run_tool_ids(run.get("runSpec"))
    expected_revision_id = str(tool_revision_id or "").strip()
    if not expected_revision_id:
        raise ToolProductionConflictError("TOOL_PRODUCTION_REQUIRES_TOOL_REVISION")
    if expected_revision_id not in run_tool_ids:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_TOOL_MISMATCH")
    _validate_database_evidence(cfg, evidence, run.get("runSpec"))
    try:
        results = fetch_run_results(cfg, run_id)
    except KeyError as exc:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_RUN_NOT_FOUND") from exc
    artifacts = results.get("artifacts") if isinstance(results, dict) else []
    if not artifacts:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_ARTIFACT_REQUIRED")
    artifact_dicts = [item for item in artifacts if isinstance(item, dict)]
    if not artifact_dicts:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_ARTIFACT_REQUIRED")
    artifact_name = str(evidence.get("artifactName") or "").strip()
    candidate_artifacts = artifact_dicts
    if artifact_name:
        candidate_artifacts = [item for item in artifact_dicts if _artifact_matches(item, artifact_name)]
        if not candidate_artifacts:
            raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_ARTIFACT_NOT_FOUND")
    if any(_artifact_size_bytes(item) <= 0 for item in candidate_artifacts):
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_ARTIFACT_EMPTY")
    names = [_artifact_name(item) for item in artifact_dicts]
    names = [name for name in names if name]
    return {"artifactCount": str(len(artifacts)), "artifactNames": ",".join(names)}


def _run_tool_ids(run_spec: Any) -> set[str]:
    if not isinstance(run_spec, dict):
        return set()
    ids: set[str] = set()
    workflow = run_spec.get("workflow")
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else []
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                tool_revision_id = str(node.get("toolRevisionId") or "").strip()
                if tool_revision_id:
                    ids.add(tool_revision_id)
    return ids


def _validate_database_evidence(cfg: RemoteRunnerConfig, evidence: dict[str, Any], run_spec: Any) -> None:
    if str(evidence.get("evidenceType") or "").strip() != "real-database-acceptance":
        return
    role = str(evidence.get("role") or "").strip()
    database_id = str(evidence.get("databaseId") or "").strip()
    template_id = str(evidence.get("templateId") or "").strip()
    if not role or not database_id or not template_id:
        raise ToolRegistryError("TOOL_PRODUCTION_EVIDENCE_DATABASE_REQUIRED")
    bindings = _run_database_bindings(run_spec)
    binding = bindings.get(role)
    if binding is None or str(binding.get("databaseId") or "").strip() != database_id:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH")
    if str(binding.get("templateId") or "").strip().lower() != template_id.lower():
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH")
    database = fetch_reference_database(cfg, database_id)
    if str((database or {}).get("status") or "") != "available":
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_UNAVAILABLE")
    if not production_evidence_database_layer_supported(database or {}):
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_LAYER_UNSUPPORTED")
    metadata = (database or {}).get("metadata") or {}
    registered_template_id = str(metadata.get("templateId") or "").strip().lower()
    if registered_template_id != template_id.lower():
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_MISMATCH")
    _validate_pack_database_evidence(evidence, metadata)


def _validate_pack_database_evidence(evidence: dict[str, Any], metadata: Any) -> None:
    expected_pack_id = str(evidence.get("packId") or evidence.get("installedFromPackId") or "").strip()
    if not expected_pack_id:
        return
    registered_metadata = metadata if isinstance(metadata, dict) else {}
    registered_pack_id = str(
        registered_metadata.get("installedFromPackId") or registered_metadata.get("packId") or ""
    ).strip()
    if registered_pack_id != expected_pack_id:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_PACK_MISMATCH")
    expected_checksum = str(evidence.get("packChecksum") or "").strip()
    if expected_checksum and str(registered_metadata.get("packChecksum") or "").strip() != expected_checksum:
        raise ToolProductionConflictError("TOOL_PRODUCTION_EVIDENCE_DATABASE_PACK_MISMATCH")


def _run_database_bindings(run_spec: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(run_spec, dict):
        return {}
    raw = run_spec.get("resourceBindings")
    if not isinstance(raw, dict):
        return {}
    return {str(role): binding for role, binding in raw.items() if isinstance(binding, dict)}


def _artifact_matches(artifact: dict[str, Any], expected_name: str) -> bool:
    path = str(artifact.get("path") or "").replace("\\", "/")
    return path == expected_name or path.rsplit("/", 1)[-1] == expected_name


def _artifact_name(artifact: dict[str, Any]) -> str:
    path = str(artifact.get("path") or "").replace("\\", "/")
    if path:
        return path.rsplit("/", 1)[-1]
    return str(artifact.get("kind") or artifact.get("artifactId") or "").strip()


def _artifact_size_bytes(artifact: dict[str, Any]) -> int:
    try:
        return int(artifact.get("sizeBytes") or 0)
    except (TypeError, ValueError):
        return 0
