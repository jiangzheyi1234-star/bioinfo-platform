from __future__ import annotations

import hashlib
import re
from typing import Any

from .config import RemoteRunnerConfig
from .execution_query_storage import fetch_run_events, fetch_run_results, require_run
from .log_storage import fetch_log_lines
from .result_preview_service import build_result_preview_data
from .rule_execution_storage import fetch_run_rules


RUN_FAILURE_LOCATOR_SCHEMA = "run-failure-locator.v1"
RUN_RULE_LOG_CONTEXT_SCHEMA = "run-rule-log-context.v1"


def fetch_run_failure_locator(cfg: RemoteRunnerConfig, run_id: str) -> dict[str, Any]:
    run = require_run(cfg, run_id)
    status = str(run.get("status") or "").lower()
    base = {
        "schemaVersion": RUN_FAILURE_LOCATOR_SCHEMA,
        "runId": run_id,
        "status": run.get("status"),
        "stage": run.get("stage"),
        "workflowRevisionId": run.get("workflowRevisionId"),
        "available": False,
        "redactionPolicy": {
            "artifactPathsExposed": False,
            "storageUrisExposed": False,
            "commandSummaryExposed": False,
            "eventDetailsSanitized": True,
            "sourceLocationsSanitized": True,
            "runSpecExposed": False,
        },
    }
    if not _is_failed_status(status):
        return {
            **base,
            "reasonCode": "RUN_NOT_FAILED",
            "message": "Run is not in a failed state.",
            "ruleLogContext": _rule_log_context_base("NO_FAILED_RULE", "No failed rule was identified."),
        }

    events = fetch_run_events(cfg, run_id)
    stdout = fetch_log_lines(cfg, run_id, "stdout", None)
    stderr = fetch_log_lines(cfg, run_id, "stderr", None)
    results = fetch_run_results(cfg, run_id)
    rules = fetch_run_rules(cfg, run_id)
    rule_items = _dict_items(rules.get("items"))
    failed_rule = _latest_failed_rule(rule_items)
    failure_event = _latest_failure_event(failed_rule.get("events") or []) if failed_rule else _latest_failure_event(events)
    stdout_lines = _log_lines(stdout)
    stderr_lines = _log_lines(stderr)
    artifacts = _dict_items(results.get("artifacts"))
    related_artifacts = _related_artifacts(failed_rule, artifacts)

    if not failed_rule:
        return {
            **base,
            "available": True,
            "reasonCode": "RUN_FAILED_NO_RULE",
            "message": _public_message(
                run.get("message") or (failure_event or {}).get("message"),
                "Run failed before a rule failure could be identified.",
            ),
            "runEvent": _failure_event_summary(failure_event),
            "logContext": _log_context(stdout_lines, stderr_lines),
            "artifactContext": _artifact_context(artifacts, []),
            "ruleLogContext": _rule_log_context_base("NO_FAILED_RULE", "No failed rule was identified for rule log lookup."),
        }

    locator = {
        **base,
        "available": True,
        "reasonCode": "FAILED_RULE",
        "message": _public_message(
            failed_rule.get("message") or (failure_event or {}).get("message") or run.get("message"),
            "Failed rule message redacted by run-failure-locator.v1.",
        ),
        "failedRule": _failed_rule_summary(failed_rule, failure_event),
        "runEvent": _failure_event_summary(failure_event),
        "logContext": _log_context(stdout_lines, stderr_lines),
        "artifactContext": _artifact_context(artifacts, related_artifacts),
    }
    return {
        **locator,
        "ruleLogContext": _load_rule_log_context(
            cfg,
            result_id=_canonical_result_id_for_run(run_id),
            failed_rule=failed_rule,
            artifacts=artifacts,
        ),
    }


def build_rule_log_context(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    rule: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    return _load_rule_log_context(cfg, result_id=result_id, failed_rule=rule, artifacts=artifacts)


def public_rule_event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    return _failure_event_summary(event)


def public_rule_message(value: Any, fallback: str = "") -> str:
    return _public_message(value, fallback)


def public_rule_source_location(event: dict[str, Any] | None) -> dict[str, Any] | None:
    return _source_location(event)


def safe_rule_wildcards(value: Any) -> dict[str, Any]:
    return _safe_wildcards(value)


def _load_rule_log_context(
    cfg: RemoteRunnerConfig,
    *,
    result_id: str,
    failed_rule: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    log_paths = [str(value) for value in failed_rule.get("logs") or [] if str(value or "").strip()]
    if not log_paths:
        return _rule_log_context_base("NO_RULE_LOGS", "The failed rule did not report managed log paths.")
    matched = _matched_log_artifacts(log_paths, artifacts)
    matched_summaries = [_public_artifact_summary(artifact) for artifact in matched]
    if not matched:
        return {
            **_rule_log_context_base("PATH_REFERENCE_ONLY", "Rule log paths were reported, but no managed result artifact matched them."),
            "logReferenceCount": len(log_paths),
        }
    previewable = [artifact for artifact in matched if _is_log_previewable_artifact(artifact)]
    if not previewable:
        return {
            **_rule_log_context_base("MATCHED_ARTIFACT_NOT_PREVIEWABLE", "Matched rule log artifacts are not text-previewable."),
            "logReferenceCount": len(log_paths),
            "matchedArtifactCount": len(matched),
            "matchedArtifacts": matched_summaries,
        }
    selected = _preferred_rule_log_artifact(previewable)
    artifact_id = str(selected.get("artifactId") or "")
    try:
        preview_data = build_result_preview_data(cfg, result_id, artifact_id)
    except Exception as exc:  # noqa: BLE001 - locator remains useful when preview storage is temporarily unavailable.
        return {
            **_rule_log_context_base("PREVIEW_UNAVAILABLE", f"Rule log artifact preview is unavailable: {type(exc).__name__}"),
            "logReferenceCount": len(log_paths),
            "matchedArtifactCount": len(matched),
            "matchedArtifacts": matched_summaries,
            "selectedArtifact": _public_artifact_summary(selected),
        }
    preview = preview_data.get("preview") if isinstance(preview_data, dict) else {}
    lines = _preview_text_lines(preview)
    return {
        **_rule_log_context_base("PREVIEW_AVAILABLE", ""),
        "status": "available",
        "logReferenceCount": len(log_paths),
        "matchedArtifactCount": len(matched),
        "matchedArtifacts": matched_summaries,
        "selectedArtifact": _public_artifact_summary(selected),
        "previewKind": preview.get("kind") if isinstance(preview, dict) else None,
        "lineCount": len(lines),
        "tail": lines[-30:],
        "truncated": bool(preview.get("truncated")) if isinstance(preview, dict) else False,
    }


def _rule_log_context_base(reason_code: str, message: str) -> dict[str, Any]:
    return {
        "schemaVersion": RUN_RULE_LOG_CONTEXT_SCHEMA,
        "status": "unavailable",
        "reasonCode": reason_code,
        "message": message,
        "logReferenceCount": 0,
        "matchedArtifactCount": 0,
        "matchedArtifacts": [],
        "tail": [],
    }


def _artifact_context(artifacts: list[dict[str, Any]], related_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "artifactCount": len(artifacts),
        "relatedArtifactCount": len(related_artifacts),
        "relatedArtifacts": [_public_artifact_summary(artifact) for artifact in related_artifacts[:8]],
        "lineageEdgeCount": 0,
        "lineageEdges": [],
    }


def _failed_rule_summary(rule: dict[str, Any], event: dict[str, Any] | None) -> dict[str, Any]:
    latest_failure_event = _failure_event_summary(event)
    source_location = latest_failure_event.get("sourceLocation") if latest_failure_event else None
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
        "message": _public_message(rule.get("message"), ""),
        "inputCount": len(list(rule.get("inputs") or [])),
        "outputCount": len(list(rule.get("outputs") or [])),
        "logReferenceCount": len(list(rule.get("logs") or [])),
        "wildcards": _safe_wildcards(rule.get("wildcards")),
        "sourceLocation": source_location,
        "latestFailureEvent": latest_failure_event,
    }


def _failure_event_summary(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    summary = {
        "eventId": event.get("eventId") or event.get("ruleEventId"),
        "eventType": event.get("eventType"),
        "status": event.get("status"),
        "message": _public_message(event.get("message"), ""),
        "createdAt": event.get("createdAt"),
        "details": _public_event_details(event.get("details") or event.get("detailsJson") or {}),
    }
    source_location = _source_location(event)
    if source_location:
        summary["sourceLocation"] = source_location
    return summary


def _source_location(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    details = _event_details(event)
    file_text = _source_file_text(details)
    location_text = str(details.get("location") or "")
    if not file_text and location_text:
        file_text = _file_from_location(location_text)
    line = _source_line(details, location_text)
    basename = _safe_source_basename(file_text)
    if not basename:
        return None
    source = {
        "schemaVersion": "run-source-location.v1",
        "sourceKind": _source_kind(basename),
        "fileBasename": basename,
        "fileHash": _source_file_hash(file_text),
    }
    if line is not None:
        source["line"] = line
    return source


def _event_details(event: dict[str, Any]) -> dict[str, Any]:
    details = event.get("details") or event.get("detailsJson") or {}
    return details if isinstance(details, dict) else {}


def _source_file_text(details: dict[str, Any]) -> str:
    for key in ("file", "sourceFile", "snakefile"):
        value = str(details.get(key) or "").strip()
        if value:
            return value
    return ""


def _file_from_location(location: str) -> str:
    normalized = location.strip()
    if not normalized:
        return ""
    match = re.match(r"^(?P<file>.+?)(?::\d+)?(?:\s|$)", normalized)
    return str(match.group("file") if match else normalized).strip()


def _source_line(details: dict[str, Any], location: str) -> int | None:
    for key in ("line", "lineno", "lineNumber"):
        parsed = _safe_line_number(details.get(key))
        if parsed is not None:
            return parsed
    match = re.search(r":(?P<line>\d+)(?:\D|$)", location or "")
    return _safe_line_number(match.group("line")) if match else None


def _safe_line_number(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed < 1_000_000 else None


def _safe_source_basename(value: str) -> str:
    normalized = _normalize_path(value)
    basename = normalized.rsplit("/", 1)[-1].strip()
    if not basename or len(basename) > 80:
        return ""
    lowered = basename.lower()
    if any(token in lowered for token in ("secret", "token", "password", "credential", "api_key", "access_key")):
        return ""
    if "/" in basename or "\\" in basename or "://" in basename:
        return ""
    return basename if re.fullmatch(r"[A-Za-z0-9_. -]+", basename) else ""


def _source_kind(basename: str) -> str:
    lowered = basename.lower()
    if lowered == "snakefile" or lowered.endswith(".smk"):
        return "snakefile"
    return "rule-source"


def _source_file_hash(value: str) -> str:
    normalized = _normalize_path(value)
    return f"sha256:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _public_event_details(details: Any) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    public: dict[str, Any] = {}
    for key, value in details.items():
        normalized_key = str(key or "")
        if _sensitive_key(normalized_key) or _source_location_key(normalized_key):
            continue
        if isinstance(value, bool):
            public[normalized_key] = value
        elif isinstance(value, (int, float)):
            public[normalized_key] = value
        elif isinstance(value, str) and _safe_detail_text(value):
            public[normalized_key] = value[:120]
    return public


def _safe_wildcards(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    public: dict[str, Any] = {}
    for key, item in value.items():
        public_key = str(key)
        if _sensitive_key(public_key):
            continue
        if isinstance(item, str):
            if _safe_detail_text(item):
                public[public_key] = item[:120]
        elif isinstance(item, (int, float, bool)):
            public[public_key] = item
    return public


def _public_artifact_summary(artifact: dict[str, Any]) -> dict[str, Any]:
    allowed = ("artifactId", "kind", "mimeType", "sizeBytes", "sha256", "lifecycleState")
    return {key: artifact.get(key) for key in allowed if artifact.get(key) not in (None, "")}


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
    return [artifact for artifact in artifacts if _artifact_matches_any_path(artifact, related_paths)]


def _matched_log_artifacts(log_paths: list[str], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_logs = {_normalize_path(path) for path in log_paths if _normalize_path(path)}
    if not normalized_logs:
        return []
    return [artifact for artifact in artifacts if _artifact_matches_any_path(artifact, normalized_logs)]


def _artifact_matches_any_path(artifact: dict[str, Any], paths: set[str]) -> bool:
    candidates = [_normalize_path(artifact.get("path")), _normalize_path(artifact.get("storageUri"))]
    return any(_path_matches(candidate, target) for candidate in candidates for target in paths)


def _path_matches(candidate: str, target: str) -> bool:
    if not candidate or not target:
        return False
    return candidate == target or candidate.endswith(f"/{target}")


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
        lines.extend("\t".join(str(value) for value in row) if isinstance(row, list) else str(row) for row in rows)
        return lines
    return []


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in (value or []) if isinstance(item, dict)]


def _log_lines(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    lines = payload.get("lines")
    return [str(line) for line in lines] if isinstance(lines, list) else []


def _is_failed_status(status: Any) -> bool:
    return str(status or "").lower() in {"failed", "error"}


def _canonical_result_id_for_run(run_id: str) -> str:
    normalized = run_id.strip()
    return normalized if normalized.startswith("res_") else f"res_{normalized}"


def _normalize_path(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip()


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("path", "uri", "command", "shell", "input", "output", "log", "secret", "token"))


def _source_location_key(key: str) -> bool:
    return key.lower() in {"file", "line", "lineno", "linenumber", "location", "sourcefile", "snakefile", "traceback"}


def _safe_detail_text(value: str) -> bool:
    lowered = value.lower()
    if any(token in lowered for token in ("secret", "token", "password", "bearer ")):
        return False
    return not ("/" in value or "\\" in value or "://" in value)


def _public_message(value: Any, fallback: str) -> str:
    message = str(value or "").strip()
    if message and _safe_detail_text(message):
        return message[:240]
    return fallback
