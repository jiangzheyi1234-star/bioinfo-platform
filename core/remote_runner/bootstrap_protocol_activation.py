from __future__ import annotations

import shlex
from typing import Any

from core.remote_runner.bootstrap_config_files import (
    BootstrapConfigTempFiles,
    cleanup_bootstrap_config_temp_files,
    write_bootstrap_config_temp_files,
)


class RemoteRunnerBootstrapProtocolActivationMixin:
    """Stage and promote a protocol-bound config without exposing candidates."""

    def _prepare_remote_runner_protocol_candidate(
        self,
        *,
        ssh_service,
        artifact,
        workflow_runtime: dict[str, Any],
        version: str,
        mode: str,
        token: str,
        paths,
        previous_config_payload: dict[str, Any] | None,
        remote_candidate_config: str,
    ) -> tuple[BootstrapConfigTempFiles, dict[str, Any]]:
        descriptor = artifact.manifest.get("runnerProtocol") or {}
        config_payload = self._build_remote_config_payload(
            version=version,
            mode=mode,
            remote_port=0,
            token=token,
            remote_shared=paths.shared,
            remote_release=paths.release,
            remote_runtime_state=paths.runtime_state,
            runner_python=paths.service_python,
            managed_conda_command=str(workflow_runtime.get("command") or ""),
            managed_conda_root_prefix=str(workflow_runtime.get("root_prefix") or ""),
            workflow_runtime_provider=str(workflow_runtime.get("provider") or ""),
            workflow_runtime_source=str(workflow_runtime.get("source") or ""),
            workflow_runtime_version=str(workflow_runtime.get("version") or ""),
            snakemake_command=str(workflow_runtime.get("snakemake_command") or ""),
            snakemake_version=str(workflow_runtime.get("snakemake_version") or ""),
            workflow_profile_dir=paths.profile_dir,
            workflow_profile_name=paths.profile_name,
            runner_protocol_version=str(descriptor.get("protocolVersion") or ""),
            runner_protocol_fingerprint=str(
                artifact.manifest.get("runnerProtocolFingerprint") or ""
            ),
        )
        temp_files = write_bootstrap_config_temp_files(
            previous_config_payload=previous_config_payload,
            config_payload=config_payload,
        )
        try:
            self._upload_remote_file_atomic(
                ssh_service,
                local_path=temp_files.config_path,
                remote_path=remote_candidate_config,
                step="write remote runner candidate config",
                timeout=10,
            )
            self._verify_remote_config_payload(
                ssh_service=ssh_service,
                remote_config=remote_candidate_config,
                expected=config_payload,
            )
            self._run_checked(
                ssh_service,
                'cd {release} && H2OMETA_REMOTE_CONFIG={config} {python} -B -c "from remote_runner.runner_protocol_startup import require_runner_protocol_startup_preflight; require_runner_protocol_startup_preflight()"'.format(
                    release=shlex.quote(paths.release),
                    config=shlex.quote(remote_candidate_config),
                    python=shlex.quote(paths.service_python),
                ),
                step="validate remote runner candidate config",
                timeout=60,
            )
        except BaseException:
            cleanup_bootstrap_config_temp_files(temp_files)
            raise
        return temp_files, config_payload

    def _promote_remote_runner_protocol_candidate(
        self,
        *,
        ssh_service,
        paths,
        remote_candidate_config: str,
        config_payload: dict[str, Any],
        bootstrap_metadata: dict[str, Any],
    ) -> None:
        self._run_checked(
            ssh_service,
            "test -s {candidate} && mv -f {candidate} {config}".format(
                candidate=shlex.quote(remote_candidate_config),
                config=shlex.quote(paths.config),
            ),
            step="promote remote runner candidate config",
            timeout=10,
        )
        self._verify_remote_config_payload(
            ssh_service=ssh_service,
            remote_config=paths.config,
            expected=config_payload,
        )
        self._write_remote_workflow_profile(
            ssh_service=ssh_service,
            remote_profile_path=paths.profile_path,
            remote_profile_dir=paths.profile_dir,
            remote_conda_prefix=paths.conda_prefix,
            remote_wrapper_prefix=paths.wrapper_prefix,
            bootstrap_metadata=bootstrap_metadata,
        )
        self._run_checked(
            ssh_service,
            'cd {release} && H2OMETA_REMOTE_CONFIG={config} {python} -B -c "from remote_runner.runner_protocol_startup import initialize_runtime_layout_from_explicit_config; initialize_runtime_layout_from_explicit_config()"'.format(
                release=shlex.quote(paths.release),
                config=shlex.quote(paths.config),
                python=shlex.quote(paths.service_python),
            ),
            step="initialize remote runner layout",
            timeout=60,
        )
        self._run_checked(
            ssh_service,
            f"rm -f {shlex.quote(paths.runtime_state)}",
            step="clear previous remote runner runtime state",
            timeout=10,
        )

    def _pre_activation_failure(
        self,
        *,
        exc: Exception,
        bootstrap_action: str,
        bootstrap_metadata: dict[str, Any],
    ) -> Exception | None:
        rollback = bootstrap_metadata.get("rollback")
        if isinstance(rollback, dict) and rollback.get("attempted") is True:
            return None
        guard = bootstrap_metadata.get("upgradeGuard")
        owner = (
            str(guard.get("maintenanceOwner") or "").strip()
            if isinstance(guard, dict)
            else ""
        )
        if not owner:
            return self._bootstrap_failure(
                str(exc) or "remote runner preparation failed",
                bootstrap_metadata=bootstrap_metadata,
            )
        recovery = {
            "schemaVersion": (
                "h2ometa.remote-runner-pre-activation-guard-recovery.v1"
            ),
            "bootstrapAction": str(bootstrap_action or "").strip() or "ensure",
            "maintenanceOwner": owner,
            "forwardRepairRequired": True,
            "failClosed": True,
            "admissionState": "guarded-or-unknown",
            "message": (
                "pre-activation preparation failed after lifecycle guard acquisition; "
                "the guard was retained because no exact ready recovery was proven"
            ),
            "nextAction": (
                "repair or restore an exact current-protocol runner, verify runtime state "
                "and ready health, then perform an owner-matched guard release"
            ),
        }
        bootstrap_metadata["preActivationRecovery"] = recovery
        detail = (
            f"{str(exc) or 'remote runner preparation failed'}; "
            "lifecycle guard retained pending verified recovery"
        )
        return self._bootstrap_failure(detail, bootstrap_metadata=bootstrap_metadata)

    def _cleanup_remote_runner_protocol_candidate(
        self,
        *,
        ssh_service,
        remote_candidate_config: str,
        temp_files: BootstrapConfigTempFiles | None,
    ) -> None:
        try:
            self._run_checked(
                ssh_service,
                f"rm -f {shlex.quote(remote_candidate_config)}",
                step="remove remote runner candidate config",
                timeout=10,
            )
        finally:
            if temp_files is not None:
                cleanup_bootstrap_config_temp_files(temp_files)


__all__ = ["RemoteRunnerBootstrapProtocolActivationMixin"]
