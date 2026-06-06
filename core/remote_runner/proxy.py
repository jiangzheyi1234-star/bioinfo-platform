from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from config import resolve_runner_token
from core.remote_runner.client import RemoteRunnerHttpClient

def _is_manager_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "RemoteRunnerManagerError"


class RemoteRunnerProxyMixin:
    def get_health(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_health()

    def upload_content(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            "/api/v1/uploads",
            {
                "filename": kwargs["filename"],
                "contentBase64": kwargs["content_base64"],
                "mimeType": kwargs.get("mime_type") or "application/octet-stream",
            },
        )["data"]

    def list_tools(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/tools")["data"]["items"]

    def list_tool_index(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        query = urlencode(
            {
                "query": kwargs.get("query") or "",
                "limit": int(kwargs.get("limit") or 50),
                "offset": int(kwargs.get("offset") or 0),
                "source": kwargs.get("source") or "",
                "state": kwargs.get("state") or "",
            }
        )
        return client.get_json(f"/api/v1/tools/index?{query}")["data"]

    def add_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/tools", kwargs["payload"])["data"]

    def create_tool_prepare_job(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/tools/prepare-jobs", kwargs["payload"])["data"]

    def list_latest_tool_prepare_jobs(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        tool_ids = quote(",".join(str(item or "").strip() for item in kwargs.get("tool_ids") or []), safe="")
        return client.get_json(f"/api/v1/tools/prepare-jobs?toolIds={tool_ids}")["data"]["byToolId"]

    def get_tool_prepare_job(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/tools/prepare-jobs/{kwargs['job_id']}")["data"]

    def cancel_tool_prepare_job(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(f"/api/v1/tools/prepare-jobs/{kwargs['job_id']}/cancel", {})["data"]

    def update_tool_rule_template(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.patch_json(f"/api/v1/tools/{kwargs['tool_id']}/rule-template", kwargs["payload"])["data"]

    def delete_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.delete_json(f"/api/v1/tools/{kwargs['tool_id']}")["data"]

    def mark_tool_production_enabled(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(f"/api/v1/tools/{kwargs['tool_id']}/production", kwargs["payload"])["data"]

    def list_workflow_design_drafts(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/workflow-design-drafts")["data"]["items"]

    def create_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/workflow-design-drafts", kwargs["payload"])["data"]

    def get_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/workflow-design-drafts/{kwargs['draft_id']}")["data"]

    def update_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.patch_json(
            f"/api/v1/workflow-design-drafts/{kwargs['draft_id']}",
            kwargs["payload"],
        )["data"]

    def fork_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-design-drafts/{kwargs['draft_id']}/fork",
            kwargs["payload"],
        )["data"]

    def delete_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.delete_json(f"/api/v1/workflow-design-drafts/{kwargs['draft_id']}")["data"]

    def plan_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-design-drafts/{kwargs['draft_id']}/plan",
            kwargs["payload"],
        )["data"]

    def compile_workflow_design_draft(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(f"/api/v1/workflow-design-drafts/{kwargs['draft_id']}/compile", {})["data"]

    def submit_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            "/api/v1/runs",
            kwargs["payload"],
            extra_headers={
                "Idempotency-Key": kwargs["idempotency_key"],
                "X-Request-Id": kwargs["request_id"],
            },
        )

    def list_runs(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/runs")["data"]["items"]

    def get_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}")["data"]

    def get_run_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/events")["data"]

    def get_run_logs(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        stream = kwargs.get("stream") or "stdout"
        cursor = kwargs.get("cursor")
        path = f"/api/v1/runs/{kwargs['run_id']}/logs?stream={stream}"
        if cursor:
            path += f"&cursor={cursor}"
        return client.get_json(path)["data"]

    def get_run_results(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/results")["data"]

    def list_results(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json("/api/v1/results")["data"]["items"]

    def get_result(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/results/{kwargs['result_id']}")["data"]

    def get_result_preview(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        path = f"/api/v1/results/{kwargs['result_id']}/preview"
        artifact_id = kwargs.get("artifact_id")
        if artifact_id:
            path += f"?artifact_id={artifact_id}"
        return client.get_json(path)["data"]

    def _open_runner_tunnel(self, *, server_id: str, ssh_service, remote_port: int):
        try:
            return ssh_service.ensure_local_tunnel(
                f"runner-{server_id}",
                remote_host="127.0.0.1",
                remote_port=remote_port,
            )
        except (RuntimeError, OSError, EOFError) as exc:
            if _is_manager_error(exc):
                raise
            detail = str(exc) or exc.__class__.__name__
            raise self._manager_error(detail) from exc

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any], timeout: int = 5) -> RemoteRunnerHttpClient:
        token = resolve_runner_token(str(record.get("token_ref", "") or ""))
        if not token:
            raise self._manager_error("runner token not available")
        remote_port = self._require_service_port(record)
        tunnel = self._open_runner_tunnel(
            server_id=server_id,
            ssh_service=ssh_service,
            remote_port=remote_port,
        )
        return RemoteRunnerHttpClient(
            base_url=f"http://127.0.0.1:{tunnel.local_port}",
            token=token,
            timeout=timeout,
        )

    @staticmethod
    def _manager_error(message: str) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message)
