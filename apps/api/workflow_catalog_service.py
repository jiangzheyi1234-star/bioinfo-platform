"""Service functions for workflow catalog and run detail payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.response_cache import cached_response
from apps.api.route_utils import run_sync, runtime_service
from core.contracts.pipeline_manifest import validate_pipeline_manifest


async def get_workflow_catalog_from_request(refresh: bool) -> dict[str, Any]:
    return await cached_response(
        "workflow_catalog:bundled",
        30,
        load_workflow_catalog,
        force_refresh=refresh,
    )


async def get_run_detail_from_request(run_id: str, refresh: bool) -> dict[str, Any]:
    return await cached_response(
        f"run_detail:{run_id}",
        3,
        lambda: load_run_detail(run_id),
        force_refresh=refresh,
    )


async def load_workflow_catalog() -> dict[str, Any]:
    manifests = list_bundled_pipeline_manifests()
    catalog = [_catalog_item_from_pipeline(item) for item in manifests]
    catalog.sort(key=lambda item: (not item["runnable"], item["name"].lower()))
    return {
        "data": {
            "items": catalog,
            "serverReady": False,
        }
    }


def list_bundled_pipeline_manifests() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[1] / "remote_runner" / "pipelines"
    items: list[dict[str, Any]] = []
    for manifest_path in sorted(root.glob("*/pipeline.json")):
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_pipeline_manifest(raw, manifest_path)
        raw["enabled"] = bool(raw.get("enabled", True))
        items.append(raw)
    return items


async def load_run_detail(run_id: str) -> dict[str, Any]:
    runtime = runtime_service()
    run = await run_sync(lambda: runtime.get_run(run_id))
    events = await run_sync(lambda: runtime.get_run_events(run_id))
    stdout = await run_sync(
        lambda: runtime.get_run_logs(
            run_id=run_id,
            stream="stdout",
            cursor=None,
        )
    )
    stderr = await run_sync(
        lambda: runtime.get_run_logs(
            run_id=run_id,
            stream="stderr",
            cursor=None,
        )
    )
    results = await run_sync(lambda: runtime.get_run_results(run_id))
    rules = await run_sync(lambda: runtime.get_run_rules(run_id))
    execution_context = await run_sync(lambda: runtime.get_run_execution_context(run_id))

    run_data = _unwrap_data(run, {})
    events_data = _unwrap_data(events, {})
    event_items = events_data.get("items", events_data if isinstance(events_data, list) else [])
    stdout_data = _unwrap_data(stdout, {})
    stderr_data = _unwrap_data(stderr, {})
    result_data = _unwrap_data(results, {})
    if isinstance(result_data, dict) and not result_data.get("resultId"):
        result_data = {**result_data, "resultId": _canonical_result_id_for_run(str(result_data.get("runId") or run_id))}
    rules_data = _unwrap_data(rules, {})
    execution_context_data = _unwrap_data(execution_context, {})

    failure_locator = _build_failure_locator(
        run_id=run_id,
        run=run_data,
        events=event_items,
        stdout=stdout_data,
        stderr=stderr_data,
        results=result_data,
        rules=rules_data,
    )
    failure_locator["ruleLogContext"] = await _load_rule_log_context(
        runtime=runtime,
        result_data=result_data,
        failure_locator=failure_locator,
    )

    return {
        "data": {
            "run": run_data,
            "events": event_items,
            "logs": {
                "stdout": stdout_data,
                "stderr": stderr_data,
            },
            "results": result_data,
            "rules": rules_data,
            "executionContext": execution_context_data,
            "failureLocator": failure_locator,
            "previews": await _load_previews(runtime, result_data),
        }
    }


async def _load_previews(runtime: Any, result_data: Any) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for artifact in _preferred_preview_artifacts(list(result_data.get("artifacts") or [])):
        result_id = str(result_data.get("resultId") or "")
        artifact_id = str(artifact.get("artifactId") or "")
        if not result_id or not artifact_id:
            continue
        preview = await run_sync(
            lambda: runtime.get_result_preview(
                result_id=result_id,
                artifact_id=artifact_id,
            )
        )
        previews.append(_unwrap_data(preview, {}))
    return previews


def _preferred_preview_artifacts(artifacts: list[Any]) -> list[dict[str, Any]]:
    valid = [item for item in artifacts if isinstance(item, dict)]
    priority = {
        "summary.tsv": 0,
        "qc-summary.tsv": 1,
        "run-report.html": 2,
        "raw-log.txt": 4,
    }

    def score(item: dict[str, Any]) -> tuple[int, str]:
        name = Path(str(item.get("path") or "")).name
        if name in priority:
            return priority[name], name
        mime_type = str(item.get("mimeType") or "")
        if "tab-separated" in mime_type:
            return 3, name
        if mime_type.startswith("text/"):
            return 5, name
        return 9, name

    return sorted(valid, key=score)[:3]


async def _load_rule_log_context(
    *,
    runtime: Any,
    result_data: Any,
    failure_locator: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "schemaVersion": "run-rule-log-context.v1",
        "status": "unavailable",
        "reasonCode": "NO_FAILED_RULE",
        "logPaths": [],
        "matchedArtifactCount": 0,
        "matchedArtifacts": [],
        "tail": [],
    }
    failed_rule = failure_locator.get("failedRule")
    if not isinstance(failed_rule, dict):
        return {**base, "message": "No failed rule was identified for rule log lookup."}

    log_paths = [str(value) for value in failed_rule.get("logs") or [] if str(value or "").strip()]
    if not log_paths:
        return {
            **base,
            "reasonCode": "NO_RULE_LOGS",
            "message": "The failed rule did not report managed log paths.",
        }

    result = result_data if isinstance(result_data, dict) else {}
    artifacts = _dict_items(result.get("artifacts"))
    matched = _matched_log_artifacts(log_paths, artifacts)
    matched_summaries = [_artifact_log_summary(artifact) for artifact in matched]
    if not matched:
        return {
            **base,
            "reasonCode": "PATH_REFERENCE_ONLY",
            "logPaths": log_paths,
            "message": "Rule log paths were reported, but no managed result artifact matched them.",
        }

    previewable = [artifact for artifact in matched if _is_log_previewable_artifact(artifact)]
    if not previewable:
        return {
            **base,
            "reasonCode": "MATCHED_ARTIFACT_NOT_PREVIEWABLE",
            "logPaths": log_paths,
            "matchedArtifactCount": len(matched),
            "matchedArtifacts": matched_summaries,
            "message": "Matched rule log artifacts are not text-previewable.",
        }

    result_id = str(result.get("resultId") or "").strip()
    selected = _preferred_rule_log_artifact(previewable)
    if not result_id:
        return {
            **base,
            "reasonCode": "RESULT_ID_MISSING",
            "logPaths": log_paths,
            "matchedArtifactCount": len(matched),
            "matchedArtifacts": matched_summaries,
            "selectedArtifact": _artifact_log_summary(selected),
            "message": "Result id is required before rule log artifact preview can be loaded.",
        }

    artifact_id = str(selected.get("artifactId") or "")
    try:
        preview_response = await run_sync(
            lambda: runtime.get_result_preview(
                result_id=result_id,
                artifact_id=artifact_id,
            )
        )
    except Exception as exc:  # noqa: BLE001 - keep failure locator usable when preview storage is unavailable.
        return {
            **base,
            "reasonCode": "PREVIEW_UNAVAILABLE",
            "logPaths": log_paths,
            "matchedArtifactCount": len(matched),
            "matchedArtifacts": matched_summaries,
            "selectedArtifact": _artifact_log_summary(selected),
            "message": f"Rule log artifact preview is unavailable: {type(exc).__name__}",
        }

    preview_data = _unwrap_data(preview_response, {})
    preview = preview_data.get("preview") if isinstance(preview_data, dict) else {}
    lines = _preview_text_lines(preview)
    return {
        **base,
        "status": "available",
        "reasonCode": "PREVIEW_AVAILABLE",
        "logPaths": log_paths,
        "matchedArtifactCount": len(matched),
        "matchedArtifacts": matched_summaries,
        "selectedArtifact": _artifact_log_summary(selected),
        "previewKind": preview.get("kind") if isinstance(preview, dict) else None,
        "lineCount": len(lines),
        "tail": lines[-30:],
        "truncated": bool(preview.get("truncated")) if isinstance(preview, dict) else False,
    }


def _canonical_result_id_for_run(run_id: str) -> str:
    normalized = run_id.strip()
    return normalized if normalized.startswith("res_") else f"res_{normalized}"


def _build_failure_locator(
    *,
    run_id: str,
    run: Any,
    events: Any,
    stdout: Any,
    stderr: Any,
    results: Any,
    rules: Any,
) -> dict[str, Any]:
    run_data = run if isinstance(run, dict) else {}
    status = str(run_data.get("status") or "").lower()
    base = {
        "schemaVersion": "run-failure-locator.v1",
        "runId": run_id,
        "status": run_data.get("status"),
        "stage": run_data.get("stage"),
        "workflowRevisionId": run_data.get("workflowRevisionId"),
        "available": False,
    }
    if not _is_failed_status(status):
        return {
            **base,
            "reasonCode": "RUN_NOT_FAILED",
            "message": "Run is not in a failed state.",
        }

    event_items = _dict_items(events)
    rule_items = _dict_items((rules or {}).get("items") if isinstance(rules, dict) else [])
    failed_rule = _latest_failed_rule(rule_items)
    failure_event = _latest_failure_event(failed_rule.get("events") or []) if failed_rule else _latest_failure_event(event_items)
    stdout_lines = _log_lines(stdout)
    stderr_lines = _log_lines(stderr)
    result_data = results if isinstance(results, dict) else {}
    artifacts = _dict_items(result_data.get("artifacts"))
    related_artifacts = _related_artifacts(failed_rule, artifacts)
    related_ids = {str(artifact.get("artifactId") or "") for artifact in related_artifacts}
    lineage_edges = _related_lineage_edges(result_data.get("lineageEdges"), related_ids)

    if not failed_rule:
        return {
            **base,
            "available": True,
            "reasonCode": "RUN_FAILED_NO_RULE",
            "message": run_data.get("message") or (failure_event or {}).get("message") or "Run failed before a rule failure could be identified.",
            "runEvent": _failure_event_summary(failure_event),
            "logContext": _log_context(stdout_lines, stderr_lines),
            "artifactContext": {
                "artifactCount": len(artifacts),
                "relatedArtifactCount": 0,
                "relatedArtifacts": [],
                "lineageEdgeCount": 0,
                "lineageEdges": [],
            },
        }

    return {
        **base,
        "available": True,
        "reasonCode": "FAILED_RULE",
        "message": failed_rule.get("message") or (failure_event or {}).get("message") or run_data.get("message") or "",
        "failedRule": _failed_rule_summary(failed_rule, failure_event),
        "runEvent": _failure_event_summary(failure_event),
        "logContext": _log_context(stdout_lines, stderr_lines),
        "artifactContext": {
            "artifactCount": len(artifacts),
            "relatedArtifactCount": len(related_artifacts),
            "relatedArtifacts": related_artifacts[:8],
            "lineageEdgeCount": len(lineage_edges),
            "lineageEdges": lineage_edges[:8],
        },
    }


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _is_failed_status(status: Any) -> bool:
    return str(status or "").lower() in {"failed", "error"}


def _latest_failed_rule(rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    failed = [rule for rule in rules if _is_failed_status(rule.get("status"))]
    if not failed:
        return None
    return max(failed, key=lambda rule: str(rule.get("finishedAt") or rule.get("updatedAt") or rule.get("startedAt") or ""))


def _latest_failure_event(events: Any) -> dict[str, Any] | None:
    for event in reversed(_dict_items(events)):
        if _is_failed_status(event.get("status")) or "fail" in str(event.get("eventType") or "").lower():
            return event
    return None


def _failure_event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    return {
        "eventId": event.get("eventId") or event.get("ruleEventId"),
        "eventType": event.get("eventType"),
        "status": event.get("status"),
        "message": event.get("message"),
        "createdAt": event.get("createdAt"),
        "details": event.get("details") or event.get("detailsJson") or {},
    }


def _failed_rule_summary(rule: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "runRuleId": rule.get("runRuleId"),
        "ruleName": rule.get("ruleName"),
        "stepId": rule.get("stepId"),
        "runtimeStatusKey": rule.get("runtimeStatusKey"),
        "status": rule.get("status"),
        "attemptId": rule.get("attemptId"),
        "attemptNumber": rule.get("attemptNumber"),
        "leaseGeneration": rule.get("leaseGeneration"),
        "startedAt": rule.get("startedAt"),
        "finishedAt": rule.get("finishedAt"),
        "exitCode": rule.get("exitCode"),
        "message": rule.get("message"),
        "commandSummary": rule.get("commandSummary"),
        "inputs": list(rule.get("inputs") or []),
        "outputs": list(rule.get("outputs") or []),
        "logs": list(rule.get("logs") or []),
        "wildcards": rule.get("wildcards") or {},
        "latestFailureEvent": _failure_event_summary(event),
    }


def _log_lines(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    lines = payload.get("lines")
    return [str(line) for line in lines] if isinstance(lines, list) else []


def _log_context(stdout_lines: list[str], stderr_lines: list[str]) -> dict[str, Any]:
    return {
        "stdoutLineCount": len(stdout_lines),
        "stderrLineCount": len(stderr_lines),
        "stderrTail": stderr_lines[-30:],
    }


def _related_artifacts(rule: dict[str, Any] | None, artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rule:
        return []
    related_paths = {
        _normalize_path(value)
        for value in [*list(rule.get("outputs") or []), *list(rule.get("logs") or [])]
        if str(value or "").strip()
    }
    if not related_paths:
        return []
    return [
        artifact
        for artifact in artifacts
        if _normalize_path(artifact.get("path")) in related_paths or _normalize_path(artifact.get("storageUri")) in related_paths
    ]


def _related_lineage_edges(value: Any, related_artifact_ids: set[str]) -> list[dict[str, Any]]:
    if not related_artifact_ids:
        return []
    edges = _dict_items(value)
    return [
        edge
        for edge in edges
        if _lineage_edge_artifact_ids(edge) & related_artifact_ids
    ]


def _lineage_edge_artifact_ids(edge: dict[str, Any]) -> set[str]:
    ids = {
        str(edge.get("sourceArtifactId") or ""),
        str(edge.get("targetArtifactId") or ""),
        str(edge.get("artifactId") or ""),
    }
    payload = edge.get("payload")
    if isinstance(payload, dict):
        ids.update(
            {
                str(payload.get("sourceArtifactId") or ""),
                str(payload.get("targetArtifactId") or ""),
                str(payload.get("artifactId") or ""),
            }
        )
    return {value for value in ids if value}


def _matched_log_artifacts(log_paths: list[str], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_logs = {_normalize_path(path) for path in log_paths if _normalize_path(path)}
    if not normalized_logs:
        return []
    return [
        artifact
        for artifact in artifacts
        if _normalize_path(artifact.get("path")) in normalized_logs or _normalize_path(artifact.get("storageUri")) in normalized_logs
    ]


def _artifact_log_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    allowed = ("artifactId", "path", "kind", "mimeType", "sizeBytes", "sha256", "lifecycleState")
    return {key: artifact.get(key) for key in allowed if artifact.get(key) not in (None, "")}


def _is_log_previewable_artifact(artifact: dict[str, Any]) -> bool:
    path = _normalize_path(artifact.get("path")).lower()
    mime_type = str(artifact.get("mimeType") or "").lower()
    return (
        mime_type.startswith("text/")
        or "json" in mime_type
        or "xml" in mime_type
        or "log" in mime_type
        or path.endswith((".log", ".txt", ".out", ".err", ".stderr", ".stdout"))
    )


def _preferred_rule_log_artifact(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    def score(artifact: dict[str, Any]) -> tuple[int, str]:
        path = _normalize_path(artifact.get("path")).lower()
        mime_type = str(artifact.get("mimeType") or "").lower()
        if path.endswith((".log", ".stderr", ".err")):
            return (0, path)
        if "log" in mime_type:
            return (1, path)
        if mime_type.startswith("text/"):
            return (2, path)
        return (9, path)

    return sorted(artifacts, key=score)[0]


def _preview_text_lines(preview: Any) -> list[str]:
    if not isinstance(preview, dict):
        return []
    content = preview.get("content")
    if isinstance(content, str):
        return content.splitlines()
    rows = preview.get("rows")
    if isinstance(rows, list):
        columns = preview.get("columns")
        lines: list[str] = []
        if isinstance(columns, list):
            lines.append("\t".join(str(value) for value in columns))
        lines.extend(
            "\t".join(str(value) for value in row) if isinstance(row, list) else str(row)
            for row in rows
        )
        return lines
    return []


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def _catalog_item_from_pipeline(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("pipelineId") or ""),
        "kind": "pipeline",
        "name": str(item.get("name") or ""),
        "version": str(item.get("version") or ""),
        "category": str(item.get("category") or ""),
        "description": str(item.get("description") or ""),
        "engine": "snakemake",
        "status": str(item.get("status") or "installed"),
        "runnable": bool(item.get("enabled", True)),
        "source": "remote-runner",
        "inputSchema": item.get("inputsSchema") or {},
        "paramsSchema": item.get("paramsSchema") or {},
        "outputSchema": item.get("outputSchema") or {},
        "uiSchema": item.get("uiSchema") or {},
        "resources": item.get("resources") or {},
        "tags": list(item.get("tags") or []),
        "moduleCount": None,
        "inputCount": _schema_count(item.get("inputsSchema")),
        "outputCount": _artifact_count(item.get("outputSchema")),
    }


def _schema_count(schema: Any) -> int:
    if not isinstance(schema, dict):
        return 0
    if schema.get("type") == "array":
        return int(schema.get("minItems") or 0)
    properties = schema.get("properties")
    return len(properties) if isinstance(properties, dict) else 0


def _artifact_count(schema: Any) -> int:
    if not isinstance(schema, dict):
        return 0
    artifacts = schema.get("artifacts")
    return len(artifacts) if isinstance(artifacts, list) else 0


def _unwrap_data(payload: Any, default: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload if payload is not None else default
