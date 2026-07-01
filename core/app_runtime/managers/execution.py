from __future__ import annotations

import uuid
from typing import Any, Optional

from core.app_runtime.errors import RuntimeServiceError
from core.app_runtime.managers.base import BaseRuntimeManager
from core.contracts.remote_endpoints import (
    ARTIFACT_CACHE_ENTRIES_READ,
    ARTIFACT_CACHE_LOOKUP,
    ARTIFACT_CACHE_PINS_READ,
    ARTIFACT_CACHE_PIN_RELEASE,
    ARTIFACT_CACHE_PIN_RETAIN,
    ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
    ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
    ARTIFACT_LIFECYCLE_GC_PREVIEW,
    ARTIFACT_LIFECYCLE_GC_RUN,
    ARTIFACT_LIFECYCLE_USAGE_READ,
    ARTIFACT_STORAGE_READINESS_READ,
    ARTIFACT_STORAGE_READINESS_SMOKE_RUN,
    GOVERNANCE_AUDIT_EVENTS_READ,
    RUN_CREATE,
    RESULT_AUDIT_READ,
    RESULT_LIST,
    RESULT_PREVIEW_READ,
    RESULT_READ,
    RUN_ATTEMPTS_READ,
    RUN_CANCEL,
    RUN_EVENTS_READ,
    RUN_EXECUTION_CONTEXT_READ,
    RUN_FAILURE_LOCATOR_READ,
    RUN_LIST,
    RUN_LOGS_READ,
    RUN_READ,
    RUN_RESUME,
    RUN_RESULTS_READ,
    RUN_RETRY,
    RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY,
    RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY,
    RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE,
    RUN_RULE_CACHE_RESTORE_PINS_APPLY,
    RUN_RULE_CACHE_RESTORE_PINS_PREPARE,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY,
    RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE,
    RUN_RULE_OUTPUT_INVALIDATION_APPLY,
    RUN_RULE_RETRY,
    RUN_RULES_READ,
    SECRET_PROVIDER_READINESS_READ,
    WORKFLOW_BACKFILL_LAUNCH_LIST,
    WORKFLOW_BACKFILL_LAUNCH_READ,
    WORKFLOW_BACKFILL_LAUNCH_CANCEL,
    WORKFLOW_TRIGGER_BACKFILL_LAUNCH,
    WORKFLOW_TRIGGER_BACKFILL_PREVIEW,
    WORKFLOW_TRIGGER_CREATE,
    WORKFLOW_TRIGGER_EVENT_SUBMIT,
    WORKFLOW_REVISION_READ,
    WORKFLOW_TRIGGER_EVENTS_READ,
    WORKFLOW_TRIGGER_INBOX_REPLAY,
    WORKFLOW_TRIGGER_INBOX_READ,
    WORKFLOW_TRIGGER_INBOX_SUBMIT,
    WORKFLOW_TRIGGER_LIST,
    WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
    WORKFLOW_TRIGGER_READINESS_SUBMIT,
    WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE,
    WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE,
    WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
)
from core.contracts.result_package_remote_endpoints import (
    RESULT_PACKAGE_BYTE_GC_PREVIEW,
    RESULT_PACKAGE_BYTE_GC_RUN,
    RESULT_PACKAGE_EXPORT,
    RESULT_PACKAGE_EXPORT_LIST,
    RESULT_PACKAGE_RETIRE,
)


class ExecutionManager(BaseRuntimeManager):
    def list_runs(self) -> list[dict[str, Any]]:
        return self.call_remote_endpoint(RUN_LIST, path_values={}, timeout=20)

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
            manager.call_remote_endpoint,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            endpoint_id=RUN_CREATE,
            path_values={},
            query_values={},
            payload={
                "serverId": server_id,
                "requestId": request_id,
                "runSpec": run_spec,
            },
            extra_headers={
                "Idempotency-Key": idempotency_key,
                "X-Request-Id": request_id,
            },
        )

    def list_workflow_triggers(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_LIST,
            preferred_server_id=server_id,
            timeout=20,
        )

    def create_workflow_trigger(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.get("serverId") or "").strip()
        if not server_id_hint:
            raise RuntimeServiceError("serverId is required")
        manager, server_id, ssh, record = self._runner_context(preferred_server_id=server_id_hint)
        body["serverId"] = server_id
        data = self._service._call_remote_runner(
            manager.call_remote_endpoint,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            endpoint_id=WORKFLOW_TRIGGER_CREATE,
            path_values={},
            query_values={},
            payload=body,
        )
        return {
            "data": data
        }

    def submit_workflow_trigger_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.call_remote_endpoint(
            WORKFLOW_TRIGGER_EVENT_SUBMIT,
            path_values={"trigger_id": trigger_id},
            payload=body,
            preferred_server_id=server_id_hint,
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
        endpoint_kwargs: dict[str, Any] = {
            "path_values": {"trigger_id": trigger_id},
            "preferred_server_id": server_id_hint,
        }
        if raw_body is not None:
            endpoint_kwargs["raw_body"] = bytes(raw_body)
            endpoint_kwargs["extra_headers"] = dict(headers or {})
        else:
            endpoint_kwargs["payload"] = body
        return self.call_remote_endpoint(
            WORKFLOW_TRIGGER_INBOX_SUBMIT,
            **endpoint_kwargs,
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
        return self.call_remote_endpoint(
            WORKFLOW_TRIGGER_INBOX_REPLAY,
            path_values={"trigger_id": trigger_id, "inbox_event_id": inbox_event_id},
            payload=body,
            preferred_server_id=server_id_hint,
        )

    def submit_workflow_trigger_readiness_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.call_remote_endpoint(
            WORKFLOW_TRIGGER_READINESS_SUBMIT,
            path_values={"trigger_id": trigger_id},
            payload=body,
            preferred_server_id=server_id_hint,
        )

    def preview_workflow_trigger_backfill(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_BACKFILL_PREVIEW,
            path_values={"trigger_id": trigger_id},
            payload=body,
            preferred_server_id=server_id_hint,
        )

    def launch_workflow_trigger_backfill(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_BACKFILL_LAUNCH,
            path_values={"trigger_id": trigger_id},
            payload=body,
            preferred_server_id=server_id_hint,
        )

    def list_workflow_trigger_events(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_EVENTS_READ,
            path_values={"trigger_id": trigger_id},
            preferred_server_id=server_id,
            timeout=20,
        )

    def get_workflow_trigger_readiness_observation(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_READINESS_OBSERVATION_READ,
            path_values={"trigger_id": trigger_id},
            preferred_server_id=server_id,
            timeout=20,
        )

    def list_workflow_trigger_inbox_events(
        self,
        trigger_id: str,
        *,
        server_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_INBOX_READ,
            path_values={"trigger_id": trigger_id},
            query_values={"state": state, "limit": limit},
            preferred_server_id=server_id,
            timeout=20,
        )

    def list_workflow_trigger_scheduler_ticks(
        self,
        *,
        server_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_SCHEDULER_TICKS_READ,
            query_values={"limit": limit},
            preferred_server_id=server_id,
            timeout=20,
        )

    def run_workflow_trigger_scheduler_once(
        self,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_SCHEDULER_RUN_ONCE,
            payload=body,
            preferred_server_id=server_id_hint,
            timeout=20,
        )

    def run_workflow_trigger_readiness_watcher_once(
        self,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            WORKFLOW_TRIGGER_READINESS_WATCHER_RUN_ONCE,
            payload=body,
            preferred_server_id=server_id_hint,
            timeout=20,
        )

    def list_workflow_backfill_launches(
        self,
        *,
        server_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_BACKFILL_LAUNCH_LIST,
            query_values={"triggerId": trigger_id, "limit": limit},
            preferred_server_id=server_id,
            timeout=20,
        )

    def get_workflow_backfill_launch(
        self,
        launch_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_BACKFILL_LAUNCH_READ,
            path_values={"launch_id": launch_id},
            preferred_server_id=server_id,
            timeout=20,
        )

    def cancel_workflow_backfill_launch(
        self,
        launch_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            WORKFLOW_BACKFILL_LAUNCH_CANCEL,
            path_values={"launch_id": launch_id},
            payload=body,
            preferred_server_id=server_id_hint,
            timeout=20,
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
        return self.read_remote_endpoint(
            GOVERNANCE_AUDIT_EVENTS_READ,
            query_values={
                "subjectKind": subject_kind,
                "subjectId": subject_id,
                "action": action,
                "limit": limit,
            },
            preferred_server_id=server_id,
            require_existing_runner=True,
            timeout=20,
        )

    def get_secret_provider_readiness(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.read_remote_endpoint(
            SECRET_PROVIDER_READINESS_READ,
            preferred_server_id=server_id,
            require_existing_runner=True,
            timeout=20,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_READ, run_id)

    def get_workflow_revision(
        self,
        workflow_revision_id: str,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            WORKFLOW_REVISION_READ,
            path_values={"workflow_revision_id": workflow_revision_id},
            preferred_server_id=server_id,
        )

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self.read_remote_endpoint(RUN_CANCEL, path_values={"run_id": run_id})

    def retry_run(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.read_remote_endpoint(RUN_RETRY, path_values={"run_id": run_id}, payload=dict(payload or {}))

    def retry_run_rules(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_RETRY, run_id, payload)

    def apply_rule_output_invalidation(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_OUTPUT_INVALIDATION_APPLY, run_id, payload)

    def prepare_rule_cache_restore_pins(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_PINS_PREPARE, run_id, payload)

    def apply_rule_cache_restore_pins(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_PINS_APPLY, run_id, payload)

    def prepare_rule_cache_restore_staged_files(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_STAGED_FILES_PREPARE, run_id, payload)

    def apply_rule_cache_restore_staged_files(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_STAGED_FILES_APPLY, run_id, payload)

    def prepare_rule_cache_restore_final_outputs(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_PREPARE, run_id, payload)

    def apply_rule_cache_restore_final_outputs(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_FINAL_OUTPUTS_APPLY, run_id, payload)

    def prepare_rule_cache_restore_adoption(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_ADOPTION_PREPARE, run_id, payload)

    def apply_rule_cache_restore_adoption(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self._run_command_endpoint(RUN_RULE_CACHE_RESTORE_ADOPTION_APPLY, run_id, payload)

    def resume_run(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.read_remote_endpoint(RUN_RESUME, path_values={"run_id": run_id}, payload=dict(payload or {}))

    def _run_command_endpoint(
        self,
        endpoint_id: str,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(endpoint_id, path_values={"run_id": run_id}, payload=dict(payload or {}))

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_EVENTS_READ, run_id)

    def get_run_execution_context(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_EXECUTION_CONTEXT_READ, run_id)

    def get_run_attempts(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_ATTEMPTS_READ, run_id)

    def get_run_logs(
        self,
        run_id: str,
        stream: str = "stdout",
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._get_run_read_model(RUN_LOGS_READ, run_id, query_values={"stream": stream, "cursor": cursor})

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_RESULTS_READ, run_id)

    def get_run_rules(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_RULES_READ, run_id)

    def get_run_failure_locator(self, run_id: str) -> dict[str, Any]:
        return self._get_run_read_model(RUN_FAILURE_LOCATOR_READ, run_id)

    def _get_run_read_model(
        self,
        endpoint_id: str,
        run_id: str,
        *,
        query_values: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                endpoint_id,
                path_values={"run_id": run_id},
                query_values=query_values,
            )
        }

    def list_results(self) -> dict[str, Any]:
        return {"data": {"items": self.call_remote_endpoint(RESULT_LIST, path_values={})}}

    def get_result(self, result_id: str) -> dict[str, Any]:
        return {"data": self.call_remote_endpoint(RESULT_READ, path_values={"result_id": result_id})}

    def get_result_preview(
        self,
        result_id: str,
        artifact_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                RESULT_PREVIEW_READ,
                path_values={"result_id": result_id},
                query_values={"artifact_id": artifact_id},
            )
        }

    def get_result_audit(self, result_id: str) -> dict[str, Any]:
        return {"data": self.call_remote_endpoint(RESULT_AUDIT_READ, path_values={"result_id": result_id})}

    def export_result_package(
        self,
        result_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            RESULT_PACKAGE_EXPORT,
            path_values={"result_id": result_id},
            preferred_server_id=server_id,
            require_existing_runner=True,
            payload=dict(payload or {}),
        )

    def list_result_package_exports(
        self,
        result_id: str,
        *,
        server_id: Optional[str] = None,
        lifecycle_state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                RESULT_PACKAGE_EXPORT_LIST,
                path_values={"result_id": result_id},
                query_values={"lifecycleState": lifecycle_state, "limit": limit},
                preferred_server_id=server_id,
                require_existing_runner=True,
            )
        }

    def download_result_package(
        self,
        result_id: str,
        package_export_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.call_existing_runner(
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
        return self.read_remote_endpoint(
            RESULT_PACKAGE_RETIRE,
            path_values={"result_id": result_id, "package_export_id": package_export_id},
            preferred_server_id=server_id_hint,
            require_existing_runner=True,
            payload=body,
        )

    def preview_result_package_byte_gc(
        self,
        payload: dict[str, Any] | None = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            RESULT_PACKAGE_BYTE_GC_PREVIEW,
            preferred_server_id=server_id_hint,
            require_existing_runner=True,
            payload=body,
        )

    def run_result_package_byte_gc(
        self,
        payload: dict[str, Any] | None = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body = dict(payload or {})
        server_id_hint = str(body.pop("serverId", None) or server_id or "").strip() or None
        return self.read_remote_endpoint(
            RESULT_PACKAGE_BYTE_GC_RUN,
            preferred_server_id=server_id_hint,
            require_existing_runner=True,
            payload=body,
        )

    def get_artifact_lifecycle_usage(
        self,
        *,
        server_id: Optional[str] = None,
        quota_bytes: Optional[int] = None,
    ) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            ARTIFACT_LIFECYCLE_USAGE_READ,
            preferred_server_id=server_id,
            query_values={"quotaBytes": quota_bytes},
        )

    def get_artifact_storage_readiness(
        self,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            ARTIFACT_STORAGE_READINESS_READ,
            preferred_server_id=server_id,
        )

    def run_artifact_storage_readiness_smoke(
        self,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_STORAGE_READINESS_SMOKE_RUN,
            preferred_server_id=server_id,
            require_existing_runner=True,
        )

    def list_artifact_lifecycle_controller_ticks(
        self,
        *,
        server_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            ARTIFACT_LIFECYCLE_CONTROLLER_TICKS_READ,
            preferred_server_id=server_id,
            query_values={"limit": limit},
        )

    def run_artifact_lifecycle_controller_once(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_LIFECYCLE_CONTROLLER_RUN_ONCE,
            preferred_server_id=server_id,
            require_existing_runner=True,
            timeout=20,
            payload=dict(payload or {}),
        )

    def preview_artifact_gc(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_LIFECYCLE_GC_PREVIEW,
            preferred_server_id=server_id,
            require_existing_runner=True,
            payload=dict(payload or {}),
        )

    def run_artifact_gc(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_LIFECYCLE_GC_RUN,
            preferred_server_id=server_id,
            require_existing_runner=True,
            payload=dict(payload or {}),
        )

    def list_artifact_cache_entries(
        self,
        *,
        server_id: Optional[str] = None,
        workflow_revision_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            ARTIFACT_CACHE_ENTRIES_READ,
            preferred_server_id=server_id,
            query_values={"workflowRevisionId": workflow_revision_id, "limit": limit},
        )

    def list_artifact_cache_pins(
        self,
        *,
        server_id: Optional[str] = None,
        cache_entry_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.read_existing_remote_endpoint(
            ARTIFACT_CACHE_PINS_READ,
            preferred_server_id=server_id,
            query_values={"cacheEntryId": cache_entry_id, "state": state, "limit": limit},
        )

    def retain_artifact_cache_pin(
        self,
        cache_entry_id: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_CACHE_PIN_RETAIN,
            path_values={"cache_entry_id": cache_entry_id},
            preferred_server_id=server_id,
            require_existing_runner=True,
            payload=dict(payload or {}),
        )

    def release_artifact_cache_pin(
        self,
        cache_pin_id: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_CACHE_PIN_RELEASE,
            path_values={"cache_pin_id": cache_pin_id},
            preferred_server_id=server_id,
            require_existing_runner=True,
            payload=dict(payload or {}),
        )

    def lookup_artifact_cache(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            ARTIFACT_CACHE_LOOKUP,
            preferred_server_id=server_id,
            require_existing_runner=True,
            payload=dict(payload or {}),
        )
