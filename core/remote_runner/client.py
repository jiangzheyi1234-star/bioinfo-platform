from __future__ import annotations

import json
import hashlib
import http.client
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class RemoteRunnerClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class RemoteRunnerConflictError(RuntimeError):
    def __init__(self, payload: dict[str, Any]):
        super().__init__("remote runner conflict")
        self.payload = payload


def _http_error_detail_value(payload: str) -> Any:
    cleaned = payload.strip()
    if not cleaned:
        return None
    try:
        decoded = json.loads(cleaned)
    except json.JSONDecodeError:
        return cleaned
    if not isinstance(decoded, dict):
        return cleaned
    return decoded.get("detail")


def _http_error_detail(payload: str) -> str:
    detail = _http_error_detail_value(payload)
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail.strip()
    return json.dumps(detail, ensure_ascii=False, separators=(",", ":"))


@dataclass
class RemoteRunnerHttpClient:
    base_url: str
    token: str
    timeout: int = 5

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        raw_body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> dict[str, Any]:
        accepted = accepted_statuses or {200}
        if payload is not None and raw_body is not None:
            raise ValueError("REMOTE_RUNNER_REQUEST_BODY_AMBIGUOUS")
        body = None
        if raw_body is not None:
            body = bytes(raw_body)
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
            if any(str(key).lower() == "authorization" for key in extra_headers):
                raise ValueError("REMOTE_RUNNER_EXTRA_HEADER_FORBIDDEN: Authorization")
            headers.update(extra_headers)
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers=headers,
            data=body,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_payload = exc.read().decode("utf-8", errors="replace")
            if exc.code in accepted:
                decoded = json.loads(response_payload or "{}")
                if isinstance(decoded, dict):
                    return decoded
            detail_value = _http_error_detail_value(response_payload)
            if exc.code == 409 and isinstance(detail_value, dict):
                raise RemoteRunnerConflictError(detail_value) from exc
            detail = _http_error_detail(response_payload)
            message = f"runner http error {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RemoteRunnerClientError(message, status_code=exc.code, detail=detail_value) from exc
        except urllib.error.URLError as exc:
            raise RemoteRunnerClientError(str(exc.reason) or "runner unreachable") from exc
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as exc:
            raise RemoteRunnerClientError(str(exc) or "runner unreachable") from exc

    def _request_bytes(self, method: str, path: str) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self.token}"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {
                    "statusCode": int(response.status),
                    "content": response.read(),
                    "headers": {key.lower(): value for key, value in response.headers.items()},
                }
        except urllib.error.HTTPError as exc:
            response_payload = exc.read().decode("utf-8", errors="replace")
            detail_value = _http_error_detail_value(response_payload)
            detail = _http_error_detail(response_payload)
            message = f"runner http error {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RemoteRunnerClientError(message, status_code=exc.code, detail=detail_value) from exc
        except urllib.error.URLError as exc:
            raise RemoteRunnerClientError(str(exc.reason) or "runner unreachable") from exc
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as exc:
            raise RemoteRunnerClientError(str(exc) or "runner unreachable") from exc

    def get_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        return self._request_json("GET", path, accepted_statuses=accepted_statuses)

    def probe_json(self, path: str, *, accepted_statuses: set[int] | None = None) -> dict[str, Any]:
        accepted = accepted_statuses or {200}
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return {"httpStatus": int(response.status), "body": json.loads(response.read().decode("utf-8"))}
        except urllib.error.HTTPError as exc:
            response_payload = exc.read().decode("utf-8", errors="replace")
            if exc.code in accepted:
                return {"httpStatus": int(exc.code), "body": json.loads(response_payload or "{}")}
            return {
                "httpStatus": int(exc.code),
                "body": _decode_json_object(response_payload),
                "error": {
                    "reasonCode": "RUNNER_HTTP_ERROR",
                    "message": str(exc),
                    "errorType": type(exc).__name__,
                },
            }
        except urllib.error.URLError as exc:
            return _runner_unreachable_probe(exc)
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as exc:
            return _runner_unreachable_probe(exc)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request_json("POST", path, payload=payload, extra_headers=extra_headers)

    def post_bytes_json(
        self,
        path: str,
        body: bytes,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request_json("POST", path, raw_body=bytes(body), extra_headers=extra_headers)

    def patch_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("PATCH", path, payload=payload)

    def delete_json(self, path: str) -> dict[str, Any]:
        return self._request_json("DELETE", path)

    def create_upload(
        self,
        *,
        filename: str,
        content_base64: str,
        mime_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        return self.post_json(
            "/api/v1/uploads",
            {
                "filename": filename,
                "contentBase64": content_base64,
                "mimeType": mime_type,
            },
        )["data"]

    def create_run(
        self,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        request_id: str,
    ) -> dict[str, Any]:
        return self.post_json(
            "/api/v1/runs",
            payload,
            extra_headers={
                "Idempotency-Key": idempotency_key,
                "X-Request-Id": request_id,
            },
        )

    def list_workflow_triggers(self) -> dict[str, Any]:
        return self.get_json("/api/v1/workflow-triggers")["data"]

    def create_workflow_trigger(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json("/api/v1/workflow-triggers", payload)["data"]

    def submit_workflow_trigger_event(self, trigger_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/events", payload)

    def submit_workflow_trigger_inbox_event(
        self,
        trigger_id: str,
        payload: dict[str, Any] | None = None,
        *,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        path = f"/api/v1/workflow-triggers/{trigger_id}/inbox"
        if raw_body is not None:
            return self.post_bytes_json(path, raw_body, extra_headers=headers)
        return self.post_json(path, dict(payload or {}))

    def replay_workflow_trigger_inbox_event(
        self,
        trigger_id: str,
        inbox_event_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/inbox/{inbox_event_id}/replay", payload)

    def submit_workflow_trigger_readiness_event(self, trigger_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/readiness", payload)

    def preview_workflow_trigger_backfill(self, trigger_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/backfill/preview", payload)

    def launch_workflow_trigger_backfill(self, trigger_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(f"/api/v1/workflow-triggers/{trigger_id}/backfill/launch", payload)

    def list_workflow_trigger_events(self, trigger_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/workflow-triggers/{trigger_id}/events")["data"]

    def get_workflow_trigger_readiness_observation(self, trigger_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/workflow-triggers/{trigger_id}/readiness-observation")["data"]

    def list_workflow_trigger_inbox_events(
        self,
        trigger_id: str,
        *,
        state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "state": str(state or ""),
                "limit": int(limit),
            }
        )
        return self.get_json(f"/api/v1/workflow-triggers/{trigger_id}/inbox?{query}")["data"]

    def list_workflow_trigger_scheduler_ticks(self, *, limit: int = 20) -> dict[str, Any]:
        query = urllib.parse.urlencode({"limit": int(limit)})
        return self.get_json(f"/api/v1/workflow-trigger-scheduler/ticks?{query}")["data"]

    def list_workflow_backfill_launches(
        self,
        *,
        trigger_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "triggerId": str(trigger_id or ""),
                "limit": int(limit),
            }
        )
        return self.get_json(f"/api/v1/workflow-backfill-launches?{query}")["data"]

    def get_workflow_backfill_launch(self, launch_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/workflow-backfill-launches/{launch_id}")["data"]

    def cancel_workflow_backfill_launch(self, launch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(f"/api/v1/workflow-backfill-launches/{launch_id}/cancel", payload)["data"]

    def list_governance_audit_events(
        self,
        *,
        subject_kind: str | None = None,
        subject_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "subjectKind": str(subject_kind or ""),
                "subjectId": str(subject_id or ""),
                "action": str(action or ""),
                "limit": int(limit),
            }
        )
        return self.get_json(f"/api/v1/audit/events?{query}")["data"]

    def get_secret_provider_readiness(self) -> dict[str, Any]:
        return self.get_json("/api/v1/secrets/provider-readiness")["data"]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}")["data"]

    def get_run_execution_context(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}/execution-context")["data"]

    def get_run_attempts(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}/attempts")["data"]

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}/results")["data"]

    def get_run_rules(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}/rules")["data"]

    def get_result(self, result_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/results/{result_id}")["data"]

    def list_results(self) -> list[dict[str, Any]]:
        return self.get_json("/api/v1/results")["data"]["items"]

    def get_result_preview(self, result_id: str, *, artifact_id: str | None = None) -> dict[str, Any]:
        path = f"/api/v1/results/{result_id}/preview"
        if artifact_id:
            path += f"?artifact_id={artifact_id}"
        return self.get_json(path)["data"]

    def get_result_audit(self, result_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/results/{result_id}/audit")["data"]

    def export_result_package(
        self,
        result_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.post_json(f"/api/v1/results/{result_id}/export", dict(payload or {}))["data"]

    def list_result_package_exports(
        self,
        result_id: str,
        *,
        lifecycle_state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        result_part = urllib.parse.quote(result_id, safe="")
        query = urllib.parse.urlencode(
            {
                "lifecycleState": str(lifecycle_state or ""),
                "limit": int(limit),
            }
        )
        return self.get_json(f"/api/v1/results/{result_part}/exports?{query}")["data"]

    def download_result_package(self, result_id: str, package_export_id: str) -> dict[str, Any]:
        result_part = urllib.parse.quote(result_id, safe="")
        export_part = urllib.parse.quote(package_export_id, safe="")
        return self._request_bytes(
            "GET",
            f"/api/v1/results/{result_part}/exports/{export_part}/download",
        )

    def retire_result_package(
        self,
        result_id: str,
        package_export_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result_part = urllib.parse.quote(result_id, safe="")
        export_part = urllib.parse.quote(package_export_id, safe="")
        return self.post_json(
            f"/api/v1/results/{result_part}/exports/{export_part}/retire",
            dict(payload or {}),
        )["data"]

    def delete_result_package_bytes(
        self,
        result_id: str,
        package_export_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result_part = urllib.parse.quote(result_id, safe="")
        export_part = urllib.parse.quote(package_export_id, safe="")
        return self.post_json(
            f"/api/v1/results/{result_part}/exports/{export_part}/bytes/delete",
            dict(payload or {}),
        )["data"]

    def get_artifact_lifecycle_usage(self, *, quota_bytes: int | None = None) -> dict[str, Any]:
        query = urllib.parse.urlencode({"quotaBytes": quota_bytes if quota_bytes is not None else ""})
        return self.get_json(f"/api/v1/artifacts/lifecycle/usage?{query}")["data"]

    def list_artifact_lifecycle_controller_ticks(self, *, limit: int = 20) -> dict[str, Any]:
        query = urllib.parse.urlencode({"limit": int(limit)})
        return self.get_json(f"/api/v1/artifacts/lifecycle/controller/ticks?{query}")["data"]

    def preview_artifact_gc(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.post_json("/api/v1/artifacts/lifecycle/gc/preview", dict(payload or {}))["data"]

    def run_artifact_gc(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.post_json("/api/v1/artifacts/lifecycle/gc/run", dict(payload or {}))["data"]

    def list_artifact_cache_entries(
        self,
        *,
        workflow_revision_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "workflowRevisionId": str(workflow_revision_id or ""),
                "limit": int(limit),
            }
        )
        return self.get_json(f"/api/v1/artifacts/cache/entries?{query}")["data"]

    def list_artifact_cache_pins(
        self,
        *,
        cache_entry_id: str | None = None,
        state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        query = urllib.parse.urlencode(
            {
                "cacheEntryId": str(cache_entry_id or ""),
                "state": str(state or ""),
                "limit": int(limit),
            }
        )
        return self.get_json(f"/api/v1/artifacts/cache/pins?{query}")["data"]

    def retain_artifact_cache_pin(self, cache_entry_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        entry_part = urllib.parse.quote(cache_entry_id, safe="")
        return self.post_json(f"/api/v1/artifacts/cache/entries/{entry_part}/retain", dict(payload or {}))["data"]

    def release_artifact_cache_pin(self, cache_pin_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        pin_part = urllib.parse.quote(cache_pin_id, safe="")
        return self.post_json(f"/api/v1/artifacts/cache/pins/{pin_part}/release", dict(payload or {}))["data"]

    def lookup_artifact_cache(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.post_json("/api/v1/artifacts/cache/lookup", dict(payload or {}))["data"]

    def get_health(self) -> dict[str, Any]:
        startup = self.get_json("/health/startup", accepted_statuses={200, 503})
        live = self.get_json("/health/live")
        ready = self.get_json("/health/ready", accepted_statuses={200, 503})
        workflow = ready.get("workflowRuntime") if isinstance(ready.get("workflowRuntime"), dict) else {}
        pipeline_registry = ready.get("pipelineRegistry") if isinstance(ready.get("pipelineRegistry"), dict) else {}
        ready_ok = ready.get("status") == "ok"
        workflow_ok = workflow.get("ok")
        workflow_message = str(workflow.get("message") or "")
        pipeline_ok = pipeline_registry.get("ok")
        pipeline_message = str(pipeline_registry.get("message") or "")
        normalized_workflow_ok = bool(workflow_ok) if workflow_ok is not None else ready_ok
        normalized_pipeline_ok = bool(pipeline_ok) if pipeline_ok is not None else ready_ok
        ready_message = "Remote runner control plane is ready."
        reason_code = ""
        if not ready_ok:
            detail_parts: list[str] = []
            if not normalized_workflow_ok:
                detail_parts.append(
                    f"workflow runtime: {workflow_message or 'Workflow runtime is not ready.'}"
                )
                reason_code = "WORKFLOW_RUNTIME_NOT_READY"
            if not normalized_pipeline_ok:
                detail_parts.append(
                    f"pipeline registry: {pipeline_message or 'Pipeline registry is not ready.'}"
                )
                if not reason_code:
                    reason_code = "PIPELINE_REGISTRY_NOT_READY"
            if detail_parts:
                ready_message = "; ".join(detail_parts)
            else:
                ready_message = "Remote runner control plane is not ready."
                reason_code = "RUNNER_NOT_READY"
        return {
            "startup": {
                "ok": startup.get("status") == "ok",
                "message": "Remote runner startup checks passed." if startup.get("status") == "ok" else "Remote runner startup checks failed.",
            },
            "live": {
                "ok": live.get("status") == "ok",
                "message": "Remote runner process is alive." if live.get("status") == "ok" else "Remote runner process is not healthy.",
            },
            "ready": {
                "ok": ready_ok,
                "message": ready_message,
            },
            "workflowRuntime": {
                "ok": normalized_workflow_ok,
                "message": workflow_message or ("Workflow runtime is ready." if ready_ok else "Workflow runtime is not ready."),
                "provider": str(workflow.get("provider") or ""),
                "source": str(workflow.get("source") or ""),
                "version": str(workflow.get("version") or ""),
                "snakemakeCommand": str(workflow.get("snakemakeCommand") or ""),
                "snakemakeVersion": str(workflow.get("snakemakeVersion") or ""),
                "workflowProfileConfigured": bool(workflow.get("workflowProfileConfigured")),
                "workflowProfileOk": bool(workflow.get("workflowProfileOk")),
                "workflowProfileMessage": str(workflow.get("workflowProfileMessage") or ""),
                "workflowProfileDir": str(workflow.get("workflowProfileDir") or ""),
                "workflowProfileName": str(workflow.get("workflowProfileName") or ""),
                "workflowProfilePath": str(workflow.get("workflowProfilePath") or ""),
            },
            "pipelineRegistry": {
                "ok": normalized_pipeline_ok,
                "message": pipeline_message
                or ("Pipeline registry is ready." if ready_ok else "Pipeline registry is not ready."),
                "count": int(pipeline_registry.get("count") or 0),
                "items": pipeline_registry.get("items") if isinstance(pipeline_registry.get("items"), list) else [],
            },
            "reasonCode": reason_code,
            "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_execution_diagnostics(self) -> dict[str, Any]:
        return self.get_json("/health/execution-diagnostics")["data"]

    def get_operator_diagnostics(
        self,
        *,
        server_id: str = "",
        run_id: str = "",
        scenario_id: str = "",
        release_tag: str = "",
        source_commit: str = "",
    ) -> dict[str, Any]:
        remote_runner = {
            endpoint: self.probe_json(endpoint, accepted_statuses={200, 503})
            for endpoint in (
                "/health/startup",
                "/health/live",
                "/health/ready",
                "/health/meta",
                "/health/workers",
                "/health/execution-diagnostics",
            )
        }
        collected_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        bundle = {
            "schemaVersion": "operator-diagnostics-bundle.v1",
            "collectedAt": collected_at,
            "identity": {
                "serverId": str(server_id or ""),
                "runId": str(run_id or ""),
                "scenarioId": str(scenario_id or ""),
            },
            "release": {
                "releaseTag": str(release_tag or ""),
                "sourceCommit": str(source_commit or ""),
            },
            "remoteRunner": remote_runner,
            "includedSections": ["remoteRunner"],
            "redactionPolicy": {"schemaVersion": "diagnostics-redaction.v1"},
        }
        bundle["summary"] = _operator_diagnostics_summary(remote_runner)
        bundle["bundleHash"] = _stable_bundle_hash(bundle)
        bundle["bundleId"] = f"opdiag_{bundle['bundleHash'][:16]}"
        return bundle


def _decode_json_object(payload: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(payload or "{}")
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _runner_unreachable_probe(exc: BaseException) -> dict[str, Any]:
    return {
        "httpStatus": None,
        "body": None,
        "error": {
            "reasonCode": "RUNNER_UNREACHABLE",
            "message": str(exc),
            "errorType": type(exc).__name__,
        },
    }


def _operator_diagnostics_summary(remote_runner: dict[str, Any]) -> dict[str, Any]:
    endpoint_statuses: dict[str, Any] = {}
    reason_codes: list[str] = []
    reachable = False
    for endpoint, payload in sorted(remote_runner.items()):
        status = _operator_endpoint_status(payload)
        endpoint_statuses[endpoint.strip("/").split("/")[-1].replace("-", "_")] = status
        reachable = reachable or status.get("httpStatus") is not None
        reason_code = str(status.get("reasonCode") or "").strip()
        if reason_code and reason_code not in reason_codes:
            reason_codes.append(reason_code)
    if not reachable and "RUNNER_UNREACHABLE" not in reason_codes:
        reason_codes.append("RUNNER_UNREACHABLE")
    ready = endpoint_statuses.get("ready") or {}
    return {
        "remoteRunnerReachable": reachable,
        "readinessOk": bool(ready.get("ok")),
        "reasonCodes": reason_codes,
        "endpointStatuses": endpoint_statuses,
    }


def _operator_endpoint_status(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"httpStatus": None, "ok": False, "reasonCode": "RUNNER_UNREACHABLE"}
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    readiness = data.get("readiness") if isinstance(data.get("readiness"), dict) else {}
    reason_code = (
        body.get("reasonCode")
        or data.get("reasonCode")
        or readiness.get("reasonCode")
        or error.get("reasonCode")
        or ""
    )
    status = body.get("status") or data.get("status") or ""
    return {
        "httpStatus": payload.get("httpStatus"),
        "ok": _operator_status_ok(body=body, data=data, status=status),
        "status": str(status or ""),
        "reasonCode": str(reason_code or ""),
        "error": dict(error),
    }


def _operator_status_ok(*, body: dict[str, Any], data: dict[str, Any], status: Any) -> bool:
    if "ok" in body:
        return bool(body.get("ok"))
    if "ok" in data:
        return bool(data.get("ok"))
    return str(status or "").lower() == "ok"


def _stable_bundle_hash(bundle: dict[str, Any]) -> str:
    comparable = {key: value for key, value in bundle.items() if key not in {"bundleHash", "bundleId"}}
    payload = json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
