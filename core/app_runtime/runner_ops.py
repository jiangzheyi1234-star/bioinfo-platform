from __future__ import annotations

import time
from typing import Any, Optional

from config import delete_runner_token
from core.app_runtime.runner_database_ops import RunnerDatabaseOperationsMixin
from core.app_runtime.runner_execution_ops import RunnerExecutionOperationsMixin
from core.app_runtime.runner_file_ops import RunnerFileOperationsMixin
from core.app_runtime.runner_pipeline_ops import RunnerPipelineOperationsMixin
from core.app_runtime.runner_stop_state import raise_if_runner_manually_stopped
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
    def stop_remote_runner_service(self, server_id: str) -> dict[str, Any]:
        return self.runner.stop_remote_runner_service(server_id)

    def start_remote_runner(self, server_id: str) -> dict[str, Any]:
        return self._bootstrap_remote_runner(server_id=server_id, action="start")

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

    def preview_runner_release_prune(self, server_id: str | None = None) -> dict[str, Any]:
        selected_server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=server_id)
        return self._call_remote_runner(
            self._service_locator.remote_runner_manager.preview_release_prune,
            server_id=selected_server_id,
            ssh_service=ssh,
            server_record=record,
        )

    def run_runner_release_prune(self, server_id: str | None = None, *, plan_hash: str) -> dict[str, Any]:
        selected_server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=server_id)
        return self._call_remote_runner(
            self._service_locator.remote_runner_manager.run_release_prune,
            server_id=selected_server_id,
            ssh_service=ssh,
            server_record=record,
            plan_hash=plan_hash,
        )

    def preview_runner_uninstall(self, server_id: str | None = None) -> dict[str, Any]:
        selected_server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=server_id)
        return self._call_remote_runner(
            self._service_locator.remote_runner_manager.preview_uninstall,
            server_id=selected_server_id,
            ssh_service=ssh,
            server_record=record,
        )

    def run_runner_uninstall(self, server_id: str | None = None, *, plan_hash: str) -> dict[str, Any]:
        selected_server_id, ssh, record = self._require_existing_runner_prepared(preferred_server_id=server_id)
        result = self._call_remote_runner(
            self._service_locator.remote_runner_manager.run_uninstall,
            server_id=selected_server_id,
            ssh_service=ssh,
            server_record=record,
            plan_hash=plan_hash,
        )
        token_ref = str(record.get("token_ref") or "")
        if token_ref:
            delete_runner_token(token_ref)
        close_tunnel = getattr(ssh, "close_local_tunnel", None)
        if callable(close_tunnel):
            close_tunnel(f"runner-{selected_server_id}")
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        health = _runner_uninstalled_health(selected_server_id, completed_at=completed_at)
        registry_entry = self._replace_server_registry_entry(
            selected_server_id,
            {
                "last_health_snapshot": health,
                "runner_uninstalled_at": completed_at,
                "runner_uninstall": {
                    "schemaVersion": result.get("schemaVersion"),
                    "planHash": result.get("planHash"),
                    "removedTargetCount": result.get("removedTargetCount"),
                    "controlPlaneOnly": result.get("controlPlaneOnly"),
                    "preservedPaths": result.get("preservedPaths"),
                },
            },
        )
        return {
            "data": {
                **result,
                "serverId": selected_server_id,
                "health": health,
                "runner": self._compose_runner_payload(registry_entry=registry_entry, health=health),
                "lifecycleAction": "uninstall",
                "completedAt": completed_at,
            }
        }

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
        raise_if_runner_manually_stopped(server_id=server_id, record=record)
        if not record.get("bootstrap_version"):
            raise RuntimeServiceError("Remote runner is not prepared")
        ssh = self._ensure_ssh_connected()
        return server_id, ssh, record


def _runner_uninstalled_health(server_id: str, *, completed_at: str) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "state": "uninstalled",
        "startup": {"ok": True, "message": "Remote runner control plane was uninstalled."},
        "live": {"ok": False, "message": "Remote runner service is not installed."},
        "ready": {"ok": False, "message": "Start the runner to reinstall the remote control plane."},
        "reasonCode": "RUNNER_UNINSTALLED",
        "checkedAt": completed_at,
    }
