from __future__ import annotations

from typing import Any

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
            "runId": str(public.get("runId") or run_id),
            "artifactCount": _safe_int(public.get("artifactCount")),
            "inputArtifactCount": _safe_int(public.get("inputArtifactCount")),
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
            "resultId": str(public.get("resultId") or result_id),
            "runId": str(public.get("runId") or ""),
            "artifactCount": _safe_int(public.get("artifactCount")),
            "inputArtifactCount": _safe_int(public.get("inputArtifactCount")),
        },
    )
    return public


def public_run_results(results: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(results)
    artifacts = public.get("artifacts")
    if isinstance(artifacts, list):
        public["artifacts"] = [_public_artifact(item) for item in artifacts if isinstance(item, dict)]
    input_artifacts = public.get("inputArtifacts")
    if isinstance(input_artifacts, list):
        public["inputArtifacts"] = [_public_input_artifact(item) for item in input_artifacts if isinstance(item, dict)]
    public.pop("lineageEdges", None)
    return public


def public_result_detail(result: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(result)
    artifacts = public.get("artifacts")
    if isinstance(artifacts, list):
        public["artifacts"] = [_public_artifact(item) for item in artifacts if isinstance(item, dict)]
    input_artifacts = public.get("inputArtifacts")
    if isinstance(input_artifacts, list):
        public["inputArtifacts"] = [_public_input_artifact(item) for item in input_artifacts if isinstance(item, dict)]
    public.pop("lineageEdges", None)
    return public


def public_result_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "resultId": str(item.get("resultId") or ""),
        "runId": str(item.get("runId") or ""),
        "title": str(item.get("title") or ""),
        "pipelineId": str(item.get("pipelineId") or ""),
        "artifactCount": _safe_int(item.get("artifactCount")),
        "inputArtifactCount": _safe_int(item.get("inputArtifactCount")),
        "producedAt": str(item.get("producedAt") or ""),
    }


def _public_artifact(item: dict[str, Any]) -> dict[str, Any]:
    return _without_sensitive_fields(item)


def _public_input_artifact(item: dict[str, Any]) -> dict[str, Any]:
    public = _without_sensitive_fields(item)
    ports = public.get("ports")
    if isinstance(ports, list):
        public["ports"] = [_without_sensitive_fields(port) for port in ports if isinstance(port, dict)]
    return public


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
