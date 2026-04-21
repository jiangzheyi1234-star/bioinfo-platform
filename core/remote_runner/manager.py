from __future__ import annotations

import json
import secrets
import shlex
import tempfile
import time
from pathlib import Path
from typing import Any

from config import resolve_runner_token, store_runner_token
from core.remote_runner.bundle import (
    REMOTE_RUNNER_PORT,
    REMOTE_RUNNER_VERSION,
    LocalRunnerRuntimePackager,
    RemoteRunnerBundleBuilder,
)
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient


class RemoteRunnerManagerError(RuntimeError):
    pass


class RemoteRunnerManager:
    def __init__(
        self,
        bundle_builder: RemoteRunnerBundleBuilder | None = None,
        runtime_packager: LocalRunnerRuntimePackager | None = None,
    ):
        self._bundle_builder = bundle_builder or RemoteRunnerBundleBuilder()
        self._runtime_packager = runtime_packager or LocalRunnerRuntimePackager()

    def bootstrap(self, **kwargs) -> dict[str, Any]:
        try:
            server_id = str(kwargs["server_id"])
            server = kwargs["server"]
            ssh_service = kwargs["ssh_service"]
            version = REMOTE_RUNNER_VERSION
            remote_platform = self._detect_remote_platform(ssh_service)
            bundle = self._bundle_builder.build(version=version)
            runtime_artifact = self._runtime_packager.build(target_platform=remote_platform)
            home_dir = self._resolve_remote_home(ssh_service)
            mode = self._detect_mode(ssh_service)
            token = secrets.token_urlsafe(24)

            remote_root = f"{home_dir}/.h2ometa/runner"
            remote_release = f"{remote_root}/releases/{version}"
            remote_shared = f"{remote_root}/shared"
            remote_bundle = f"{remote_root}/bundle-{version}.tar.gz"
            remote_runtime_archive = f"{remote_root}/runner-runtime-{runtime_artifact.fingerprint}.tar.gz"
            remote_config = f"{remote_shared}/config/runner.json"
            remote_log = f"{remote_shared}/logs/runner.log"
            remote_current = f"{remote_root}/current"
            remote_port = REMOTE_RUNNER_PORT
            remote_tools_root = f"{remote_shared}/tools"
            remote_tools_bin = f"{remote_tools_root}/bin"
            remote_managed_root_prefix = f"{remote_tools_root}/micromamba-root"
            remote_managed_micromamba = f"{remote_tools_bin}/micromamba"
            remote_managed_conda = f"{remote_tools_bin}/conda"
            remote_runner_environment = f"{remote_release}/runner-env"
            remote_runner_python = f"{remote_release}/{runtime_artifact.python_relative_path}"
            bootstrap_metadata: dict[str, Any] = {
                "preflight": {
                    "launcher": {
                        "mode": mode,
                    },
                    "platform": remote_platform,
                },
                "tooling": {},
            }

            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
                json.dump(
                    self._build_remote_config_payload(
                        version=version,
                        mode=mode,
                        remote_port=remote_port,
                        token=token,
                        remote_shared=remote_shared,
                        remote_release=remote_release,
                        runner_python=remote_runner_python,
                        managed_conda_command=remote_managed_conda,
                        managed_conda_root_prefix=remote_managed_root_prefix,
                    ),
                    handle,
                    indent=2,
                )
                local_config_path = Path(handle.name)

            self._run_checked(
                ssh_service,
                f"mkdir -p {remote_root}/releases {remote_shared}/config {remote_shared}/data {remote_shared}/logs {remote_shared}/uploads {remote_shared}/results {remote_shared}/work {remote_tools_bin}",
                step="prepare remote runner directories",
                timeout=20,
            )
            ssh_service.upload(str(bundle.archive_path), remote_bundle)
            ssh_service.upload(str(runtime_artifact.archive_path), remote_runtime_archive)
            ssh_service.upload(str(local_config_path), remote_config)
            self._run_checked(
                ssh_service,
                f"mkdir -p {remote_release} && tar -xzf {remote_bundle} -C {remote_release} && tar -xzf {remote_runtime_archive} -C {remote_release} && chmod 0755 {remote_release}/*.sh",
                step="extract remote runner bundle",
                timeout=60,
            )
            bootstrap_metadata["tooling"] = self._ensure_workflow_runtime(
                ssh_service,
                remote_tools_root=remote_tools_root,
                remote_tools_bin=remote_tools_bin,
                remote_managed_root_prefix=remote_managed_root_prefix,
                remote_managed_micromamba=remote_managed_micromamba,
                remote_managed_conda=remote_managed_conda,
            )
            bootstrap_metadata["tooling"]["runner_runtime"] = {
                "source": "bundled",
                "artifact": runtime_artifact.fingerprint,
                "environment": remote_runner_environment,
                "python": remote_runner_python,
            }
            self._run_checked(
                ssh_service,
                f'cd {remote_release} && H2OMETA_REMOTE_CONFIG="{remote_config}" {remote_runner_python} -c "from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())"',
                step="initialize remote runner layout",
                timeout=60,
            )
            if mode == "systemd_user":
                self._run_checked(
                    ssh_service,
                    f"mkdir -p ~/.config/systemd/user && cp {remote_release}/h2ometa-remote.service ~/.config/systemd/user/h2ometa-remote.service && ln -sfn {remote_release} {remote_current} && systemctl --user daemon-reload && systemctl --user restart h2ometa-remote.service",
                    step="start remote runner service",
                    timeout=60,
                )
            else:
                self._run_checked(
                    ssh_service,
                    f"ln -sfn {remote_release} {remote_current} && bash {remote_current}/start_service.sh {remote_config} {remote_log}",
                    step="start remote runner service",
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
            health = self._wait_for_runner_health(client)
            token_ref = store_runner_token(server_id=server_id, token=token)
            return {
                "bootstrap_version": version,
                "runner_mode": mode,
                "tunnel_port": tunnel.local_port,
                "token_ref": token_ref,
                "health": health,
                "service_port": remote_port,
                "server_label": server.get("label", ""),
                "bootstrap_metadata": bootstrap_metadata,
            }
        except RemoteRunnerManagerError:
            raise
        except Exception as exc:
            raise RemoteRunnerManagerError(str(exc) or "remote runner bootstrap failed") from exc

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
        try:
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
                    self._build_remote_config_payload(
                        version=version,
                        mode=str(record.get("runner_mode") or "background_process"),
                        remote_port=int(record.get("service_port") or REMOTE_RUNNER_PORT),
                        token=token,
                        remote_shared=f"{home_dir}/.h2ometa/runner/shared",
                        remote_release=f"{home_dir}/.h2ometa/runner/releases/{version}",
                        runner_python=str(
                            (((record.get("bootstrap_metadata") or {}).get("tooling") or {}).get("runner_runtime") or {}).get("python")
                            or ""
                        ),
                        managed_conda_command=str(
                            (((record.get("bootstrap_metadata") or {}).get("tooling") or {}).get("workflow_runtime") or {}).get("command")
                            or ""
                        ),
                        managed_conda_root_prefix=str(
                            (((record.get("bootstrap_metadata") or {}).get("tooling") or {}).get("workflow_runtime") or {}).get("root_prefix")
                            or ""
                        ),
                    ),
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
        except RemoteRunnerManagerError:
            raise
        except Exception as exc:
            raise RemoteRunnerManagerError(str(exc) or "runner token rotation failed") from exc

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any]) -> RemoteRunnerHttpClient:
        try:
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
        except RemoteRunnerManagerError:
            raise
        except Exception as exc:
            raise RemoteRunnerManagerError(str(exc) or "runner tunnel setup failed") from exc

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
    def _detect_remote_platform(ssh_service) -> str:
        exit_code, stdout, stderr = ssh_service.run('printf "%s:%s" "$(uname -s)" "$(uname -m)"', timeout=10)
        if exit_code != 0:
            raise RemoteRunnerManagerError(stderr.strip() or stdout.strip() or "failed to detect remote platform")
        mapping = {
            "Linux:x86_64": "linux-64",
            "Linux:amd64": "linux-64",
            "Linux:aarch64": "linux-aarch64",
            "Linux:arm64": "linux-aarch64",
        }
        signature = stdout.strip()
        if signature not in mapping:
            raise RemoteRunnerManagerError(f"unsupported remote platform: {signature or 'unknown'}")
        return mapping[signature]

    @staticmethod
    def _resolve_remote_home(ssh_service) -> str:
        exit_code, stdout, stderr = ssh_service.run('printf "%s" "$HOME"', timeout=10)
        if exit_code != 0:
            raise RemoteRunnerManagerError(stderr.strip() or stdout.strip() or "failed to resolve remote home")
        home_dir = stdout.strip()
        if not home_dir:
            raise RemoteRunnerManagerError("remote home directory is empty")
        return home_dir

    @staticmethod
    def _build_remote_config_payload(
        *,
        version: str,
        mode: str,
        remote_port: int,
        token: str,
        remote_shared: str,
        remote_release: str,
        runner_python: str,
        managed_conda_command: str,
        managed_conda_root_prefix: str,
    ) -> dict[str, Any]:
        return {
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
            "runner_python": runner_python,
            "managed_conda_command": managed_conda_command,
            "managed_conda_root_prefix": managed_conda_root_prefix,
        }

    def _ensure_workflow_runtime(
        self,
        ssh_service,
        *,
        remote_tools_root: str,
        remote_tools_bin: str,
        remote_managed_root_prefix: str,
        remote_managed_micromamba: str,
        remote_managed_conda: str,
    ) -> dict[str, Any]:
        self._install_managed_micromamba(
            ssh_service,
            remote_tools_root=remote_tools_root,
            remote_tools_bin=remote_tools_bin,
            remote_managed_root_prefix=remote_managed_root_prefix,
            remote_managed_micromamba=remote_managed_micromamba,
            remote_managed_conda=remote_managed_conda,
        )
        return {
            "workflow_runtime": {
                "source": "managed",
                "provider": "micromamba",
                "command": remote_managed_conda,
                "executable": remote_managed_micromamba,
                "root_prefix": remote_managed_root_prefix,
                "bin_dir": remote_tools_bin,
            },
        }

    def _install_managed_micromamba(
        self,
        ssh_service,
        *,
        remote_tools_root: str,
        remote_tools_bin: str,
        remote_managed_root_prefix: str,
        remote_managed_micromamba: str,
        remote_managed_conda: str,
    ) -> None:
        install_cmd = f"""
set -euo pipefail
TOOLS_ROOT={shlex.quote(remote_tools_root)}
TOOLS_BIN={shlex.quote(remote_tools_bin)}
ROOT_PREFIX={shlex.quote(remote_managed_root_prefix)}
MICROMAMBA_BIN={shlex.quote(remote_managed_micromamba)}
CONDA_SHIM={shlex.quote(remote_managed_conda)}
if [ -x "$MICROMAMBA_BIN" ] && [ -x "$CONDA_SHIM" ]; then
  exit 0
fi
TMPDIR="$(mktemp -d)"
cleanup() {{
  rm -rf "$TMPDIR"
}}
trap cleanup EXIT
case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:amd64) URL="https://micro.mamba.pm/api/micromamba/linux-64/latest" ;;
  Linux:aarch64|Linux:arm64) URL="https://micro.mamba.pm/api/micromamba/linux-aarch64/latest" ;;
  Darwin:x86_64) URL="https://micro.mamba.pm/api/micromamba/osx-64/latest" ;;
  Darwin:arm64) URL="https://micro.mamba.pm/api/micromamba/osx-arm64/latest" ;;
  *) echo "unsupported platform for managed micromamba: $(uname -s):$(uname -m)" >&2; exit 1 ;;
esac
mkdir -p "$TOOLS_BIN" "$ROOT_PREFIX"
if command -v curl >/dev/null 2>&1; then
  curl -Ls "$URL" | tar -xvj -C "$TMPDIR" bin/micromamba >/dev/null
elif command -v wget >/dev/null 2>&1; then
  wget -qO- "$URL" | tar -xvj -C "$TMPDIR" bin/micromamba >/dev/null
else
  echo "curl or wget is required to install managed micromamba" >&2
  exit 1
fi
cp "$TMPDIR/bin/micromamba" "$MICROMAMBA_BIN"
chmod 0755 "$MICROMAMBA_BIN"
cat > "$CONDA_SHIM" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec {shlex.quote(remote_managed_micromamba)} "$@"
EOF
chmod 0755 "$CONDA_SHIM"
ln -sfn "$MICROMAMBA_BIN" "$TOOLS_BIN/mamba"
"""
        self._run_checked(
            ssh_service,
            install_cmd,
            step="install managed workflow runtime",
            timeout=180,
        )

    @staticmethod
    def _wait_for_runner_health(
        client: RemoteRunnerHttpClient,
        *,
        attempts: int = 8,
        delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return client.get_health()
            except Exception as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break
                time.sleep(delay_seconds)
        raise RemoteRunnerManagerError(str(last_error) or "remote runner health check failed")

    @staticmethod
    def _run_checked(ssh_service, cmd: str, *, step: str, timeout: int) -> tuple[int, str, str]:
        exit_code, stdout, stderr = ssh_service.run(cmd, timeout=timeout)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or f"{step} failed"
            raise RemoteRunnerManagerError(f"{step}: {detail}")
        return exit_code, stdout, stderr
