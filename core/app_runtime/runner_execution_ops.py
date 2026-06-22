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
    ) -> dict[str, Any]:
        return self.execution.submit_workflow_trigger_inbox_event(trigger_id, payload, server_id)

    def list_workflow_trigger_events(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.list_workflow_trigger_events(trigger_id, server_id)

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

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self.execution.cancel_run(run_id)

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_events(run_id)

    def get_run_execution_context(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_execution_context(run_id)

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

    def export_result_package(self, result_id: str) -> dict[str, Any]:
        return self.execution.export_result_package(result_id)

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

    def lookup_artifact_cache(
        self,
        payload: Optional[dict[str, Any]] = None,
        *,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.lookup_artifact_cache(payload, server_id=server_id)
