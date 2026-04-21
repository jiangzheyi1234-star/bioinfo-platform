from __future__ import annotations

import uuid
from typing import Any, Optional

from core.remote_runner.manager import RemoteRunnerManagerError

from .errors import RuntimeServiceError


class RunnerOperationsMixin:
    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_bootstrapped_runner()
            manager = self._service_locator.remote_runner_manager
        return self._call_remote_runner(
            manager.list_runs,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
        )

    def upload_file(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_bootstrapped_runner(
                preferred_server_id=body.get("serverId")
            )
            manager = self._service_locator.remote_runner_manager
        return self._call_remote_runner(
            manager.upload_content,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            filename=str(body.get("filename") or ""),
            content_base64=str(body.get("contentBase64") or ""),
            mime_type=str(body.get("mimeType") or "application/octet-stream"),
        )

    def submit_run(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            request_id = str(body.get("requestId") or f"req_{uuid.uuid4().hex[:8]}").strip()
            run_spec = dict(body.get("runSpec") or {})
            preferred_server_id = body.get("serverId") or run_spec.get("serverId")
            server_id, ssh, record = self._require_bootstrapped_runner(
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
            idempotency_key=f"idem_{request_id}",
            request_id=request_id,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_bootstrapped_runner()
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
            server_id, ssh, record = self._require_bootstrapped_runner()
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
            server_id, ssh, record = self._require_bootstrapped_runner()
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
            server_id, ssh, record = self._require_bootstrapped_runner()
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
            server_id, ssh, record = self._require_bootstrapped_runner()
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
            server_id, ssh, record = self._require_bootstrapped_runner()
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
            server_id, ssh, record = self._require_bootstrapped_runner()
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

    @staticmethod
    def _call_remote_runner(func, /, **kwargs):
        try:
            return func(**kwargs)
        except RuntimeServiceError:
            raise
        except (RemoteRunnerManagerError, RuntimeError) as exc:
            raise RuntimeServiceError(str(exc) or "remote runner operation failed") from exc
