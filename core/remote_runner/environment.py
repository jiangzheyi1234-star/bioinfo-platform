from __future__ import annotations

import shlex
from typing import Any


class RemoteRunnerEnvironmentMixin:
    _manager_error: type[Exception]

    @classmethod
    def _verify_remote_manifest(cls, manifest: dict[str, Any], *, version: str, platform: str) -> None:
        if str(manifest.get("service") or "") != "h2ometa-remote":
            raise cls._manager_error("remote runner manifest has unexpected service")
        if str(manifest.get("version") or "") != version:
            raise cls._manager_error("remote runner manifest version mismatch")
        if str(manifest.get("platform") or "") != platform:
            raise cls._manager_error("remote runner manifest platform mismatch")
        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        if str(runtime.get("provider") or "") != "bundled" or str(runtime.get("python") or "") != "runtime/bin/python":
            raise cls._manager_error("remote runner manifest does not declare bundled runtime")

    @classmethod
    def _verify_remote_manifest_for_reuse(cls, manifest: dict[str, Any], *, version: str, platform: str) -> None:
        if str(manifest.get("service") or "") != "h2ometa-remote":
            raise cls._manager_error("remote runner manifest has unexpected service")
        if str(manifest.get("version") or "") != version:
            raise cls._manager_error("remote runner manifest version mismatch")
        if platform and str(manifest.get("platform") or "") != platform:
            raise cls._manager_error("remote runner manifest platform mismatch")
        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        if str(runtime.get("provider") or "") != "bundled" or str(runtime.get("python") or "") != "runtime/bin/python":
            raise cls._manager_error("remote runner manifest does not declare bundled runtime")

    @classmethod
    def _verify_remote_config_payload(
        cls,
        *,
        ssh_service,
        remote_config: str,
        expected: dict[str, Any],
    ) -> None:
        actual = cls._read_remote_json(ssh_service, remote_config, "remote runner config")
        required_keys = (
            "version",
            "mode",
            "bind_host",
            "bind_port",
            "token",
            "data_root",
            "database_backend",
            "db_path",
            "runtime_state_path",
            "release_dir",
            "runner_python",
            "managed_conda_command",
            "managed_conda_root_prefix",
            "workflow_runtime_provider",
            "workflow_runtime_source",
            "workflow_runtime_version",
            "snakemake_command",
            "snakemake_version",
            "workflow_profile_dir",
            "workflow_profile_name",
        )
        for key in required_keys:
            if actual.get(key) != expected.get(key):
                raise cls._manager_error(f"remote runner config verification failed: {key}")

    @classmethod
    def _require_service_port(cls, record: dict[str, Any]) -> int:
        raw = record.get("service_port")
        try:
            port = int(raw)
        except (TypeError, ValueError) as exc:
            raise cls._manager_error(
                "remote runner service_port is missing; bootstrap did not complete"
            ) from exc
        if port <= 0 or port > 65535:
            raise cls._manager_error(
                "remote runner service_port is invalid; bootstrap did not complete"
            )
        return port

    @staticmethod
    def _detect_mode(ssh_service) -> str:
        exit_code, stdout, _stderr = ssh_service.run(
            "if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then echo systemd_user; else echo background_process; fi",
            timeout=10,
        )
        if exit_code == 0 and stdout.strip() == "systemd_user":
            return "systemd_user"
        return "background_process"

    @classmethod
    def _detect_remote_platform(cls, ssh_service) -> str:
        exit_code, stdout, stderr = ssh_service.run('printf "%s:%s" "$(uname -s)" "$(uname -m)"', timeout=10)
        if exit_code != 0:
            raise cls._manager_error(
                stderr.strip() or stdout.strip() or "failed to detect remote platform"
            )
        mapping = {
            "Linux:x86_64": "linux-64",
            "Linux:amd64": "linux-64",
            "Linux:aarch64": "linux-aarch64",
            "Linux:arm64": "linux-aarch64",
        }
        signature = stdout.strip()
        if signature not in mapping:
            raise cls._manager_error(f"unsupported remote platform: {signature or 'unknown'}")
        return mapping[signature]

    @classmethod
    def _resolve_remote_home(cls, ssh_service) -> str:
        exit_code, stdout, stderr = ssh_service.run('printf "%s" "$HOME"', timeout=10)
        if exit_code != 0:
            raise cls._manager_error(
                stderr.strip() or stdout.strip() or "failed to resolve remote home"
            )
        home_dir = stdout.strip()
        if not home_dir:
            raise cls._manager_error("remote home directory is empty")
        return home_dir

    @staticmethod
    def _read_current_release_target(ssh_service, remote_current: str) -> str:
        exit_code, stdout, _stderr = ssh_service.run(f"readlink -f {shlex.quote(remote_current)}", timeout=10)
        if exit_code != 0:
            return ""
        return stdout.strip()
