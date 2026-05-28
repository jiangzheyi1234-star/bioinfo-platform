from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from config import resolve_runner_token, store_runner_token
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient


def _is_manager_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "RemoteRunnerManagerError"


class RemoteRunnerProxyMixin:
    def get_health(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_health()
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def upload_content(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json(
                "/api/v1/uploads",
                {
                    "filename": kwargs["filename"],
                    "contentBase64": kwargs["content_base64"],
                    "mimeType": kwargs.get("mime_type") or "application/octet-stream",
                },
            )["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def list_pipelines(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/pipelines")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_pipeline(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/pipelines/{kwargs['pipeline_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def list_tools(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/tools")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def add_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json("/api/v1/tools", kwargs["payload"])["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def delete_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.delete_json(f"/api/v1/tools/{kwargs['tool_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def check_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json(f"/api/v1/tools/{kwargs['tool_id']}/check", {})["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def submit_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json(
                "/api/v1/runs",
                kwargs["payload"],
                extra_headers={
                    "Idempotency-Key": kwargs["idempotency_key"],
                    "X-Request-Id": kwargs["request_id"],
                },
            )
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def list_runs(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/runs")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/runs/{kwargs['run_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_run_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/events")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_run_logs(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        stream = kwargs.get("stream") or "stdout"
        cursor = kwargs.get("cursor")
        path = f"/api/v1/runs/{kwargs['run_id']}/logs?stream={stream}"
        if cursor:
            path += f"&cursor={cursor}"
        try:
            return client.get_json(path)["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_run_results(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/results")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def list_results(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/results")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_result(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/results/{kwargs['result_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def get_result_preview(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        path = f"/api/v1/results/{kwargs['result_id']}/preview"
        artifact_id = kwargs.get("artifact_id")
        if artifact_id:
            path += f"?artifact_id={artifact_id}"
        try:
            return client.get_json(path)["data"]
        except RemoteRunnerClientError as exc:
            raise self._manager_error(str(exc)) from exc

    def rotate_token(self, **kwargs) -> dict[str, Any]:
        try:
            server_id = str(kwargs["server_id"])
            record = kwargs["server_record"]
            ssh_service = kwargs["ssh_service"]
            version = str(record.get("bootstrap_version") or "").strip()
            if not version:
                raise self._manager_error("runner is not bootstrapped")
            remote_port = self._require_service_port(record)
            token = secrets.token_urlsafe(24)
            home_dir = self._resolve_remote_home(ssh_service)
            remote_config = f"{home_dir}/.h2ometa/runner/shared/config/runner.json"
            tooling = (record.get("bootstrap_metadata") or {}).get("tooling") or {}
            service_runtime = tooling.get("service_runtime") or {}
            workflow_runtime = tooling.get("workflow_runtime") or {}
            old_config_path: Path | None = None
            with tempfile.NamedTemporaryFile("w+b", delete=False, suffix=".json") as handle:
                old_config_path = Path(handle.name)
            try:
                ssh_service.download(remote_config, str(old_config_path))
            except Exception:
                old_config_path = None

            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
                json.dump(
                    self._build_remote_config_payload(
                        version=version,
                        mode=str(record.get("runner_mode") or "background_process"),
                        remote_port=remote_port,
                        token=token,
                        remote_shared=f"{home_dir}/.h2ometa/runner/shared",
                        remote_release=f"{home_dir}/.h2ometa/runner/releases/{version}",
                        remote_runtime_state=f"{home_dir}/.h2ometa/runner/shared/runtime/runner-state.json",
                        runner_python=str(service_runtime.get("python") or ""),
                        managed_conda_command=str(workflow_runtime.get("command") or ""),
                        managed_conda_root_prefix=str(workflow_runtime.get("root_prefix") or ""),
                        workflow_runtime_provider=str(workflow_runtime.get("provider") or ""),
                        workflow_runtime_source=str(workflow_runtime.get("source") or ""),
                        workflow_runtime_version=str(workflow_runtime.get("version") or ""),
                        snakemake_command=str(workflow_runtime.get("snakemake_command") or ""),
                        snakemake_version=str(workflow_runtime.get("snakemake_version") or ""),
                        workflow_profile_dir=str(
                            record.get("bootstrap_metadata", {}).get("workflow_profile", {}).get("path") or ""
                        ),
                        workflow_profile_name=str(
                            record.get("bootstrap_metadata", {}).get("workflow_profile", {}).get("name")
                            or "profile.v9+.yaml"
                        ),
                    ),
                    handle,
                    indent=2,
                )
                local_config_path = Path(handle.name)
            try:
                self._upload_remote_file_atomic(
                    ssh_service,
                    local_path=local_config_path,
                    remote_path=remote_config,
                    step="write rotated remote runner config",
                    timeout=10,
                )
                if str(record.get("runner_mode")) == "systemd_user":
                    ssh_service.run("systemctl --user restart h2ometa-remote.service", timeout=30)
                else:
                    ssh_service.run("pkill -f '[r]emote_runner.run' || true", timeout=10)
                    ssh_service.run(
                        f"bash {home_dir}/.h2ometa/runner/current/start_service.sh {remote_config} {home_dir}/.h2ometa/runner/shared/logs/runner.log",
                        timeout=30,
                    )
                tunnel = ssh_service.ensure_local_tunnel(
                    f"runner-{server_id}",
                    remote_host="127.0.0.1",
                    remote_port=remote_port,
                )
                client = RemoteRunnerHttpClient(
                    base_url=f"http://127.0.0.1:{tunnel.local_port}",
                    token=token,
                    timeout=5,
                )
                client.get_health()
            except Exception:
                if old_config_path and old_config_path.exists():
                    try:
                        self._upload_remote_file_atomic(
                            ssh_service,
                            local_path=old_config_path,
                            remote_path=remote_config,
                            step="restore previous remote runner config",
                            timeout=10,
                        )
                        if str(record.get("runner_mode")) == "systemd_user":
                            ssh_service.run("systemctl --user restart h2ometa-remote.service", timeout=30)
                        else:
                            ssh_service.run(
                                f"bash {home_dir}/.h2ometa/runner/current/start_service.sh {remote_config} {home_dir}/.h2ometa/runner/shared/logs/runner.log",
                                timeout=30,
                            )
                    except Exception:
                        pass
                raise
            token_ref = store_runner_token(server_id=server_id, token=token)
            return {"token_ref": token_ref}
        except Exception as exc:
            if _is_manager_error(exc):
                raise
            raise self._manager_error(str(exc) or "runner token rotation failed") from exc

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any], timeout: int = 5) -> RemoteRunnerHttpClient:
        try:
            token = resolve_runner_token(str(record.get("token_ref", "") or ""))
            if not token:
                raise self._manager_error("runner token not available")
            remote_port = self._require_service_port(record)
            tunnel = ssh_service.ensure_local_tunnel(
                f"runner-{server_id}",
                remote_host="127.0.0.1",
                remote_port=remote_port,
            )
            return RemoteRunnerHttpClient(
                base_url=f"http://127.0.0.1:{tunnel.local_port}",
                token=token,
                timeout=timeout,
            )
        except Exception as exc:
            if _is_manager_error(exc):
                raise
            raise self._manager_error(str(exc) or "runner tunnel setup failed") from exc

    @staticmethod
    def _manager_error(message: str) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message)
