from __future__ import annotations

import uuid
from typing import Any, Optional

from .errors import RuntimeServiceError


class RunnerExecutionOperationsMixin:
    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return self._call_remote_runner(
            manager.list_runs,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
        )

    def submit_run(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
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
            preferred_server_id = server_id_hint
            server_id, ssh, record = self._require_runner_ready(
                preferred_server_id=preferred_server_id
            )
            manager = self._service_locator.remote_runner_manager
        return self._call_remote_runner(
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

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_run,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                run_id=run_id,
            )
        }

    def get_run_events(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_run_events,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                run_id=run_id,
            )
        }

    def get_run_logs(
        self,
        run_id: str,
        stream: str = "stdout",
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_run_logs,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                run_id=run_id,
                stream=stream,
                cursor=cursor,
            )
        }

    def get_run_results(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_run_results,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                run_id=run_id,
            )
        }

    def list_results(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_results,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def get_result(self, result_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_result,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                result_id=result_id,
            )
        }

    def get_result_preview(
        self,
        result_id: str,
        artifact_id: Optional[str] = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_result_preview,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                result_id=result_id,
                artifact_id=artifact_id,
            )
        }
