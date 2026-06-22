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

    def list_workflow_trigger_events(
        self,
        trigger_id: str,
        server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.execution.list_workflow_trigger_events(trigger_id, server_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run(run_id)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self.execution.cancel_run(run_id)

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        return self.execution.get_run_events(run_id)

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
