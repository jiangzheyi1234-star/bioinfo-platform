from __future__ import annotations

from typing import Any, Optional

from .errors import RuntimeServiceError


class RunnerWorkflowDesignOperationsMixin:
    def list_workflow_design_drafts(self, server_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            selected_server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=server_id
            )
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_workflow_design_drafts,
                    server_id=selected_server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def create_workflow_design_draft(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.create_workflow_design_draft,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                payload=body,
            )
        }

    def get_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            selected_server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=server_id
            )
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_workflow_design_draft,
                server_id=selected_server_id,
                ssh_service=ssh,
                server_record=record,
                draft_id=draft_id,
            )
        }

    def update_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.update_workflow_design_draft,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                draft_id=draft_id,
                payload=body,
            )
        }

    def fork_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        body.pop("serverId", None)
        return {
            "data": self._call_remote_runner(
                manager.fork_workflow_design_draft,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                draft_id=draft_id,
                payload=body,
            )
        }

    def delete_workflow_design_draft(self, draft_id: str, server_id: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            selected_server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=server_id
            )
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.delete_workflow_design_draft,
                server_id=selected_server_id,
                ssh_service=ssh,
                server_record=record,
                draft_id=draft_id,
            )
        }

    def plan_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        if body:
            raise RuntimeServiceError(f"WORKFLOW_DESIGN_PLAN_UNSUPPORTED_FIELD: {sorted(body)[0]}")
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=preferred_server_id
            )
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.plan_workflow_design_draft,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                draft_id=draft_id,
                payload=body,
            )
        }

    def compile_workflow_design_draft(self, draft_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        preferred_server_id = body.pop("serverId", None)
        if body:
            raise RuntimeServiceError(f"WORKFLOW_DESIGN_COMPILE_UNSUPPORTED_FIELD: {sorted(body)[0]}")
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready(
                preferred_server_id=preferred_server_id
            )
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.compile_workflow_design_draft,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                draft_id=draft_id,
            )
        }
