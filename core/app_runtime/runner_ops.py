from __future__ import annotations

from typing import Any, Optional

from core.app_runtime.runner_database_ops import RunnerDatabaseOperationsMixin
from core.app_runtime.runner_execution_ops import RunnerExecutionOperationsMixin
from core.app_runtime.runner_file_ops import RunnerFileOperationsMixin
from core.app_runtime.runner_pipeline_ops import RunnerPipelineOperationsMixin
from core.app_runtime.runner_tool_ops import RunnerToolOperationsMixin
from core.app_runtime.runner_workflow_design_ops import RunnerWorkflowDesignOperationsMixin
from core.app_runtime.remote_runner_call import call_remote_runner

from .errors import RuntimeServiceError


class RunnerOperationsMixin(
    RunnerDatabaseOperationsMixin,
    RunnerExecutionOperationsMixin,
    RunnerFileOperationsMixin,
    RunnerPipelineOperationsMixin,
    RunnerToolOperationsMixin,
    RunnerWorkflowDesignOperationsMixin,
):
    def stop_remote_runner_service(self) -> dict[str, Any]:
        return self.runner.stop_remote_runner_service()

    def get_runner_execution_diagnostics(self, server_id: str | None = None) -> dict[str, Any]:
        selected_server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=server_id)
        return self._call_remote_runner(
            self._service_locator.remote_runner_manager.get_execution_diagnostics,
            server_id=selected_server_id,
            ssh_service=ssh,
            server_record=record,
        )

    def get_runner_operator_diagnostics(
        self,
        server_id: str | None = None,
        *,
        run_id: str = "",
        scenario_id: str = "",
    ) -> dict[str, Any]:
        selected_server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=server_id)
        return self._call_remote_runner(
            self._service_locator.remote_runner_manager.get_operator_diagnostics,
            server_id=selected_server_id,
            ssh_service=ssh,
            server_record=record,
            run_id=run_id,
            scenario_id=scenario_id,
        )

    @staticmethod
    def _call_remote_runner(func, /, **kwargs):
        return call_remote_runner(func, **kwargs)

    def _require_existing_runner_ready(
        self,
        *,
        preferred_server_id: Optional[str] = None,
    ):
        server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=preferred_server_id)
        snapshot = record.get("last_health_snapshot")
        if isinstance(snapshot, dict) and not bool((snapshot.get("ready") or {}).get("ok")):
            message = str((snapshot.get("ready") or {}).get("message") or "Remote runner is not ready.")
            raise RuntimeServiceError(message)
        return server_id, ssh, record

    def _require_existing_runner_prepared(
        self,
        *,
        preferred_server_id: Optional[str] = None,
    ):
        ssh_status = self._get_ssh_status_unlocked()
        server = self._build_primary_server_identity(ssh_status=ssh_status)
        if server is None:
            raise RuntimeServiceError("No server configured")
        server_id = str(preferred_server_id or server["serverId"] or "").strip() or server["serverId"]
        if server_id != server["serverId"]:
            raise RuntimeServiceError(f"Server not found: {server_id}")
        if not bool(server.get("connected")):
            raise RuntimeServiceError("SSH is not connected")
        record = self._get_server_registry_entry(server_id)
        if not record.get("bootstrap_version"):
            raise RuntimeServiceError("Remote runner is not prepared")
        ssh = self._ensure_ssh_connected()
        return server_id, ssh, record
