from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from config import resolve_runner_token, store_runner_token
from core.remote_runner.bundle import REMOTE_RUNNER_PORT, REMOTE_RUNNER_VERSION, RemoteRunnerBundleBuilder
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient


class RemoteRunnerManagerError(RuntimeError):
    pass


class RemoteRunnerManager:
    def __init__(self, bundle_builder: RemoteRunnerBundleBuilder | None = None):
        self._bundle_builder = bundle_builder or RemoteRunnerBundleBuilder()

    def bootstrap(self, **kwargs) -> dict[str, Any]:
        server_id = str(kwargs["server_id"])
        server = kwargs["server"]
        ssh_service = kwargs["ssh_service"]
        version = REMOTE_RUNNER_VERSION
        bundle = self._bundle_builder.build(version=version)
        home_dir = self._resolve_remote_home(ssh_service)
        mode = self._detect_mode(ssh_service)
        token = secrets.token_urlsafe(24)

        remote_root = f"{home_dir}/.h2ometa/runner"
        remote_release = f"{remote_root}/releases/{version}"
        remote_shared = f"{remote_root}/shared"
        remote_bundle = f"{remote_root}/bundle-{version}.tar.gz"
        remote_config = f"{remote_shared}/config/runner.json"
        remote_log = f"{remote_shared}/logs/runner.log"
        remote_current = f"{remote_root}/current"
        remote_port = REMOTE_RUNNER_PORT

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
            json.dump(
                {
                    "service_name": "h2ometa-remote",
                    "version": version,
                    "mode": mode,
                    "bind_host": "127.0.0.1",
                    "bind_port": remote_port,
                    "token": token,
                    "data_root": f"{remote_shared}",
                    "db_path": f"{remote_shared}/data/runner.db",
                    "uploads_dir": f"{remote_shared}/uploads",
                    "results_dir": f"{remote_shared}/results",
                    "work_dir": f"{remote_shared}/work",
                    "logs_dir": f"{remote_shared}/logs",
                    "release_dir": remote_release,
                },
                handle,
                indent=2,
            )
            local_config_path = Path(handle.name)

        ssh_service.run(
            f"mkdir -p {remote_root}/releases {remote_shared}/config {remote_shared}/data {remote_shared}/logs {remote_shared}/uploads {remote_shared}/results {remote_shared}/work",
            timeout=20,
        )
        ssh_service.upload(str(bundle.archive_path), remote_bundle)
        ssh_service.upload(str(local_config_path), remote_config)
        ssh_service.run(f"mkdir -p {remote_release} && tar -xzf {remote_bundle} -C {remote_release}", timeout=60)
        ssh_service.run(
            f"python3 -m venv {remote_release}/.venv && {remote_release}/.venv/bin/pip install -r {remote_release}/remote_runner/requirements.txt",
            timeout=180,
        )
        ssh_service.run(
            f'H2OMETA_REMOTE_CONFIG="{remote_config}" {remote_release}/.venv/bin/python -c "from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())"',
            timeout=60,
        )
        if mode == "systemd_user":
            ssh_service.run(
                f"mkdir -p ~/.config/systemd/user && cp {remote_release}/h2ometa-remote.service ~/.config/systemd/user/h2ometa-remote.service && ln -sfn {remote_release} {remote_current} && systemctl --user daemon-reload && systemctl --user restart h2ometa-remote.service",
                timeout=60,
            )
        else:
            ssh_service.run(
                f"ln -sfn {remote_release} {remote_current} && bash {remote_current}/start_service.sh {remote_config} {remote_log}",
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
        health = client.get_health()
        token_ref = store_runner_token(server_id=server_id, token=token)
        return {
            "bootstrap_version": version,
            "runner_mode": mode,
            "tunnel_port": tunnel.local_port,
            "token_ref": token_ref,
            "health": health,
            "service_port": remote_port,
            "server_label": server.get("label", ""),
        }

    def get_health(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_health()
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

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
            raise RemoteRunnerManagerError(str(exc)) from exc

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
            raise RemoteRunnerManagerError(str(exc)) from exc

    def list_runs(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/runs")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def get_run(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/runs/{kwargs['run_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def get_run_events(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/events")["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

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
            raise RemoteRunnerManagerError(str(exc)) from exc

    def get_run_results(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/runs/{kwargs['run_id']}/results")["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def list_results(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/results")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def get_result(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/results/{kwargs['result_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

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
            raise RemoteRunnerManagerError(str(exc)) from exc

    def rotate_token(self, **kwargs) -> dict[str, Any]:
        server_id = str(kwargs["server_id"])
        record = kwargs["server_record"]
        ssh_service = kwargs["ssh_service"]
        version = str(record.get("bootstrap_version") or "").strip()
        if not version:
            raise RemoteRunnerManagerError("runner is not bootstrapped")
        token = secrets.token_urlsafe(24)
        home_dir = self._resolve_remote_home(ssh_service)
        remote_config = f"{home_dir}/.h2ometa/runner/shared/config/runner.json"
        old_config_path: Path | None = None
        with tempfile.NamedTemporaryFile("w+b", delete=False, suffix=".json") as handle:
            old_config_path = Path(handle.name)
        try:
            ssh_service.download(remote_config, str(old_config_path))
        except Exception:
            old_config_path = None

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
            json.dump(
                {
                    "service_name": "h2ometa-remote",
                    "version": version,
                    "mode": str(record.get("runner_mode") or "background_process"),
                    "bind_host": "127.0.0.1",
                    "bind_port": int(record.get("service_port") or REMOTE_RUNNER_PORT),
                    "token": token,
                    "data_root": f"{home_dir}/.h2ometa/runner/shared",
                    "db_path": f"{home_dir}/.h2ometa/runner/shared/data/runner.db",
                    "uploads_dir": f"{home_dir}/.h2ometa/runner/shared/uploads",
                    "results_dir": f"{home_dir}/.h2ometa/runner/shared/results",
                    "work_dir": f"{home_dir}/.h2ometa/runner/shared/work",
                    "logs_dir": f"{home_dir}/.h2ometa/runner/shared/logs",
                    "release_dir": f"{home_dir}/.h2ometa/runner/releases/{version}",
                },
                handle,
                indent=2,
            )
            local_config_path = Path(handle.name)
        try:
            ssh_service.upload(str(local_config_path), remote_config)
            if str(record.get("runner_mode")) == "systemd_user":
                ssh_service.run("systemctl --user restart h2ometa-remote.service", timeout=30)
            else:
                ssh_service.run("pkill -f 'remote_runner.run' || true", timeout=10)
                ssh_service.run(
                    f"bash {home_dir}/.h2ometa/runner/current/start_service.sh {remote_config} {home_dir}/.h2ometa/runner/shared/logs/runner.log",
                    timeout=30,
                )
            tunnel = ssh_service.ensure_local_tunnel(
                f"runner-{server_id}",
                remote_host="127.0.0.1",
                remote_port=int(record.get("service_port") or REMOTE_RUNNER_PORT),
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
                    ssh_service.upload(str(old_config_path), remote_config)
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

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any]) -> RemoteRunnerHttpClient:
        token = resolve_runner_token(str(record.get("token_ref", "") or ""))
        if not token:
            raise RemoteRunnerManagerError("runner token not available")
        remote_port = int(record.get("service_port") or REMOTE_RUNNER_PORT)
        tunnel = ssh_service.ensure_local_tunnel(
            f"runner-{server_id}",
            remote_host="127.0.0.1",
            remote_port=remote_port,
        )
        return RemoteRunnerHttpClient(
            base_url=f"http://127.0.0.1:{tunnel.local_port}",
            token=token,
            timeout=5,
        )

    @staticmethod
    def _detect_mode(ssh_service) -> str:
        exit_code, stdout, _stderr = ssh_service.run(
            "if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then echo systemd_user; else echo background_process; fi",
            timeout=10,
        )
        if exit_code == 0 and stdout.strip() == "systemd_user":
            return "systemd_user"
        return "background_process"

    @staticmethod
    def _resolve_remote_home(ssh_service) -> str:
        exit_code, stdout, stderr = ssh_service.run('printf "%s" "$HOME"', timeout=10)
        if exit_code != 0:
            raise RemoteRunnerManagerError(stderr.strip() or stdout.strip() or "failed to resolve remote home")
        home_dir = stdout.strip()
        if not home_dir:
            raise RemoteRunnerManagerError("remote home directory is empty")
        return home_dir
