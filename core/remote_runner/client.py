from __future__ import annotations

import json
import http.client
import time
import urllib.error
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
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if extra_headers:
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

    def get_json(self, path: str) -> dict[str, Any]:
        return self._request_json("GET", path)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._request_json("POST", path, payload=payload, extra_headers=extra_headers)

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

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}")["data"]

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/runs/{run_id}/results")["data"]

    def get_result(self, result_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/v1/results/{result_id}")["data"]

    def list_results(self) -> list[dict[str, Any]]:
        return self.get_json("/api/v1/results")["data"]["items"]

    def get_result_preview(self, result_id: str, *, artifact_id: str | None = None) -> dict[str, Any]:
        path = f"/api/v1/results/{result_id}/preview"
        if artifact_id:
            path += f"?artifact_id={artifact_id}"
        return self.get_json(path)["data"]

    def get_health(self) -> dict[str, Any]:
        startup = self.get_json("/health/startup")
        live = self.get_json("/health/live")
        ready = self.get_json("/health/ready")
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
