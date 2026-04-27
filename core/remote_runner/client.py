from __future__ import annotations

import json
import http.client
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class RemoteRunnerClientError(RuntimeError):
    pass


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
            detail = ""
            try:
                payload = exc.read().decode("utf-8")
            except Exception:
                payload = ""
            if payload:
                try:
                    detail = str(json.loads(payload).get("detail") or "").strip()
                except Exception:
                    detail = payload.strip()
            message = f"runner http error {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RemoteRunnerClientError(message) from exc
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

    def get_health(self) -> dict[str, Any]:
        startup = self.get_json("/health/startup")
        live = self.get_json("/health/live")
        ready = self.get_json("/health/ready")
        checked_at = ready.get("startedAt") or live.get("startedAt") or startup.get("startedAt") or ""
        workflow = ready.get("workflowRuntime") if isinstance(ready.get("workflowRuntime"), dict) else {}
        pipeline_registry = ready.get("pipelineRegistry") if isinstance(ready.get("pipelineRegistry"), dict) else {}
        workflow_ok = workflow.get("ok")
        workflow_message = str(workflow.get("message") or "")
        pipeline_ok = pipeline_registry.get("ok")
        pipeline_message = str(pipeline_registry.get("message") or "")
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
                "ok": ready.get("status") == "ok",
                "message": "Remote runner control plane is ready." if ready.get("status") == "ok" else "Remote runner control plane is not ready.",
            },
            "workflowRuntime": {
                "ok": bool(workflow_ok) if workflow_ok is not None else ready.get("status") == "ok",
                "message": workflow_message or ("Workflow runtime is ready." if ready.get("status") == "ok" else "Workflow runtime is not ready."),
                "provider": str(workflow.get("provider") or ""),
                "source": str(workflow.get("source") or ""),
                "version": str(workflow.get("version") or ""),
                "snakemakeCommand": str(workflow.get("snakemakeCommand") or ""),
                "snakemakeVersion": str(workflow.get("snakemakeVersion") or ""),
            },
            "pipelineRegistry": {
                "ok": bool(pipeline_ok) if pipeline_ok is not None else ready.get("status") == "ok",
                "message": pipeline_message
                or ("Pipeline registry is ready." if ready.get("status") == "ok" else "Pipeline registry is not ready."),
                "count": int(pipeline_registry.get("count") or 0),
                "items": pipeline_registry.get("items") if isinstance(pipeline_registry.get("items"), list) else [],
            },
            "reasonCode": "" if ready.get("status") == "ok" else "RUNNER_NOT_READY",
            "checkedAt": checked_at,
        }
