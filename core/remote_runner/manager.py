from __future__ import annotations

import secrets
import shlex
from typing import Any

from config import store_runner_token
from core.remote_runner.artifact import (
    RemoteRunnerArtifactError,
    RemoteRunnerArtifactProvider,
    WORKFLOW_RUNTIME_VERSION,
    WorkflowRuntimeArtifactProvider,
)
from core.remote_runner.bootstrap_activation import RemoteRunnerBootstrapActivationMixin
from core.remote_runner.bootstrap_bundle import RemoteRunnerBootstrapBundleMixin
from core.remote_runner.bootstrap_config_files import (
    BootstrapConfigTempFiles,
    cleanup_bootstrap_config_temp_files,
    write_bootstrap_config_temp_files,
)
from core.remote_runner.bootstrap_response import (
    build_bootstrap_install_response,
    build_bootstrap_reuse_response,
)
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.catalog import RemoteRunnerCatalogMixin
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient
from core.remote_runner.environment import RemoteRunnerEnvironmentMixin
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.layout import remote_runner_bootstrap_layout
from core.remote_runner.install_lock import RemoteRunnerInstallLockMixin
from core.remote_runner.metadata import (
    build_fast_reuse_metadata,
    build_install_bootstrap_metadata,
    build_remote_config_payload,
    build_remote_workflow_profile_content,
    build_workflow_runtime_metadata,
    compact_preview_payload,
    mark_reuse_bootstrap_phases_skipped,
    platform_from_metadata,
    reuse_failed,
    summarize_artifact,
)
from core.remote_runner.proxy import RemoteRunnerProxyMixin
from core.remote_runner.readiness import RemoteRunnerReadinessMixin
from core.remote_runner.remote_io import RemoteRunnerRemoteIoMixin
from core.remote_runner.reuse import RemoteRunnerReuseMixin
from core.remote_runner.token_rotation import RemoteRunnerTokenRotationMixin
from core.remote_runner.workflow_runtime import RemoteRunnerWorkflowRuntimeMixin


class RemoteRunnerManager(
    RemoteRunnerEnvironmentMixin,
    RemoteRunnerInstallLockMixin,
    RemoteRunnerRemoteIoMixin,
    RemoteRunnerReadinessMixin,
    RemoteRunnerProxyMixin,
    RemoteRunnerTokenRotationMixin,
    RemoteRunnerCatalogMixin,
    RemoteRunnerReuseMixin,
    RemoteRunnerWorkflowRuntimeMixin,
    RemoteRunnerBootstrapBundleMixin,
    RemoteRunnerBootstrapActivationMixin,
):
    _manager_error = RemoteRunnerManagerError
    _build_fast_reuse_metadata = staticmethod(build_fast_reuse_metadata)
    _build_remote_config_payload = staticmethod(build_remote_config_payload)
    _build_remote_workflow_profile_content = staticmethod(build_remote_workflow_profile_content)
    _build_workflow_runtime_metadata = staticmethod(build_workflow_runtime_metadata)
    _compact_preview_payload = staticmethod(compact_preview_payload)
    _mark_reuse_bootstrap_phases_skipped = staticmethod(mark_reuse_bootstrap_phases_skipped)
    _platform_from_metadata = staticmethod(platform_from_metadata)
    _reuse_failed = staticmethod(reuse_failed)
    _summarize_artifact = staticmethod(summarize_artifact)

    def __init__(
        self,
        artifact_provider: RemoteRunnerArtifactProvider | None = None,
        workflow_artifact_provider: WorkflowRuntimeArtifactProvider | None = None,
    ):
        self._artifact_provider = artifact_provider or RemoteRunnerArtifactProvider()
        self._workflow_artifact_provider = workflow_artifact_provider or WorkflowRuntimeArtifactProvider()

    def bootstrap(self, **kwargs) -> dict[str, Any]:
        bootstrap_metadata: dict[str, Any] | None = None
        try:
            server_id = str(kwargs["server_id"])
            server = kwargs["server"]
            ssh_service = kwargs["ssh_service"]
            server_record = kwargs.get("server_record") or {}
            version = REMOTE_RUNNER_VERSION
            home_dir = self._resolve_remote_home(ssh_service)
            paths = remote_runner_bootstrap_layout(home_dir, version)
            requested_remote_port = 0
            remote_platform = self._detect_remote_platform(ssh_service)
            previous_release = self._read_current_release_target(ssh_service, paths.current)
            fast_platform = platform_from_metadata(server_record) or remote_platform
            workflow_runtime_dir = paths.workflow_runtime_dir(version=WORKFLOW_RUNTIME_VERSION, platform=fast_platform)
            remote_workflow_bundle = paths.workflow_runtime_bundle(version=WORKFLOW_RUNTIME_VERSION, platform=fast_platform)
            workflow_artifact = self._resolve_workflow_artifact_for_bootstrap(
                ssh_service=ssh_service,
                version=WORKFLOW_RUNTIME_VERSION,
                platform=fast_platform,
                remote_dir=workflow_runtime_dir,
                remote_bundle=remote_workflow_bundle,
            )
            remote_workflow_artifact_sha = f"{workflow_runtime_dir}/artifact.sha256"
            artifact = self._artifact_provider.resolve(version=version, platform=remote_platform)

            fast_reuse_metadata = build_fast_reuse_metadata(
                server_record=server_record,
                version=version,
                remote_service_python=paths.service_python,
            )
            reuse_result = self._try_reuse_existing_runner_fast(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                version=version,
                remote_release=paths.release,
                remote_current=paths.current,
                remote_runtime_state=paths.runtime_state,
                remote_config=paths.config,
                remote_artifact_sha=paths.artifact_sha,
                artifact_sha=str(getattr(artifact, "sha256", "") or ""),
                workflow_artifact=workflow_artifact,
                workflow_runtime_dir=workflow_runtime_dir,
                remote_workflow_artifact_sha=remote_workflow_artifact_sha,
                bootstrap_metadata=fast_reuse_metadata,
            )
            if reuse_result is not None:
                return build_bootstrap_reuse_response(reuse_result, server)

            mode = self._detect_mode(ssh_service)
            previous_config_payload = self._read_remote_json_if_exists(
                ssh_service,
                paths.config,
                "remote runner config",
            )
            previous_mode = str((previous_config_payload or {}).get("mode") or server_record.get("runner_mode") or "")
            if workflow_artifact.platform != remote_platform:
                workflow_runtime_dir = paths.workflow_runtime_dir(version=WORKFLOW_RUNTIME_VERSION, platform=remote_platform)
                remote_workflow_bundle = paths.workflow_runtime_bundle(version=WORKFLOW_RUNTIME_VERSION, platform=remote_platform)
                workflow_artifact = self._resolve_workflow_artifact_for_bootstrap(
                    ssh_service=ssh_service,
                    version=WORKFLOW_RUNTIME_VERSION,
                    platform=remote_platform,
                    remote_dir=workflow_runtime_dir,
                    remote_bundle=remote_workflow_bundle,
                )
                remote_workflow_artifact_sha = f"{workflow_runtime_dir}/artifact.sha256"
            workflow_runtime = build_workflow_runtime_metadata(
                artifact=workflow_artifact,
                remote_dir=workflow_runtime_dir,
            )
            token = secrets.token_urlsafe(24)
            bootstrap_metadata = build_install_bootstrap_metadata(
                mode=mode,
                remote_platform=remote_platform,
                artifact=artifact,
                workflow_runtime=workflow_runtime,
                remote_service_python=paths.service_python,
                remote_profile_dir=paths.profile_dir,
                remote_profile_path=paths.profile_path,
                remote_profile_name=paths.profile_name,
                remote_release=paths.release,
                previous_release=previous_release,
                previous_mode=previous_mode,
            )

            reuse_result = self._try_reuse_existing_runner(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                version=version,
                mode=mode,
                remote_platform=remote_platform,
                remote_release=paths.release,
                remote_current=paths.current,
                remote_runtime_state=paths.runtime_state,
                remote_artifact_sha=paths.artifact_sha,
                artifact_sha=str(getattr(artifact, "sha256", "") or ""),
                remote_config=paths.config,
                workflow_artifact=workflow_artifact,
                workflow_runtime_dir=workflow_runtime_dir,
                remote_workflow_artifact_sha=remote_workflow_artifact_sha,
                bootstrap_metadata=bootstrap_metadata,
            )
            if reuse_result is not None:
                return build_bootstrap_reuse_response(reuse_result, server)

            self._acquire_remote_install_lock(
                ssh_service=ssh_service,
                lock_dir=paths.install_lock,
                remote_root=paths.root,
                bootstrap_metadata=bootstrap_metadata,
            )
            config_temp_files: BootstrapConfigTempFiles | None = None
            try:
                reuse_result = self._try_reuse_existing_runner(
                    server_id=server_id,
                    ssh_service=ssh_service,
                    server_record=server_record,
                    version=version,
                    mode=mode,
                    remote_platform=remote_platform,
                    remote_release=paths.release,
                    remote_current=paths.current,
                    remote_runtime_state=paths.runtime_state,
                    remote_artifact_sha=paths.artifact_sha,
                    artifact_sha=str(getattr(artifact, "sha256", "") or ""),
                    remote_config=paths.config,
                    workflow_artifact=workflow_artifact,
                    workflow_runtime_dir=workflow_runtime_dir,
                    remote_workflow_artifact_sha=remote_workflow_artifact_sha,
                    bootstrap_metadata=bootstrap_metadata,
                )
                if reuse_result is not None:
                    return build_bootstrap_reuse_response(reuse_result, server)

                self._deploy_service_runtime_bundle(
                    ssh_service=ssh_service,
                    artifact=artifact,
                    paths=paths,
                )

                workflow_runtime = self._ensure_workflow_runtime(
                    ssh_service=ssh_service,
                    artifact=workflow_artifact,
                    remote_bundle=remote_workflow_bundle,
                    remote_dir=workflow_runtime_dir,
                    remote_artifact_sha=remote_workflow_artifact_sha,
                    bootstrap_metadata=bootstrap_metadata,
                )
                config_payload = self._build_remote_config_payload(
                    version=version,
                    mode=mode,
                    remote_port=requested_remote_port,
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
                )
                config_temp_files = write_bootstrap_config_temp_files(
                    previous_config_payload=previous_config_payload,
                    config_payload=config_payload,
                )
                self._upload_remote_file_atomic(
                    ssh_service,
                    local_path=config_temp_files.config_path,
                    remote_path=paths.config,
                    step="write remote runner config",
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
                    'cd {release} && H2OMETA_REMOTE_CONFIG={config} {python} -c "from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())"'.format(
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
                release_switch = dict(bootstrap_metadata.get("release_switch") or {})
                try:
                    self._switch_current_release(
                        ssh_service=ssh_service,
                        target=paths.release,
                        link_path=paths.current,
                    )
                    release_switch["switched"] = True
                    bootstrap_metadata["release_switch"] = release_switch
                    self._start_remote_runner_service(
                        ssh_service=ssh_service,
                        remote_release=paths.release,
                        remote_current=paths.current,
                        remote_config=paths.config,
                        remote_log=paths.log,
                        mode=mode,
                    )
                    runtime_state = self._wait_for_runtime_state(
                        ssh_service=ssh_service,
                        remote_runtime_state=paths.runtime_state,
                        version=version,
                    )
                    remote_port = int(runtime_state["bindPort"])
                    tunnel = ssh_service.ensure_local_tunnel(
                        f"runner-{server_id}",
                        remote_host="127.0.0.1",
                        remote_port=remote_port,
                    )
                    client = RemoteRunnerHttpClient(
                        base_url=f"http://127.0.0.1:{tunnel.local_port}",
                        token=token,
                        timeout=30,
                    )
                    health = self._wait_for_runner_health(client)
                    try:
                        self._run_bootstrap_canary(
                            client=client,
                            server_id=server_id,
                            bootstrap_metadata=bootstrap_metadata,
                        )
                    except RemoteRunnerManagerError as exc:
                        if not self._canary_failure_needs_fresh_tunnel_retry(str(exc)):
                            raise
                        runtime_state = self._wait_for_runtime_state(
                            ssh_service=ssh_service,
                            remote_runtime_state=paths.runtime_state,
                            version=version,
                        )
                        remote_port = int(runtime_state["bindPort"])
                        close_tunnel = getattr(ssh_service, "close_local_tunnel", None)
                        if callable(close_tunnel):
                            close_tunnel(f"runner-{server_id}")
                        tunnel = ssh_service.ensure_local_tunnel(
                            f"runner-{server_id}",
                            remote_host="127.0.0.1",
                            remote_port=remote_port,
                        )
                        client = RemoteRunnerHttpClient(
                            base_url=f"http://127.0.0.1:{tunnel.local_port}",
                            token=token,
                            timeout=30,
                        )
                        health = self._wait_for_runner_health(client)
                        bootstrap_metadata["canary_retry"] = {
                            "reason": str(exc),
                            "servicePort": remote_port,
                            "tunnelPort": tunnel.local_port,
                        }
                        self._run_bootstrap_canary(
                            client=client,
                            server_id=server_id,
                            bootstrap_metadata=bootstrap_metadata,
                        )
                    release_switch["active_release"] = paths.release
                    bootstrap_metadata["release_switch"] = release_switch
                except (RemoteRunnerManagerError, RemoteRunnerClientError) as exc:
                    self._attempt_release_rollback(
                        ssh_service=ssh_service,
                        server_id=server_id,
                        server_record=server_record,
                        previous_version=str((previous_config_payload or {}).get("version") or server_record.get("bootstrap_version") or ""),
                        previous_release=previous_release,
                        previous_mode=previous_mode,
                        previous_config_path=config_temp_files.previous_config_path,
                        remote_current=paths.current,
                        remote_config=paths.config,
                        remote_log=paths.log,
                        remote_runtime_state=paths.runtime_state,
                        bootstrap_metadata=bootstrap_metadata,
                        failure=str(exc) or "remote runner activation failed",
                    )
                    raise self._bootstrap_failure(
                        str(exc) or "remote runner activation failed",
                        bootstrap_metadata=bootstrap_metadata,
                    ) from exc
                token_ref = store_runner_token(server_id=server_id, token=token)
                return build_bootstrap_install_response(
                    version=version,
                    mode=mode,
                    tunnel_port=tunnel.local_port,
                    token_ref=token_ref,
                    health=health,
                    service_port=remote_port,
                    server=server,
                    bootstrap_metadata=bootstrap_metadata,
                )
            finally:
                try:
                    if config_temp_files is not None:
                        cleanup_bootstrap_config_temp_files(config_temp_files)
                finally:
                    self._release_remote_install_lock(ssh_service=ssh_service, lock_dir=paths.install_lock)
        except RemoteRunnerManagerError:
            raise
        except RemoteRunnerArtifactError as exc:
            raise RemoteRunnerManagerError(str(exc), bootstrap_metadata=bootstrap_metadata) from exc
