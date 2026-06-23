from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from config import resolve_runner_token
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient
from core.remote_runner.layout import remote_runner_bootstrap_layout


def _is_manager_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "RemoteRunnerManagerError"


def _record_service_port(record: dict[str, Any]) -> int | None:
    try:
        port = int(record.get("service_port") or 0)
    except (TypeError, ValueError):
        return None
    if port <= 0 or port > 65535:
        return None
    return port


def _manager_error_blocks_runtime_state_resync(exc: Exception) -> bool:
    detail = str(exc)
    return (
        "runner token not available" in detail
        or "service_port is missing" in detail
        or "service_port is invalid" in detail
    )


class RemoteRunnerProxyMixin:
    def get_health(self, **kwargs) -> dict[str, Any]:
        return self._get_health_with_runtime_state_resync(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=dict(kwargs["server_record"]),
        )

    def get_execution_diagnostics(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_execution_diagnostics()

    def get_operator_diagnostics(self, **kwargs) -> dict[str, Any]:
        record = kwargs["server_record"]
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=record,
        )
        metadata = record.get("bootstrap_metadata") if isinstance(record.get("bootstrap_metadata"), dict) else {}
        release = metadata.get("release") if isinstance(metadata.get("release"), dict) else {}
        return client.get_operator_diagnostics(
            server_id=str(kwargs["server_id"]),
            run_id=str(kwargs.get("run_id") or ""),
            scenario_id=str(kwargs.get("scenario_id") or ""),
            release_tag=str(release.get("releaseTag") or record.get("bootstrap_version") or ""),
            source_commit=str(release.get("sourceCommit") or ""),
        )

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

    def list_tool_prepare_job_queue(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        query = urlencode(
            {
                "status": kwargs.get("status") or "",
                "limit": int(kwargs.get("limit") or 50),
                "offset": int(kwargs.get("offset") or 0),
            }
        )
        return client.get_json(f"/api/v1/tools/prepare-jobs/queue?{query}")["data"]

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

    def list_workflow_triggers(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        return client.get_json("/api/v1/workflow-triggers")["data"]

    def create_workflow_trigger(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/workflow-triggers", kwargs["payload"])["data"]

    def submit_workflow_trigger_event(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/events",
            kwargs["payload"],
        )

    def submit_workflow_trigger_inbox_event(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/inbox",
            kwargs["payload"],
        )

    def replay_workflow_trigger_inbox_event(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/inbox/{kwargs['inbox_event_id']}/replay",
            kwargs["payload"],
        )

    def submit_workflow_trigger_readiness_event(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/readiness",
            kwargs["payload"],
        )

    def preview_workflow_trigger_backfill(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/backfill/preview",
            kwargs["payload"],
        )

    def launch_workflow_trigger_backfill(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/backfill/launch",
            kwargs["payload"],
        )

    def list_workflow_trigger_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        return client.get_json(f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/events")["data"]

    def list_workflow_trigger_inbox_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        query = urlencode(
            {
                "state": kwargs.get("state") or "",
                "limit": int(kwargs.get("limit") or 100),
            }
        )
        return client.get_json(f"/api/v1/workflow-triggers/{kwargs['trigger_id']}/inbox?{query}")["data"]

    def list_workflow_backfill_launches(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        query = urlencode(
            {
                "triggerId": kwargs.get("trigger_id") or "",
                "limit": int(kwargs.get("limit") or 100),
            }
        )
        return client.get_json(f"/api/v1/workflow-backfill-launches?{query}")["data"]

    def get_workflow_backfill_launch(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        return client.get_json(f"/api/v1/workflow-backfill-launches/{kwargs['launch_id']}")["data"]

    def cancel_workflow_backfill_launch(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        return client.post_json(
            f"/api/v1/workflow-backfill-launches/{kwargs['launch_id']}/cancel",
            kwargs["payload"],
        )["data"]

    def list_governance_audit_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        query = urlencode(
            {
                "subjectKind": kwargs.get("subject_kind") or "",
                "subjectId": kwargs.get("subject_id") or "",
                "action": kwargs.get("action") or "",
                "limit": int(kwargs.get("limit") or 100),
            }
        )
        return client.get_json(f"/api/v1/audit/events?{query}")["data"]

    def list_runs(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=20,
        )
        return client.get_json("/api/v1/runs")["data"]["items"]

    def get_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}")["data"]

    def cancel_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(f"/api/v1/runs/{kwargs['run_id']}/cancel", {})["data"]

    def retry_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(f"/api/v1/runs/{kwargs['run_id']}/retry", kwargs["payload"])["data"]

    def get_run_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/events")["data"]

    def get_run_execution_context(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/execution-context")["data"]

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

    def get_run_rules(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/rules")["data"]

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

    def get_result_audit(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.get_json(f"/api/v1/results/{kwargs['result_id']}/audit")["data"]

    def export_result_package(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/results/{kwargs['result_id']}/export",
            dict(kwargs.get("payload") or {}),
        )["data"]

    def get_artifact_lifecycle_usage(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        query = urlencode({"quotaBytes": kwargs.get("quota_bytes") or ""})
        return client.get_json(f"/api/v1/artifacts/lifecycle/usage?{query}")["data"]

    def preview_artifact_gc(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/artifacts/lifecycle/gc/preview", dict(kwargs.get("payload") or {}))["data"]

    def run_artifact_gc(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/artifacts/lifecycle/gc/run", dict(kwargs.get("payload") or {}))["data"]

    def list_artifact_cache_entries(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        query = urlencode(
            {
                "workflowRevisionId": kwargs.get("workflow_revision_id") or "",
                "limit": int(kwargs.get("limit") or 100),
            }
        )
        return client.get_json(f"/api/v1/artifacts/cache/entries?{query}")["data"]

    def lookup_artifact_cache(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json("/api/v1/artifacts/cache/lookup", dict(kwargs.get("payload") or {}))["data"]

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

    def _get_health_with_runtime_state_resync(
        self,
        *,
        server_id: str,
        ssh_service,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            client, service_port, tunnel_port = self._get_client_connection(
                server_id=server_id,
                ssh_service=ssh_service,
                record=record,
            )
        except Exception as exc:
            if not _is_manager_error(exc) or _manager_error_blocks_runtime_state_resync(exc):
                raise
            stale_service_port = _record_service_port(record)
            if stale_service_port is None:
                raise
            return self._get_health_after_runtime_state_resync(
                server_id=server_id,
                ssh_service=ssh_service,
                record=record,
                stale_service_port=stale_service_port,
                stale_error=exc,
            )
        try:
            health = client.get_health()
        except RemoteRunnerClientError as exc:
            return self._get_health_after_runtime_state_resync(
                server_id=server_id,
                ssh_service=ssh_service,
                record=record,
                stale_service_port=service_port,
                stale_error=exc,
            )
        return self._attach_connection_metadata(
            health,
            service_port=service_port,
            tunnel_port=tunnel_port,
        )

    def _get_health_after_runtime_state_resync(
        self,
        *,
        server_id: str,
        ssh_service,
        record: dict[str, Any],
        stale_service_port: int,
        stale_error: Exception,
    ) -> dict[str, Any]:
        version = str(record.get("bootstrap_version") or REMOTE_RUNNER_VERSION)
        home_dir = self._resolve_remote_home(ssh_service)
        paths = remote_runner_bootstrap_layout(home_dir, version)
        state = self._wait_for_runtime_state(
            ssh_service=ssh_service,
            remote_runtime_state=paths.runtime_state,
            version=version,
            attempts=1,
            delay_seconds=0,
        )
        service_port = int(state["bindPort"])
        if service_port == stale_service_port:
            raise stale_error
        token = self._resolve_runner_token(record)
        tunnel = self._open_runner_tunnel(
            server_id=server_id,
            ssh_service=ssh_service,
            remote_port=service_port,
        )
        client = RemoteRunnerHttpClient(
            base_url=f"http://127.0.0.1:{tunnel.local_port}",
            token=token,
            timeout=5,
        )
        runtime_state = {
            "bindPort": service_port,
            "pid": int(state.get("pid") or 0),
            "version": str(state.get("version") or version),
        }
        try:
            health = client.get_health()
        except RemoteRunnerClientError as exc:
            detail_payload = dict(exc.detail) if isinstance(exc.detail, dict) else {}
            detail_payload.setdefault("message", str(exc))
            detail_payload["servicePort"] = service_port
            detail_payload["tunnelPort"] = int(tunnel.local_port)
            detail_payload["runtimeState"] = runtime_state
            detail_payload["connectionResynced"] = True
            raise RemoteRunnerClientError(
                str(exc),
                status_code=exc.status_code,
                detail=detail_payload,
            ) from exc
        health = self._attach_connection_metadata(
            health,
            service_port=service_port,
            tunnel_port=int(tunnel.local_port),
        )
        health["runtimeState"] = runtime_state
        health["connectionResynced"] = True
        return health

    @classmethod
    def _attach_connection_metadata(
        cls,
        health: dict[str, Any],
        *,
        service_port: int,
        tunnel_port: int,
    ) -> dict[str, Any]:
        health["servicePort"] = service_port
        health["tunnelPort"] = tunnel_port
        return health

    @classmethod
    def _resolve_runner_token(cls, record: dict[str, Any]) -> str:
        token = resolve_runner_token(str(record.get("token_ref", "") or ""))
        if not token:
            raise cls._manager_error("runner token not available")
        return token

    def _get_client_connection(
        self,
        *,
        server_id: str,
        ssh_service,
        record: dict[str, Any],
        timeout: int = 5,
    ) -> tuple[RemoteRunnerHttpClient, int, int]:
        token = self._resolve_runner_token(record)
        remote_port = self._require_service_port(record)
        tunnel = self._open_runner_tunnel(
            server_id=server_id,
            ssh_service=ssh_service,
            remote_port=remote_port,
        )
        return (
            RemoteRunnerHttpClient(
                base_url=f"http://127.0.0.1:{tunnel.local_port}",
                token=token,
                timeout=timeout,
            ),
            remote_port,
            int(tunnel.local_port),
        )

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any], timeout: int = 5) -> RemoteRunnerHttpClient:
        client, _, _ = self._get_client_connection(
            server_id=server_id,
            ssh_service=ssh_service,
            record=record,
            timeout=timeout,
        )
        return client


    @staticmethod
    def _manager_error(message: str) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message)
