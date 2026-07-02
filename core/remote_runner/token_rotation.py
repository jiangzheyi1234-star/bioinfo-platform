from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from config import store_runner_token
from core.contracts.remote_endpoints import EXECUTION_LIFECYCLE_GUARD_RELEASE
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient
from core.remote_runner.health import build_runner_health
from core.remote_runner.layout import (
    remote_runner_config,
    remote_runner_release,
    remote_runner_runtime_state,
    remote_runner_shared,
    remote_runner_start_command,
)
from core.remote_runner.lifecycle_guard_owner import execution_lifecycle_guard_owner


TOKEN_ROTATION_LIFECYCLE_ACTION = "token-rotation"


def _runner_rotation_failure_types() -> tuple[type[BaseException], ...]:
    from core.remote_runner.manager import RemoteRunnerManagerError

    return (RemoteRunnerManagerError, RemoteRunnerClientError, OSError, EOFError)


class RemoteRunnerTokenRotationMixin:
    def rotate_token(self, **kwargs) -> dict[str, Any]:
        server_id = str(kwargs["server_id"])
        record = kwargs["server_record"]
        ssh_service = kwargs["ssh_service"]
        version = str(record.get("bootstrap_version") or "").strip()
        if not version:
            raise self._manager_error("runner is not bootstrapped")
        remote_port = self._require_service_port(record)
        token = secrets.token_urlsafe(24)
        home_dir = self._resolve_remote_home(ssh_service)
        remote_config = remote_runner_config(home_dir)
        tooling = (record.get("bootstrap_metadata") or {}).get("tooling") or {}
        service_runtime = tooling.get("service_runtime") or {}
        workflow_runtime = tooling.get("workflow_runtime") or {}
        guard_owner = execution_lifecycle_guard_owner(
            server_id=server_id,
            action=TOKEN_ROTATION_LIFECYCLE_ACTION,
        )
        old_config_path: Path | None = None
        with tempfile.NamedTemporaryFile("w+b", delete=False, suffix=".json") as handle:
            old_config_path = Path(handle.name)
        ssh_service.download(remote_config, str(old_config_path))

        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
            json.dump(
                self._build_remote_config_payload(
                    version=version,
                    mode=str(record.get("runner_mode") or "background_process"),
                    remote_port=remote_port,
                    token=token,
                    remote_shared=remote_runner_shared(home_dir),
                    remote_release=remote_runner_release(home_dir, version),
                    remote_runtime_state=remote_runner_runtime_state(home_dir),
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
        self.request_execution_lifecycle_guard(
            server_id=server_id,
            ssh_service=ssh_service,
            server_record=record,
            action=TOKEN_ROTATION_LIFECYCLE_ACTION,
            owner=guard_owner,
            ttl_seconds=600,
            timeout=30,
        )
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
                    remote_runner_start_command(home_dir, remote_config),
                    timeout=30,
                )
            tunnel = self._open_runner_tunnel(
                server_id=server_id,
                ssh_service=ssh_service,
                remote_port=remote_port,
            )
            client = RemoteRunnerHttpClient(
                base_url=f"http://127.0.0.1:{tunnel.local_port}",
                token=token,
                timeout=5,
            )
            build_runner_health(client)
            self._release_token_rotation_guard(client=client, owner=guard_owner)
        except _runner_rotation_failure_types():
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
                        ssh_service.run("pkill -f '[r]emote_runner.run' || true", timeout=10)
                        ssh_service.run(
                            remote_runner_start_command(home_dir, remote_config),
                            timeout=30,
                        )
                    self.release_execution_lifecycle_guard(
                        server_id=server_id,
                        ssh_service=ssh_service,
                        server_record=record,
                        action=TOKEN_ROTATION_LIFECYCLE_ACTION,
                        owner=guard_owner,
                        timeout=30,
                    )
                except _runner_rotation_failure_types() as restore_exc:
                    restore_detail = str(restore_exc) or restore_exc.__class__.__name__
                    raise self._manager_error(
                        f"runner token rotation failed; previous config restore also failed: {restore_detail}"
                    ) from restore_exc
            raise
        token_ref = store_runner_token(server_id=server_id, token=token)
        return {"token_ref": token_ref}

    @classmethod
    def _release_token_rotation_guard(cls, *, client: RemoteRunnerHttpClient, owner: str) -> None:
        cls._call_lifecycle_guard_endpoint_with_client(
            client=client,
            endpoint_id=EXECUTION_LIFECYCLE_GUARD_RELEASE,
            payload={"action": TOKEN_ROTATION_LIFECYCLE_ACTION, "owner": owner},
        )
