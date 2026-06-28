from __future__ import annotations

from typing import Any

from .artifact_output_labels import safe_artifact_output_label
from .config import RemoteRunnerConfig
from .execution_query_storage import fetch_result, fetch_run_results, list_results
from .governance_audit import record_governance_audit_event


SENSITIVE_RESULT_FIELDS = frozenset(
    {
        "path",
        "storageUri",
        "externalUri",
        "packagePath",
        "packageUri",
        "localPath",
        "resultDir",
        "inputStorageUri",
        "sourceStorageUri",
    }
)


def governed_fetch_run_results(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    results = fetch_run_results(cfg, run_id)
    public = public_run_results(results)
    record_governance_audit_event(
        cfg,
        action="run.results.read",
        actor=_actor(cfg),
        subject_kind="run_results",
        subject_id=str(public.get("runId") or run_id),
        details={
            "artifactCount": _safe_int(public.get("artifactCount")),
            "inputArtifactCount": _safe_int(public.get("inputArtifactCount")),
            "lineageEdgeCount": _lineage_edge_count(public),
            "lineageProjectionReturned": True,
            "lineageEdgesReturned": False,
        },
    )
    return public


def governed_list_results(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    items = [public_result_summary(item) for item in list_results(cfg)]
    record_governance_audit_event(
        cfg,
        action="result.list",
        actor=_actor(cfg),
        subject_kind="result",
        subject_id="query",
        details={"returnedCount": len(items)},
    )
    return items


def governed_fetch_result(cfg: RemoteRunnerConfig, result_id: str) -> dict[str, Any]:
    result = fetch_result(cfg, result_id)
    public = public_result_detail(result)
    record_governance_audit_event(
        cfg,
        action="result.read",
        actor=_actor(cfg),
        subject_kind="result",
        subject_id=str(public.get("resultId") or result_id),
        details={
            "artifactCount": _safe_int(public.get("artifactCount")),
            "inputArtifactCount": _safe_int(public.get("inputArtifactCount")),
            "lineageEdgeCount": _lineage_edge_count(public),
            "lineageProjectionReturned": True,
            "lineageEdgesReturned": False,
        },
    )
    return public


def public_run_results(results: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(results)
    lineage_edges = _lineage_edges(results)
    artifacts = public.get("artifacts")
    if isinstance(artifacts, list):
        public["artifacts"] = [_public_artifact(item) for item in artifacts if isinstance(item, dict)]
    input_artifacts = public.get("inputArtifacts")
    if isinstance(input_artifacts, list):
        public["inputArtifacts"] = [_public_input_artifact(item) for item in input_artifacts if isinstance(item, dict)]
    public["lineageSummary"] = _public_lineage_summary(lineage_edges)
    public["outputLineage"] = _public_output_lineage(lineage_edges)
    public.pop("lineageEdges", None)
    return public


def public_result_detail(result: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(result)
    lineage_edges = _lineage_edges(result)
    artifacts = public.get("artifacts")
    if isinstance(artifacts, list):
        public["artifacts"] = [_public_artifact(item) for item in artifacts if isinstance(item, dict)]
    input_artifacts = public.get("inputArtifacts")
    if isinstance(input_artifacts, list):
        public["inputArtifacts"] = [_public_input_artifact(item) for item in input_artifacts if isinstance(item, dict)]
    public["lineageSummary"] = _public_lineage_summary(lineage_edges)
    public["outputLineage"] = _public_output_lineage(lineage_edges)
    public.pop("lineageEdges", None)
    return public


def public_result_summary(item: dict[str, Any]) -> dict[str, Any]:
    public = {
        "resultId": str(item.get("resultId") or ""),
        "runId": str(item.get("runId") or ""),
        "title": str(item.get("title") or ""),
        "pipelineId": str(item.get("pipelineId") or ""),
        "artifactCount": _safe_int(item.get("artifactCount")),
        "inputArtifactCount": _safe_int(item.get("inputArtifactCount")),
        "producedAt": str(item.get("producedAt") or ""),
    }
    lineage_edges = _lineage_edges(item)
    if lineage_edges:
        public["lineageSummary"] = _public_lineage_summary(lineage_edges)
    return public


def _public_artifact(item: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(item)
    label = safe_artifact_output_label(public.get("artifactKey"))
    if label:
        public["artifactKey"] = label
    else:
        public.pop("artifactKey", None)
    return public


def _public_input_artifact(item: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(item)
    ports = public.get("ports")
    if isinstance(ports, list):
        public["ports"] = [_without_sensitive_fields(port) for port in ports if isinstance(port, dict)]
    return public


def _lineage_edges(item: dict[str, Any]) -> list[dict[str, Any]]:
    edges = item.get("lineageEdges")
    if not isinstance(edges, list):
        return []
    return [edge for edge in edges if isinstance(edge, dict)]


def _public_lineage_summary(edges: list[dict[str, Any]]) -> dict[str, Any]:
    predicate_counts: dict[str, int] = {}
    for edge in edges:
        predicate = str(edge.get("predicate") or "unknown")
        predicate_counts[predicate] = predicate_counts.get(predicate, 0) + 1
    input_edges = [edge for edge in edges if edge.get("predicate") == "prov:used"]
    output_edges = [
        edge
        for edge in edges
        if edge.get("predicate") in {"prov:generated", "h2ometa:cache_adopted"}
    ]
    return {
        "schemaVersion": "h2ometa.result-lineage-summary.v1",
        "edgeCount": len(edges),
        "inputEdgeCount": len(input_edges),
        "outputEdgeCount": len(output_edges),
        "cacheAdoptionEdgeCount": sum(1 for edge in output_edges if edge.get("predicate") == "h2ometa:cache_adopted"),
        "predicateCounts": dict(sorted(predicate_counts.items())),
        "redactionPolicy": {
            "rawPayloadExposed": False,
            "pathsExposed": False,
            "storageLocationsExposed": False,
        },
    }


def _public_output_lineage(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output_edges = [
        edge
        for edge in edges
        if edge.get("predicate") in {"prov:generated", "h2ometa:cache_adopted"}
        and edge.get("objectKind") == "artifact_blob"
    ]
    return [_public_output_lineage_edge(edge) for edge in output_edges]


def _public_output_lineage_edge(edge: dict[str, Any]) -> dict[str, Any]:
    payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
    public = {
        "lineageEdgeId": str(edge.get("lineageEdgeId") or ""),
        "predicate": str(edge.get("predicate") or ""),
        "artifactBlobId": str(edge.get("objectId") or ""),
        "contentHash": str(edge.get("contentHash") or ""),
        "workflowRevisionId": str(edge.get("workflowRevisionId") or ""),
        "evidenceEventId": str(edge.get("evidenceEventId") or payload.get("evidenceEventId") or ""),
        "artifactId": str(payload.get("artifactId") or ""),
        "artifactKey": safe_artifact_output_label(payload.get("artifactKey")) or "",
        "role": str(payload.get("role") or "output"),
        "stepId": str(payload.get("stepId") or ""),
        "runArtifactEdgeId": str(payload.get("runArtifactEdgeId") or ""),
    }
    return {key: value for key, value in public.items() if value != ""}


def _without_sensitive_fields(item: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in item.items():
        if key in SENSITIVE_RESULT_FIELDS:
            continue
        if isinstance(value, dict):
            public[key] = _without_sensitive_fields(value)
        elif isinstance(value, list):
            public[key] = [_without_sensitive_fields(child) if isinstance(child, dict) else child for child in value]
        else:
            public[key] = value
    return public


def _actor(cfg: RemoteRunnerConfig) -> str:
    return str(cfg.api_token_actor or "").strip() or "remote-runner-api"


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _lineage_edge_count(public: dict[str, Any]) -> int:
    summary = public.get("lineageSummary") if isinstance(public.get("lineageSummary"), dict) else {}
    return _safe_int(summary.get("edgeCount"))
