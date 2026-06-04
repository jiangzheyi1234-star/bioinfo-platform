from __future__ import annotations

from typing import Any, Optional


class RunnerToolOperationsMixin:
    def list_tools(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_tools,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def add_tool(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.add_tool,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                payload=body,
            )
        }

    def create_tool_prepare_job(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.create_tool_prepare_job,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                payload=body,
            )
        }

    def get_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_tool_prepare_job,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                job_id=job_id,
            )
        }

    def cancel_tool_prepare_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.cancel_tool_prepare_job,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                job_id=job_id,
            )
        }

    def update_tool_rule_template(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.update_tool_rule_template,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                tool_id=tool_id,
                payload=body,
            )
        }

    def delete_tool(self, tool_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.delete_tool,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                tool_id=tool_id,
            )
        }

    def mark_tool_production_enabled(self, tool_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.mark_tool_production_enabled,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                tool_id=tool_id,
                payload=body,
            )
        }
