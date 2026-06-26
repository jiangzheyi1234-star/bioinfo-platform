from __future__ import annotations

from typing import Any, Optional


class RunnerExecutionOperationsMixin:
    def list_runs(self) -> list[dict[str, Any]]:
        return self.execution.list_runs()

    def submit_run(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.submit_run(payload)

    def list_workflow_triggers(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.execution.list_workflow_triggers(server_id)

    def create_workflow_trigger(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.create_workflow_trigger(payload)

    def submit_workflow_trigger_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.submit_workflow_trigger_event(trigger_id, payload, server_id)

    def submit_workflow_trigger_inbox_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
        raw_body: bytes | None = None,
        headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        return self.execution.submit_workflow_trigger_inbox_event(
            trigger_id,
            payload,
            server_id,
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
        return self.execution.replay_workflow_trigger_inbox_event(
            trigger_id,
            inbox_event_id,
            payload,
            server_id,
        )

    def submit_workflow_trigger_readiness_event(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.submit_workflow_trigger_readiness_event(trigger_id, payload, server_id)

    def preview_workflow_trigger_backfill(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.preview_workflow_trigger_backfill(trigger_id, payload, server_id)

    def launch_workflow_trigger_backfill(
        self,
        trigger_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.launch_workflow_trigger_backfill(trigger_id, payload, server_id)

    def list_workflow_trigger_events(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.list_workflow_trigger_events(trigger_id, server_id)

    def get_workflow_trigger_readiness_observation(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.get_workflow_trigger_readiness_observation(trigger_id, server_id)

    def list_workflow_trigger_inbox_events(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.execution.list_workflow_trigger_inbox_events(
            trigger_id,
            server_id=server_id,
            state=state,
            limit=limit,
        )

    def list_workflow_trigger_scheduler_ticks(
        self,
        *,
        server_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.execution.list_workflow_trigger_scheduler_ticks(
            server_id=server_id,
            limit=limit,
        )

    def run_workflow_trigger_scheduler_once(
        self,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.run_workflow_trigger_scheduler_once(payload, server_id)

    def list_workflow_backfill_launches(
        self,
        *,
        server_id: Optional[str] = None,
        trigger_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.execution.list_workflow_backfill_launches(
            server_id=server_id,
            trigger_id=trigger_id,
            limit=limit,
        )

    def get_workflow_backfill_launch(
        self,
        launch_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.get_workflow_backfill_launch(launch_id, server_id)

    def cancel_workflow_backfill_launch(
        self,
        launch_id: str,
        payload: Optional[dict[str, Any]] = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.cancel_workflow_backfill_launch(launch_id, payload, server_id)

    def list_governance_audit_events(
        self,
        *,
        server_id: Optional[str] = None,
        subject_kind: Optional[str] = None,
        subject_id: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.execution.list_governance_audit_events(
            server_id=server_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            action=action,
            limit=limit,
        )

    def get_secret_provider_readiness(self, server_id: Optional[str] = None) -> dict[str, Any]:
        return self.execution.get_secret_provider_readiness(server_id=server_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self.execution.cancel_run(run_id)

    def retry_run(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.retry_run(run_id, payload)

    def retry_run_rules(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.retry_run_rules(run_id, payload)

    def apply_rule_output_invalidation(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.apply_rule_output_invalidation(run_id, payload)

    def prepare_rule_cache_restore_pins(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.prepare_rule_cache_restore_pins(run_id, payload)

    def apply_rule_cache_restore_pins(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.apply_rule_cache_restore_pins(run_id, payload)

    def prepare_rule_cache_restore_staged_files(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.execution.prepare_rule_cache_restore_staged_files(run_id, payload)

    def apply_rule_cache_restore_staged_files(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.execution.apply_rule_cache_restore_staged_files(run_id, payload)

    def prepare_rule_cache_restore_final_outputs(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.execution.prepare_rule_cache_restore_final_outputs(run_id, payload)

    def apply_rule_cache_restore_final_outputs(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.execution.apply_rule_cache_restore_final_outputs(run_id, payload)

    def prepare_rule_cache_restore_adoption(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.execution.prepare_rule_cache_restore_adoption(run_id, payload)

    def apply_rule_cache_restore_adoption(
        self,
        run_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        return self.execution.apply_rule_cache_restore_adoption(run_id, payload)

    def resume_run(self, run_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self.execution.resume_run(run_id, payload)

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_events(run_id)

    def get_run_execution_context(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_execution_context(run_id)

    def get_run_attempts(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_attempts(run_id)

    def get_run_logs(
        self,
        run_id: str,
        stream: str = "stdout",
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.get_run_logs(run_id, stream, cursor)

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_results(run_id)

    def get_run_rules(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_rules(run_id)

    def get_run_failure_locator(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_failure_locator(run_id)

    def list_results(self) -> dict[str, Any]:
        return self.execution.list_results()

    def get_result(self, result_id: str) -> dict[str, Any]:
        return self.execution.get_result(result_id)

    def get_result_preview(
        self,
        result_id: str,
        artifact_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.get_result_preview(result_id, artifact_id)

    def get_result_audit(self, result_id: str) -> dict[str, Any]:
        return self.execution.get_result_audit(result_id)

    def export_result_package(
        self,
        result_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.export_result_package(
            result_id,
            payload=payload,
            server_id=server_id,
        )

    def list_result_package_exports(
        self,
        result_id: str,
        *,
        server_id: Optional[str] = None,
        lifecycle_state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.execution.list_result_package_exports(
            result_id,
            server_id=server_id,
            lifecycle_state=lifecycle_state,
            limit=limit,
        )

    def download_result_package(
        self,
        result_id: str,
        package_export_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.download_result_package(
            result_id,
            package_export_id,
            server_id=server_id,
        )

    def retire_result_package(
        self,
        result_id: str,
        package_export_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.retire_result_package(
            result_id,
            package_export_id,
            payload=payload,
            server_id=server_id,
        )

    def delete_result_package_bytes(
        self,
        result_id: str,
        package_export_id: str,
        *,
        payload: dict[str, Any] | None = None,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.delete_result_package_bytes(
            result_id,
            package_export_id,
            payload=payload,
            server_id=server_id,
        )

    def preview_result_package_byte_gc(
        self,
        payload: dict[str, Any] | None = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.preview_result_package_byte_gc(payload, server_id=server_id)

    def run_result_package_byte_gc(
        self,
        payload: dict[str, Any] | None = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.run_result_package_byte_gc(payload, server_id=server_id)

    def get_artifact_lifecycle_usage(
        self,
        *,
        server_id: Optional[str] = None,
        quota_bytes: Optional[int] = None,
    ) -> dict[str, Any]:
        return self.execution.get_artifact_lifecycle_usage(
            server_id=server_id,
            quota_bytes=quota_bytes,
        )

    def list_artifact_lifecycle_controller_ticks(
        self,
        *,
        server_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self.execution.list_artifact_lifecycle_controller_ticks(
            server_id=server_id,
            limit=limit,
        )

    def run_artifact_lifecycle_controller_once(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.run_artifact_lifecycle_controller_once(payload, server_id=server_id)

    def preview_artifact_gc(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.preview_artifact_gc(payload, server_id=server_id)

    def run_artifact_gc(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.run_artifact_gc(payload, server_id=server_id)

    def list_artifact_cache_entries(
        self,
        *,
        server_id: Optional[str] = None,
        workflow_revision_id: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.execution.list_artifact_cache_entries(
            server_id=server_id,
            workflow_revision_id=workflow_revision_id,
            limit=limit,
        )

    def list_artifact_cache_pins(
        self,
        *,
        server_id: Optional[str] = None,
        cache_entry_id: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.execution.list_artifact_cache_pins(
            server_id=server_id,
            cache_entry_id=cache_entry_id,
            state=state,
            limit=limit,
        )

    def retain_artifact_cache_pin(
        self,
        cache_entry_id: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.retain_artifact_cache_pin(cache_entry_id, payload, server_id=server_id)

    def release_artifact_cache_pin(
        self,
        cache_pin_id: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.release_artifact_cache_pin(cache_pin_id, payload, server_id=server_id)

    def lookup_artifact_cache(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.lookup_artifact_cache(payload, server_id=server_id)
