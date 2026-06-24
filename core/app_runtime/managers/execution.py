from __future__ import annotations

import uuid
from typing import Any, Optional

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager


class ExecutionManager(BaseRuntimeManager):
    def list_runs(self) -> list[dict[str, Any]]:
        return self.call_runner("list_runs")

    def submit_run(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.get("serverId") or "").strip()
        if not server_id_hint:
            raise RuntimeServiceError("serverId is required")
        request_id = str(body.get("requestId") or f"req_{uuid.uuid4().hex[:8]}").strip()
        idempotency_key = str(body.get("idempotencyKey") or request_id).strip()
        if not idempotency_key:
            raise RuntimeServiceError("idempotencyKey is required")
        run_spec = dict(body.get("runSpec") or {})
        if body.get("runId") and not run_spec.get("runId"):
            run_spec["runId"] = body["runId"]
        if not str(run_spec.get("pipelineId") or "").strip():
            raise RuntimeServiceError("pipelineId is required")
        manager, server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.submit_run,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            payload={
                "serverId": server_id,
                "requestId": request_id,
                "runSpec": run_spec,
            },
            idempotency_key=idempotency_key,
            request_id=request_id,
        )

    def list_workflow_triggers(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "list_workflow_triggers",
                preferred_server_id=server_id,
            )
        }

    def create_workflow_trigger(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.get("serverId") or "").strip()
        if not server_id_hint:
            raise RuntimeServiceError("serverId is required")
        manager, server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        body["serverId"] = server_id
        return {
            "data": self._service._call_remote_runner(
                manager.create_workflow_trigger,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                payload=body,
            )
        }

    def submit_workflow_trigger_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.submit_workflow_trigger_event,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            trigger_id=trigger_id,
            payload=body,
        )

    def submit_workflow_trigger_inbox_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
        raw_body: bytes | None = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.submit_workflow_trigger_inbox_event,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            trigger_id=trigger_id,
            payload=body,
            raw_body=raw_body,
            headers=headers,
        )

    def replay_workflow_trigger_inbox_event(
        self,
        trigger_id: str,
        inbox_event_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.replay_workflow_trigger_inbox_event,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            trigger_id=trigger_id,
            inbox_event_id=inbox_event_id,
            payload=body,
        )

    def submit_workflow_trigger_readiness_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.submit_workflow_trigger_readiness_event,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            trigger_id=trigger_id,
            payload=body,
        )

    def preview_workflow_trigger_backfill(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.preview_workflow_trigger_backfill,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            trigger_id=trigger_id,
            payload=body,
        )

    def launch_workflow_trigger_backfill(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.launch_workflow_trigger_backfill,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            trigger_id=trigger_id,
            payload=body,
        )

    def list_workflow_trigger_events(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "list_workflow_trigger_events",
                preferred_server_id=server_id,
                trigger_id=trigger_id,
            )
        }

    def list_workflow_trigger_inbox_events(
        self,
        trigger_id: str,
        *,
        server_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "list_workflow_trigger_inbox_events",
                preferred_server_id=server_id,
                trigger_id=trigger_id,
                state=state,
                limit=limit,
            )
        }

    def list_workflow_backfill_launches(
        self,
        *,
        server_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "list_workflow_backfill_launches",
                preferred_server_id=server_id,
                trigger_id=trigger_id,
                limit=limit,
            )
        }

    def get_workflow_backfill_launch(
        self,
        launch_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "get_workflow_backfill_launch",
                preferred_server_id=server_id,
                launch_id=launch_id,
            )
        }

    def cancel_workflow_backfill_launch(
        self,
        launch_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        manager, resolved_server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        return self._service._call_remote_runner(
            manager.cancel_workflow_backfill_launch,
            server_id=resolved_server_id,
            ssh_service=ssh,
            server_record=record,
            launch_id=launch_id,
            payload=body,
        )

    def list_governance_audit_events(
        self,
        *,
        server_id: Optional[str] = None,
        subject_kind: Optional[str] = None,
        subject_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "list_governance_audit_events",
                preferred_server_id=server_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                action=action,
                limit=limit,
            )
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_run", run_id=run_id)}

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("cancel_run", run_id=run_id)}

    def retry_run(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"data": self.call_runner("retry_run", run_id=run_id, payload=dict(payload or {}))}

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_run_events", run_id=run_id)}

    def get_run_execution_context(self, run_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_run_execution_context", run_id=run_id)}

    def get_run_logs(
        self,
        run_id: str,
        stream: str = "stdout",
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "get_run_logs",
                run_id=run_id,
                stream=stream,
                cursor=cursor,
            )
        }

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_run_results", run_id=run_id)}

    def get_run_rules(self, run_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_run_rules", run_id=run_id)}

    def list_results(self) -> dict[str, Any]:
        return {"data": {"items": self.call_runner("list_results")}}

    def get_result(self, result_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_result", result_id=result_id)}

    def get_result_preview(
        self,
        result_id: str,
        artifact_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "get_result_preview",
                result_id=result_id,
                artifact_id=artifact_id,
            )
        }

    def get_result_audit(self, result_id: str) -> dict[str, Any]:
        return {"data": self.call_runner("get_result_audit", result_id=result_id)}

    def export_result_package(
        self,
        result_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "export_result_package",
                preferred_server_id=server_id,
                result_id=result_id,
                payload=dict(payload or {}),
            )
        }

    def list_result_package_exports(
        self,
        result_id: str,
        *,
        server_id: Optional[str] = None,
        lifecycle_state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_runner(
                "list_result_package_exports",
                preferred_server_id=server_id,
                result_id=result_id,
                lifecycle_state=lifecycle_state,
                limit=limit,
            )
        }

    def download_result_package(
        self,
        result_id: str,
        package_export_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.call_runner(
            "download_result_package",
            preferred_server_id=server_id,
            result_id=result_id,
            package_export_id=package_export_id,
        )

    def retire_result_package(
        self,
        result_id: str,
        package_export_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.call_runner(
            "retire_result_package",
            preferred_server_id=server_id_hint,
            result_id=result_id,
            package_export_id=package_export_id,
            payload=body,
        )

    def delete_result_package_bytes(
        self,
        result_id: str,
        package_export_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.call_runner(
            "delete_result_package_bytes",
            preferred_server_id=server_id_hint,
            result_id=result_id,
            package_export_id=package_export_id,
            payload=body,
        )

    def get_artifact_lifecycle_usage(
        self,
        *,
        server_id: Optional[str] = None,
        quota_bytes: Optional[int] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "get_artifact_lifecycle_usage",
                preferred_server_id=server_id,
                quota_bytes=quota_bytes,
            )
        }

    def preview_artifact_gc(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "preview_artifact_gc",
                preferred_server_id=server_id,
                payload=dict(payload or {}),
            )
        }

    def run_artifact_gc(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "run_artifact_gc",
                preferred_server_id=server_id,
                payload=dict(payload or {}),
            )
        }

    def list_artifact_cache_entries(
        self,
        *,
        server_id: Optional[str] = None,
        workflow_revision_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "list_artifact_cache_entries",
                preferred_server_id=server_id,
                workflow_revision_id=workflow_revision_id,
                limit=limit,
            )
        }

    def list_artifact_cache_pins(
        self,
        *,
        server_id: Optional[str] = None,
        cache_entry_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "list_artifact_cache_pins",
                preferred_server_id=server_id,
                cache_entry_id=cache_entry_id,
                state=state,
                limit=limit,
            )
        }

    def retain_artifact_cache_pin(
        self,
        cache_entry_id: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "retain_artifact_cache_pin",
                preferred_server_id=server_id,
                cache_entry_id=cache_entry_id,
                payload=dict(payload or {}),
            )
        }

    def release_artifact_cache_pin(
        self,
        cache_pin_id: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "release_artifact_cache_pin",
                preferred_server_id=server_id,
                cache_pin_id=cache_pin_id,
                payload=dict(payload or {}),
            )
        }

    def lookup_artifact_cache(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_existing_runner(
                "lookup_artifact_cache",
                preferred_server_id=server_id,
                payload=dict(payload or {}),
            )
        }
