from __future__ import annotations

import shlex
import time
import uuid
from typing import Any, Optional

from core.remote_runner.manager import RemoteRunnerManagerError

from .errors import RuntimeServiceError


_STOP_REMOTE_RUNNER_COMMAND = r"""
set -u
RUNNER_MODE="${H2OMETA_RUNNER_MODE:-}"
STATE_PATH="$HOME/.h2ometa/runner/shared/runtime/runner-state.json"
STOP_SCRIPT="$HOME/.h2ometa/runner/current/stop_service.sh"
FAILED=0
SYSTEMD_STOPPED=0
STOP_SCRIPT_RAN=0
PROCESS_CHECKED=0

if [ "$RUNNER_MODE" = "background_process" ]; then
  printf 'systemd_user=skipped\n'
elif command -v systemctl >/dev/null 2>&1; then
  if systemctl --user stop h2ometa-remote.service >/tmp/h2ometa-stop-systemd.out 2>&1; then
    SYSTEMD_STOPPED=1
    printf 'systemd_user=stopped\n'
  else
    if [ "$RUNNER_MODE" = "systemd_user" ]; then
      FAILED=1
      printf 'systemd_user=failed: '
    else
      printf 'systemd_user=not-stopped: '
    fi
    cat /tmp/h2ometa-stop-systemd.out
    printf '\n'
  fi
else
  if [ "$RUNNER_MODE" = "systemd_user" ]; then
    FAILED=1
  fi
  printf 'systemd_user=unavailable\n'
fi

if [ -f "$STOP_SCRIPT" ]; then
  if bash "$STOP_SCRIPT" >/tmp/h2ometa-stop-script.out 2>&1; then
    STOP_SCRIPT_RAN=1
    printf 'stop_script=stopped\n'
  else
    FAILED=1
    printf 'stop_script=failed: '
    cat /tmp/h2ometa-stop-script.out
    printf '\n'
  fi
else
  printf 'stop_script=missing\n'
fi

if command -v pkill >/dev/null 2>&1; then
  PROCESS_CHECKED=1
  pkill -f '[r]emote_runner.run' >/tmp/h2ometa-stop-pkill.out 2>&1
  PKILL_CODE=$?
  if [ "$PKILL_CODE" -eq 0 ]; then
    printf 'process=stopped\n'
  elif [ "$PKILL_CODE" -eq 1 ]; then
    printf 'process=not-running\n'
  else
    FAILED=1
    printf 'process=failed: '
    cat /tmp/h2ometa-stop-pkill.out
    printf '\n'
  fi
else
  printf 'process=pkill-unavailable\n'
fi

if [ "$SYSTEMD_STOPPED" -eq 0 ] && [ "$STOP_SCRIPT_RAN" -eq 0 ] && [ "$PROCESS_CHECKED" -eq 0 ]; then
  FAILED=1
  printf 'stop_mechanism=unavailable\n'
fi

rm -f "$STATE_PATH"
exit "$FAILED"
"""


class RunnerOperationsMixin:
    def stop_remote_runner_service(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh_status = self._get_ssh_status_unlocked()
            server = self._build_primary_server_identity(ssh_status=ssh_status)
            server_id = str(server["serverId"]) if server is not None else ""
            record = self._get_server_registry_entry(server_id) if server_id else {}
            runner_mode = str(record.get("runner_mode") or "")
            ssh = self._ensure_ssh_connected()

        try:
            command = f"H2OMETA_RUNNER_MODE={shlex.quote(runner_mode)}\n{_STOP_REMOTE_RUNNER_COMMAND}"
            exit_code, stdout, stderr = ssh.run(command, timeout=30)
        except Exception as exc:
            raise RuntimeServiceError(str(exc) or "failed to stop remote runner service") from exc

        output = (stdout or stderr or "").strip()
        ok = exit_code == 0
        health = {
            "serverId": server_id,
            "state": "stopped" if ok else "failed",
            "startup": {"ok": ok, "message": "远程服务停止命令已执行。" if ok else "远程服务停止失败。"},
            "live": {"ok": False, "message": "远程服务已停止。" if ok else "远程服务停止失败。"},
            "ready": {"ok": False, "message": "远程服务已手动停止。" if ok else output or "远程服务停止失败。"},
            "reasonCode": "RUNNER_STOPPED" if ok else "RUNNER_STOP_FAILED",
            "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        with self._lock:
            if server_id:
                self._save_server_registry_entry(server_id, {"last_health_snapshot": health})
            status = self._get_ssh_status_unlocked()

        if not ok:
            raise RuntimeServiceError(output or "failed to stop remote runner service")
        return {"data": {"ok": True, "output": output, "serverId": server_id}, "item": status}

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

    def upload_file(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            body = dict(payload or {})
            server_id, ssh, record = self._require_runner_ready(
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

    def list_pipelines(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_pipelines,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def get_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.get_pipeline,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                pipeline_id=pipeline_id,
            )
        }

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

    def check_tool(self, tool_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.check_tool,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                tool_id=tool_id,
            )
        }

    def list_databases(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_databases,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def list_database_templates(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": {
                "items": self._call_remote_runner(
                    manager.list_database_templates,
                    server_id=server_id,
                    ssh_service=ssh,
                    server_record=record,
                )
            }
        }

    def add_database(self, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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
                manager.add_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                payload=body,
            )
        }

    def delete_database(self, database_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.delete_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                database_id=database_id,
            )
        }

    def update_database(self, database_id: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.update_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                database_id=database_id,
                payload=dict(payload or {}),
            )
        }

    def check_database(self, database_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            server_id, ssh, record = self._require_existing_runner_ready()
            manager = self._service_locator.remote_runner_manager
        return {
            "data": self._call_remote_runner(
                manager.check_database,
                server_id=server_id,
                ssh_service=ssh,
                server_record=record,
                database_id=database_id,
            )
        }

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
            if body.get("pipelineId") and not run_spec.get("pipelineId"):
                run_spec["pipelineId"] = body["pipelineId"]
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

    def list_remote_files(
        self,
        path: str = "",
        *,
        directories_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_initialized()
            ssh = self._ensure_ssh_connected()
        try:
            data = ssh.list_directory(path, directories_only=directories_only, limit=limit, offset=offset)
        except Exception as exc:
            raise RuntimeServiceError(str(exc) or "failed to list remote files") from exc
        return {"data": data}

    @staticmethod
    def _call_remote_runner(func, /, **kwargs):
        try:
            return func(**kwargs)
        except RuntimeServiceError:
            raise
        except (RemoteRunnerManagerError, RuntimeError) as exc:
            raise RuntimeServiceError(str(exc) or "remote runner operation failed") from exc

    def _require_existing_runner_ready(
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
        if not record.get("bootstrap_version"):
            raise RuntimeServiceError("Remote runner is not prepared")
        snapshot = record.get("last_health_snapshot")
        if isinstance(snapshot, dict) and not bool((snapshot.get("ready") or {}).get("ok")):
            message = str((snapshot.get("ready") or {}).get("message") or "Remote runner is not ready.")
            raise RuntimeServiceError(message)
        ssh = self._ensure_ssh_connected()
        return server_id, ssh, record
