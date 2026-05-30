from __future__ import annotations

import base64
import json
import secrets
import shlex
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from config import resolve_runner_token, store_runner_token
from core.remote_runner.artifact import (
    RemoteRunnerArtifactError,
    RemoteRunnerArtifactProvider,
    WORKFLOW_RUNTIME_VERSION,
    WorkflowRuntimeArtifact,
    WorkflowRuntimeArtifactProvider,
)
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.catalog import RemoteRunnerCatalogMixin
from core.remote_runner.client import RemoteRunnerHttpClient
from core.remote_runner.metadata import (
    build_fast_reuse_metadata,
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
from core.remote_runner.workflow_runtime_policy import allow_remote_workflow_runtime_registration, workflow_runtime_artifact_required_message


class RemoteRunnerManagerError(RuntimeError):
    def __init__(self, message: str, *, bootstrap_metadata: dict[str, Any] | None = None):
        super().__init__(message)
        self.bootstrap_metadata = bootstrap_metadata


class RemoteRunnerManager(RemoteRunnerRemoteIoMixin, RemoteRunnerReadinessMixin, RemoteRunnerProxyMixin, RemoteRunnerCatalogMixin):
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
        try:
            server_id = str(kwargs["server_id"])
            server = kwargs["server"]
            ssh_service = kwargs["ssh_service"]
            server_record = kwargs.get("server_record") or {}
            version = REMOTE_RUNNER_VERSION
            home_dir = self._resolve_remote_home(ssh_service)
            remote_root = f"{home_dir}/.h2ometa/runner"
            remote_release = f"{remote_root}/releases/{version}"
            remote_shared = f"{remote_root}/shared"
            remote_bundle = f"{remote_root}/bundle-{version}.tar.gz"
            remote_config = f"{remote_shared}/config/runner.json"
            remote_conda_prefix = f"{remote_shared}/conda-envs"
            remote_profile_dir = f"{remote_shared}/config/snakemake/default"
            remote_profile_name = "profile.v9+.yaml"
            remote_profile_path = f"{remote_profile_dir}/{remote_profile_name}"
            remote_runtime_state = f"{remote_shared}/runtime/runner-state.json"
            remote_log = f"{remote_shared}/logs/runner.log"
            remote_current = f"{remote_root}/current"
            remote_artifact_sha = f"{remote_release}/artifact.sha256"
            remote_tools = f"{remote_root}/tools"
            remote_install_lock = f"{remote_root}/locks/install-{version}.lock"
            requested_remote_port = 0
            remote_service_python = f"{remote_release}/runtime/bin/python"
            remote_platform = self._detect_remote_platform(ssh_service)
            previous_release = self._read_current_release_target(ssh_service, remote_current)
            fast_platform = platform_from_metadata(server_record) or remote_platform
            workflow_runtime_dir = f"{remote_tools}/workflow-runtime-{WORKFLOW_RUNTIME_VERSION}-{fast_platform}"
            remote_workflow_bundle = f"{remote_tools}/workflow-runtime-{WORKFLOW_RUNTIME_VERSION}-{fast_platform}.tar.gz"
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
                remote_service_python=remote_service_python,
            )
            reuse_result = self._try_reuse_existing_runner_fast(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                version=version,
                remote_release=remote_release,
                remote_current=remote_current,
                remote_runtime_state=remote_runtime_state,
                remote_config=remote_config,
                remote_artifact_sha=remote_artifact_sha,
                artifact_sha=str(getattr(artifact, "sha256", "") or ""),
                workflow_artifact=workflow_artifact,
                workflow_runtime_dir=workflow_runtime_dir,
                remote_workflow_artifact_sha=remote_workflow_artifact_sha,
                bootstrap_metadata=fast_reuse_metadata,
            )
            if reuse_result is not None:
                return {
                    **reuse_result,
                    "server_label": server.get("label", ""),
                }

            mode = self._detect_mode(ssh_service)
            previous_config_payload = self._read_remote_json_if_exists(
                ssh_service,
                remote_config,
                "remote runner config",
            )
            previous_mode = str((previous_config_payload or {}).get("mode") or server_record.get("runner_mode") or "")
            if workflow_artifact.platform != remote_platform:
                workflow_runtime_dir = f"{remote_tools}/workflow-runtime-{WORKFLOW_RUNTIME_VERSION}-{remote_platform}"
                remote_workflow_bundle = f"{remote_tools}/workflow-runtime-{WORKFLOW_RUNTIME_VERSION}-{remote_platform}.tar.gz"
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
            bootstrap_metadata: dict[str, Any] = {
                "preflight": {
                    "launcher": {"mode": mode},
                    "platform": remote_platform,
                },
                "tooling": {
                    "service_runtime": {
                        "provider": "bundled",
                        "source": "artifact",
                        "python": remote_service_python,
                        "platform": getattr(artifact, "platform", remote_platform),
                    },
                    "workflow_runtime": workflow_runtime,
                },
                "workflow_profile": {
                    "path": remote_profile_dir,
                    "config": remote_profile_path,
                    "name": remote_profile_name,
                },
                "deployment_action": "installed",
                "release_switch": {
                    "target_release": remote_release,
                    "target_mode": mode,
                    "previous_release": previous_release,
                    "previous_mode": previous_mode,
                    "switched": False,
                },
                "rollback": {
                    "attempted": False,
                    "restored": False,
                    "previous_release": previous_release,
                    "previous_mode": previous_mode,
                    "message": "",
                },
                "canary": {
                    "ok": False,
                    "status": "pending",
                    "message": "",
                },
            }

            reuse_result = self._try_reuse_existing_runner(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                version=version,
                mode=mode,
                remote_platform=remote_platform,
                remote_release=remote_release,
                remote_current=remote_current,
                remote_runtime_state=remote_runtime_state,
                remote_artifact_sha=remote_artifact_sha,
                artifact_sha=str(getattr(artifact, "sha256", "") or ""),
                remote_config=remote_config,
                workflow_artifact=workflow_artifact,
                workflow_runtime_dir=workflow_runtime_dir,
                remote_workflow_artifact_sha=remote_workflow_artifact_sha,
                bootstrap_metadata=bootstrap_metadata,
            )
            if reuse_result is not None:
                return {
                    **reuse_result,
                    "server_label": server.get("label", ""),
                }

            self._acquire_remote_install_lock(
                ssh_service=ssh_service,
                lock_dir=remote_install_lock,
                remote_root=remote_root,
                bootstrap_metadata=bootstrap_metadata,
            )
            previous_config_path: Path | None = None
            local_config_path: Path | None = None
            try:
                reuse_result = self._try_reuse_existing_runner(
                    server_id=server_id,
                    ssh_service=ssh_service,
                    server_record=server_record,
                    version=version,
                    mode=mode,
                    remote_platform=remote_platform,
                    remote_release=remote_release,
                    remote_current=remote_current,
                    remote_runtime_state=remote_runtime_state,
                    remote_artifact_sha=remote_artifact_sha,
                    artifact_sha=str(getattr(artifact, "sha256", "") or ""),
                    remote_config=remote_config,
                    workflow_artifact=workflow_artifact,
                    workflow_runtime_dir=workflow_runtime_dir,
                    remote_workflow_artifact_sha=remote_workflow_artifact_sha,
                    bootstrap_metadata=bootstrap_metadata,
                )
                if reuse_result is not None:
                    return {
                        **reuse_result,
                        "server_label": server.get("label", ""),
                    }

                self._run_checked(
                    ssh_service,
                    "mkdir -p "
                    + " ".join(
                        shlex.quote(path)
                        for path in (
                            f"{remote_root}/releases",
                            f"{remote_shared}/config",
                            f"{remote_shared}/data",
                            f"{remote_shared}/logs",
                            f"{remote_shared}/uploads",
                            f"{remote_shared}/results",
                            f"{remote_shared}/work",
                            remote_conda_prefix,
                            remote_profile_dir,
                            remote_tools,
                        )
                    ),
                    step="prepare remote runner directories",
                    timeout=20,
                )
                self._run_checked(
                    ssh_service,
                    "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true; "
                    "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true; "
                    f"rm -f {shlex.quote(remote_runtime_state)}",
                    step="clear previous remote runner service",
                    timeout=20,
                )
                ssh_service.upload(str(artifact.archive_path), remote_bundle)
                self._run_checked(
                    ssh_service,
                    "rm -rf {release} && mkdir -p {release} && tar -xzf {bundle} -C {release} && chmod 0755 {release}/*.sh".format(
                        release=shlex.quote(remote_release),
                        bundle=shlex.quote(remote_bundle),
                    ),
                    step="extract remote runner bundle",
                    timeout=60,
                )
                artifact_sha = str(getattr(artifact, "sha256", "") or "")
                if artifact_sha:
                    self._write_remote_text_atomic(
                        ssh_service,
                        path=remote_artifact_sha,
                        content=artifact_sha,
                        step="write remote runner artifact marker",
                        timeout=10,
                    )
                self._cleanup_remote_bundle(
                    ssh_service,
                    remote_bundle,
                    step="cleanup remote runner bundle",
                )

                workflow_runtime = self._ensure_workflow_runtime(
                    ssh_service=ssh_service,
                    artifact=workflow_artifact,
                    remote_bundle=remote_workflow_bundle,
                    remote_dir=workflow_runtime_dir,
                    remote_artifact_sha=remote_workflow_artifact_sha,
                    bootstrap_metadata=bootstrap_metadata,
                )
                if previous_config_payload is not None:
                    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
                        json.dump(previous_config_payload, handle, indent=2)
                        previous_config_path = Path(handle.name)
                config_payload = self._build_remote_config_payload(
                    version=version,
                    mode=mode,
                    remote_port=requested_remote_port,
                    token=token,
                    remote_shared=remote_shared,
                    remote_release=remote_release,
                    remote_runtime_state=remote_runtime_state,
                    runner_python=remote_service_python,
                    managed_conda_command=str(workflow_runtime.get("command") or ""),
                    managed_conda_root_prefix=str(workflow_runtime.get("root_prefix") or ""),
                    workflow_runtime_provider=str(workflow_runtime.get("provider") or ""),
                    workflow_runtime_source=str(workflow_runtime.get("source") or ""),
                    workflow_runtime_version=str(workflow_runtime.get("version") or ""),
                    snakemake_command=str(workflow_runtime.get("snakemake_command") or ""),
                    snakemake_version=str(workflow_runtime.get("snakemake_version") or ""),
                    workflow_profile_dir=remote_profile_dir,
                    workflow_profile_name=remote_profile_name,
                )
                with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as handle:
                    json.dump(config_payload, handle, indent=2)
                    local_config_path = Path(handle.name)
                self._upload_remote_file_atomic(
                    ssh_service,
                    local_path=local_config_path,
                    remote_path=remote_config,
                    step="write remote runner config",
                    timeout=10,
                )
                self._verify_remote_config_payload(
                    ssh_service=ssh_service,
                    remote_config=remote_config,
                    expected=config_payload,
                )
                self._write_remote_workflow_profile(
                    ssh_service=ssh_service,
                    remote_profile_path=remote_profile_path,
                    remote_profile_dir=remote_profile_dir,
                    remote_conda_prefix=remote_conda_prefix,
                    bootstrap_metadata=bootstrap_metadata,
                )
                self._run_checked(
                    ssh_service,
                    'cd {release} && H2OMETA_REMOTE_CONFIG={config} {python} -c "from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())"'.format(
                        release=shlex.quote(remote_release),
                        config=shlex.quote(remote_config),
                        python=shlex.quote(remote_service_python),
                    ),
                    step="initialize remote runner layout",
                    timeout=60,
                )
                self._run_checked(
                    ssh_service,
                    f"rm -f {shlex.quote(remote_runtime_state)}",
                    step="clear previous remote runner runtime state",
                    timeout=10,
                )
                release_switch = dict(bootstrap_metadata.get("release_switch") or {})
                try:
                    self._switch_current_release(
                        ssh_service=ssh_service,
                        target=remote_release,
                        link_path=remote_current,
                    )
                    release_switch["switched"] = True
                    bootstrap_metadata["release_switch"] = release_switch
                    self._start_remote_runner_service(
                        ssh_service=ssh_service,
                        remote_release=remote_release,
                        remote_current=remote_current,
                        remote_config=remote_config,
                        remote_log=remote_log,
                        mode=mode,
                    )
                    runtime_state = self._wait_for_runtime_state(
                        ssh_service=ssh_service,
                        remote_runtime_state=remote_runtime_state,
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
                        timeout=5,
                    )
                    health = self._wait_for_runner_health(client)
                    self._run_bootstrap_canary(
                        client=client,
                        server_id=server_id,
                        bootstrap_metadata=bootstrap_metadata,
                    )
                    release_switch["active_release"] = remote_release
                    bootstrap_metadata["release_switch"] = release_switch
                except Exception as exc:
                    self._attempt_release_rollback(
                        ssh_service=ssh_service,
                        server_id=server_id,
                        server_record=server_record,
                        previous_version=str((previous_config_payload or {}).get("version") or server_record.get("bootstrap_version") or ""),
                        previous_release=previous_release,
                        previous_mode=previous_mode,
                        previous_config_path=previous_config_path,
                        remote_current=remote_current,
                        remote_config=remote_config,
                        remote_log=remote_log,
                        remote_runtime_state=remote_runtime_state,
                        bootstrap_metadata=bootstrap_metadata,
                        failure=str(exc) or "remote runner activation failed",
                    )
                    raise self._bootstrap_failure(
                        str(exc) or "remote runner activation failed",
                        bootstrap_metadata=bootstrap_metadata,
                    ) from exc
                token_ref = store_runner_token(server_id=server_id, token=token)
                bootstrap_metadata["reuse_check"] = bootstrap_metadata.get("reuse_check") or {"ok": False, "reason": "not reusable"}
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
            finally:
                for temp_path in (local_config_path, previous_config_path):
                    if temp_path is None:
                        continue
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self._release_remote_install_lock(ssh_service=ssh_service, lock_dir=remote_install_lock)
        except RemoteRunnerManagerError:
            raise
        except RemoteRunnerArtifactError as exc:
            raise RemoteRunnerManagerError(str(exc), bootstrap_metadata=locals().get("bootstrap_metadata")) from exc
        except Exception as exc:
            raise RemoteRunnerManagerError(
                str(exc) or "remote runner bootstrap failed",
                bootstrap_metadata=locals().get("bootstrap_metadata"),
            ) from exc

    @staticmethod
    def _bootstrap_failure(detail: str, *, bootstrap_metadata: dict[str, Any]) -> RemoteRunnerManagerError:
        message = str(detail or "remote runner bootstrap failed").strip() or "remote runner bootstrap failed"
        rollback = bootstrap_metadata.get("rollback") if isinstance(bootstrap_metadata, dict) else None
        if isinstance(rollback, dict) and bool(rollback.get("attempted")):
            outcome = "rollback restored previous release" if bool(rollback.get("restored")) else "rollback did not restore previous release"
            rollback_message = str(rollback.get("message") or "").strip()
            if rollback_message:
                message = f"{message}; {outcome}: {rollback_message}"
            else:
                message = f"{message}; {outcome}"
        return RemoteRunnerManagerError(message, bootstrap_metadata=bootstrap_metadata)

    @classmethod
    def _start_remote_runner_service(
        cls,
        *,
        ssh_service,
        remote_release: str,
        remote_current: str,
        remote_config: str,
        remote_log: str,
        mode: str,
    ) -> None:
        if mode == "systemd_user":
            cls._run_checked(
                ssh_service,
                "mkdir -p ~/.config/systemd/user && cp {service} ~/.config/systemd/user/h2ometa-remote.service && systemctl --user daemon-reload && systemctl --user restart h2ometa-remote.service".format(
                    service=shlex.quote(f"{remote_release}/h2ometa-remote.service"),
                ),
                step="start remote runner service",
                timeout=60,
            )
            return
        cls._run_checked(
            ssh_service,
            "bash {start} {config} {log}".format(
                start=shlex.quote(f"{remote_current}/start_service.sh"),
                config=shlex.quote(remote_config),
                log=shlex.quote(remote_log),
            ),
            step="start remote runner service",
            timeout=30,
        )

    @classmethod
    def _write_remote_workflow_profile(
        cls,
        *,
        ssh_service,
        remote_profile_path: str,
        remote_profile_dir: str,
        remote_conda_prefix: str,
        bootstrap_metadata: dict[str, Any],
    ) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as handle:
            handle.write(build_remote_workflow_profile_content(conda_prefix=remote_conda_prefix))
            local_profile_path = Path(handle.name)
        try:
            cls._upload_remote_file_atomic(
                ssh_service,
                local_path=local_profile_path,
                remote_path=remote_profile_path,
                step="write workflow profile",
                timeout=10,
            )
        finally:
            try:
                local_profile_path.unlink(missing_ok=True)
            except OSError:
                pass
        profile_metadata = dict(bootstrap_metadata.get("workflow_profile") or {})
        profile_metadata["path"] = remote_profile_dir
        profile_metadata["config"] = remote_profile_path
        profile_metadata["conda_prefix"] = remote_conda_prefix
        profile_metadata["written"] = True
        bootstrap_metadata["workflow_profile"] = profile_metadata

    def _run_bootstrap_canary(
        self,
        *,
        client: RemoteRunnerHttpClient,
        server_id: str,
        bootstrap_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        canary = dict(bootstrap_metadata.get("canary") or {})
        canary.update(
            {
                "ok": False,
                "status": "running",
                "pipelineId": "file-summary-v1",
                "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "message": "",
            }
        )
        bootstrap_metadata["canary"] = canary
        try:
            fastq_bytes = b"@h2ometa-bootstrap-canary\nACGT\n+\n!!!!\n"
            upload = client.create_upload(
                filename="bootstrap-canary.fastq",
                content_base64=base64.b64encode(fastq_bytes).decode("ascii"),
                mime_type="application/octet-stream",
            )
            canary["upload"] = {
                "uploadId": str(upload.get("uploadId") or ""),
                "fileName": str(upload.get("fileName") or ""),
                "sizeBytes": int(upload.get("sizeBytes") or 0),
                "sha256": str(upload.get("sha256") or ""),
                "remotePath": str(upload.get("remotePath") or ""),
            }
            request_id = f"req_bootstrap_canary_{int(time.time() * 1000)}"
            submission = client.create_run(
                {
                    "serverId": server_id,
                    "requestId": request_id,
                    "runSpec": {
                        "pipelineId": "file-summary-v1",
                        "inputs": [
                            {
                                "uploadId": str(upload.get("uploadId") or ""),
                                "filename": str(upload.get("fileName") or "bootstrap-canary.fastq"),
                                "role": "reads",
                            }
                        ],
                        "params": {"threads": 1},
                    },
                },
                idempotency_key=f"idem_bootstrap_canary_{secrets.token_hex(8)}",
                request_id=request_id,
            )
            run_id = str(((submission.get("data") or {}).get("runId")) or "")
            if not run_id:
                raise RemoteRunnerManagerError("bootstrap canary submission did not return a runId")
            canary["submission"] = {
                "requestId": str(((submission.get("data") or {}).get("requestId")) or request_id),
                "runId": run_id,
                "status": str(((submission.get("data") or {}).get("status")) or ""),
                "stage": str(((submission.get("data") or {}).get("stage")) or ""),
                "message": str(((submission.get("data") or {}).get("message")) or ""),
            }
            run = self._wait_for_terminal_run(client, run_id=run_id)
            canary["run"] = {
                "runId": run_id,
                "status": str(run.get("status") or ""),
                "stage": str(run.get("stage") or ""),
                "message": str(run.get("message") or ""),
                "finishedAt": str(run.get("finishedAt") or ""),
                "lastError": run.get("lastError") if isinstance(run.get("lastError"), dict) else None,
            }
            if str(run.get("status") or "") != "completed":
                last_error = run.get("lastError") if isinstance(run.get("lastError"), dict) else {}
                detail = str(last_error.get("message") or run.get("message") or f"status={run.get('status') or 'unknown'}")
                raise RemoteRunnerManagerError(detail)
            run_results = client.get_run_results(run_id)
            listed_results = client.list_results()
            result_id = next((str(item.get("resultId") or "") for item in listed_results if str(item.get("runId") or "") == run_id), "")
            if not result_id:
                result_id = f"res_{run_id}"
            result_detail = client.get_result(result_id)
            artifacts = result_detail.get("artifacts") if isinstance(result_detail.get("artifacts"), list) else []
            if not artifacts:
                raise RemoteRunnerManagerError("bootstrap canary completed without artifacts")
            primary_artifact = artifacts[0]
            preview_payload = client.get_result_preview(result_id, artifact_id=str(primary_artifact.get("artifactId") or ""))
            canary["result"] = {
                "resultId": result_id,
                "resultDir": str(run_results.get("resultDir") or ""),
                "artifactCount": len(artifacts),
                "artifacts": [summarize_artifact(item) for item in artifacts[:3]],
            }
            canary["preview"] = compact_preview_payload(preview_payload)
            canary["ok"] = True
            canary["status"] = "passed"
            canary["message"] = "Bootstrap canary completed successfully."
            canary["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            bootstrap_metadata["canary"] = canary
            return canary
        except Exception as exc:
            detail = str(exc) or "bootstrap canary failed"
            canary["ok"] = False
            canary["status"] = "failed"
            canary["message"] = detail
            canary["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            bootstrap_metadata["canary"] = canary
            if isinstance(exc, RemoteRunnerManagerError):
                raise RemoteRunnerManagerError(
                    f"bootstrap canary failed: {detail}",
                    bootstrap_metadata=bootstrap_metadata,
                ) from exc
            raise RemoteRunnerManagerError(
                f"bootstrap canary failed: {detail}",
                bootstrap_metadata=bootstrap_metadata,
            ) from exc

    @staticmethod
    def _wait_for_terminal_run(
        client: RemoteRunnerHttpClient,
        *,
        run_id: str,
        attempts: int = 60,
        delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        last_run: dict[str, Any] | None = None
        for attempt in range(attempts):
            run = client.get_run(run_id)
            last_run = run
            if str(run.get("status") or "") in {"completed", "failed"}:
                return run
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
        if last_run is not None:
            raise RemoteRunnerManagerError(
                f"bootstrap canary run did not reach a terminal state: {str(last_run.get('status') or 'unknown')}"
            )
        raise RemoteRunnerManagerError("bootstrap canary run did not reach a terminal state")

    @classmethod
    def _attempt_release_rollback(
        cls,
        *,
        ssh_service,
        server_id: str,
        server_record: dict[str, Any],
        previous_version: str,
        previous_release: str,
        previous_mode: str,
        previous_config_path: Path | None,
        remote_current: str,
        remote_config: str,
        remote_log: str,
        remote_runtime_state: str,
        bootstrap_metadata: dict[str, Any],
        failure: str,
    ) -> None:
        rollback = dict(bootstrap_metadata.get("rollback") or {})
        rollback.update(
            {
                "attempted": True,
                "restored": False,
                "previous_release": previous_release,
                "previous_mode": previous_mode,
                "failure": str(failure or ""),
                "message": "",
            }
        )
        bootstrap_metadata["rollback"] = rollback
        target_release = str((bootstrap_metadata.get("release_switch") or {}).get("target_release") or "")
        if not previous_release or previous_release == target_release:
            rollback["message"] = "previous release unavailable for rollback"
            bootstrap_metadata["rollback"] = rollback
            return
        if previous_config_path is None or not previous_config_path.exists():
            rollback["message"] = "previous runner config unavailable for rollback"
            bootstrap_metadata["rollback"] = rollback
            return
        try:
            try:
                cls._run_checked(
                    ssh_service,
                    "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true; "
                    "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true; "
                    f"rm -f {shlex.quote(remote_runtime_state)}",
                    step="stop failed remote runner service before rollback",
                    timeout=20,
                )
            except RemoteRunnerManagerError as exc:
                rollback["stopError"] = str(exc)
            cls._upload_remote_file_atomic(
                ssh_service,
                local_path=previous_config_path,
                remote_path=remote_config,
                step="restore previous remote runner config",
                timeout=10,
            )
            cls._switch_current_release(
                ssh_service=ssh_service,
                target=previous_release,
                link_path=remote_current,
            )
            cls._start_remote_runner_service(
                ssh_service=ssh_service,
                remote_release=previous_release,
                remote_current=remote_current,
                remote_config=remote_config,
                remote_log=remote_log,
                mode=previous_mode or "background_process",
            )
            runtime_state = cls._wait_for_runtime_state(
                ssh_service=ssh_service,
                remote_runtime_state=remote_runtime_state,
                version=previous_version or REMOTE_RUNNER_VERSION,
            )
            rollback["runtimeState"] = {
                "bindPort": int(runtime_state.get("bindPort") or 0),
                "pid": int(runtime_state.get("pid") or 0),
                "version": str(runtime_state.get("version") or ""),
            }
            token = resolve_runner_token(str(server_record.get("token_ref") or ""))
            if token:
                tunnel = ssh_service.ensure_local_tunnel(
                    f"runner-{server_id}",
                    remote_host="127.0.0.1",
                    remote_port=int(runtime_state["bindPort"]),
                )
                client = RemoteRunnerHttpClient(
                    base_url=f"http://127.0.0.1:{tunnel.local_port}",
                    token=token,
                    timeout=5,
                )
                rollback["health"] = cls._wait_for_runner_health(client, attempts=3)
            rollback["restored"] = True
            rollback["message"] = "previous release restored"
            release_switch = dict(bootstrap_metadata.get("release_switch") or {})
            release_switch["active_release"] = previous_release
            release_switch["rolled_back"] = True
            bootstrap_metadata["release_switch"] = release_switch
        except Exception as exc:
            rollback["message"] = str(exc) or "rollback failed"
        bootstrap_metadata["rollback"] = rollback

    def _try_reuse_existing_runner_fast(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        version: str,
        remote_release: str,
        remote_current: str,
        remote_runtime_state: str,
        remote_config: str,
        remote_artifact_sha: str,
        artifact_sha: str,
        workflow_artifact: WorkflowRuntimeArtifact,
        workflow_runtime_dir: str,
        remote_workflow_artifact_sha: str,
        bootstrap_metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            if str(server_record.get("bootstrap_version") or "") != version:
                return self._reuse_failed(bootstrap_metadata, "bootstrap version mismatch")
            workflow_runtime = ((bootstrap_metadata.get("tooling") or {}).get("workflow_runtime") or {})
            if not workflow_runtime.get("snakemake_command") or not workflow_runtime.get("artifact_sha"):
                return self._reuse_failed(bootstrap_metadata, "workflow runtime metadata missing")
            token_ref = str(server_record.get("token_ref") or "").strip()
            token = resolve_runner_token(token_ref)
            if not token:
                return self._reuse_failed(bootstrap_metadata, "runner token not available")

            exit_code, stdout, _stderr = ssh_service.run(f"readlink -f {shlex.quote(remote_current)}", timeout=10)
            if exit_code != 0 or stdout.strip() != remote_release:
                return self._reuse_failed(bootstrap_metadata, "current release mismatch")

            manifest = self._read_remote_json(ssh_service, f"{remote_release}/bootstrap_manifest.json", "remote runner manifest")
            platform = str(
                ((bootstrap_metadata.get("preflight") or {}).get("platform"))
                or (((bootstrap_metadata.get("tooling") or {}).get("service_runtime") or {}).get("platform"))
                or ""
            )
            self._verify_remote_manifest_for_reuse(manifest, version=version, platform=platform)

            exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(remote_artifact_sha)}", timeout=10)
            if exit_code != 0:
                return self._reuse_failed(bootstrap_metadata, "artifact sha marker missing")
            if artifact_sha and stdout.strip() != artifact_sha:
                return self._reuse_failed(bootstrap_metadata, "artifact sha mismatch")

            exit_code, stdout, stderr = ssh_service.run(f"cat {shlex.quote(remote_runtime_state)}", timeout=10)
            if exit_code != 0:
                detail = stderr.strip() or stdout.strip() or "runtime state missing"
                return self._reuse_failed(bootstrap_metadata, detail)
            state = self._parse_runtime_state(stdout, version=version)
            self._verify_runtime_state_pid(ssh_service, state)
            self._verify_workflow_runtime_for_reuse(
                ssh_service=ssh_service,
                artifact=workflow_artifact,
                remote_dir=workflow_runtime_dir,
                remote_artifact_sha=remote_workflow_artifact_sha,
                remote_config=remote_config,
            )
            remote_port = int(state["bindPort"])
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
            health = self._wait_for_runner_health(client, attempts=2)
            self._verify_database_template_catalog_for_reuse(client)
            bootstrap_metadata["deployment_action"] = "reused"
            bootstrap_metadata["reuse_check"] = {"ok": True, "reason": ""}
            mark_reuse_bootstrap_phases_skipped(bootstrap_metadata)
            return {
                "bootstrap_version": version,
                "runner_mode": str(server_record.get("runner_mode") or "background_process"),
                "tunnel_port": tunnel.local_port,
                "token_ref": token_ref,
                "health": health,
                "service_port": remote_port,
                "bootstrap_metadata": bootstrap_metadata,
            }
        except Exception as exc:
            return self._reuse_failed(bootstrap_metadata, str(exc) or "reuse check failed")

    def _try_reuse_existing_runner(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        version: str,
        mode: str,
        remote_platform: str,
        remote_release: str,
        remote_current: str,
        remote_runtime_state: str,
        remote_artifact_sha: str,
        artifact_sha: str,
        remote_config: str,
        workflow_artifact: WorkflowRuntimeArtifact,
        workflow_runtime_dir: str,
        remote_workflow_artifact_sha: str,
        bootstrap_metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            token_ref = str(server_record.get("token_ref") or "").strip()
            token = resolve_runner_token(token_ref)
            if not token:
                return self._reuse_failed(bootstrap_metadata, "runner token not available")

            exit_code, stdout, _stderr = ssh_service.run(f"readlink -f {shlex.quote(remote_current)}", timeout=10)
            if exit_code != 0 or stdout.strip() != remote_release:
                return self._reuse_failed(bootstrap_metadata, "current release mismatch")

            manifest = self._read_remote_json(ssh_service, f"{remote_release}/bootstrap_manifest.json", "remote runner manifest")
            self._verify_remote_manifest(manifest, version=version, platform=remote_platform)

            exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(remote_artifact_sha)}", timeout=10)
            if exit_code != 0:
                return self._reuse_failed(bootstrap_metadata, "artifact sha marker missing")
            if stdout.strip() != artifact_sha:
                return self._reuse_failed(bootstrap_metadata, "artifact sha mismatch")

            exit_code, stdout, stderr = ssh_service.run(f"cat {shlex.quote(remote_runtime_state)}", timeout=10)
            if exit_code != 0:
                detail = stderr.strip() or stdout.strip() or "runtime state missing"
                return self._reuse_failed(bootstrap_metadata, detail)
            state = self._parse_runtime_state(stdout, version=version)
            self._verify_runtime_state_pid(ssh_service, state)
            self._verify_workflow_runtime_for_reuse(
                ssh_service=ssh_service,
                artifact=workflow_artifact,
                remote_dir=workflow_runtime_dir,
                remote_artifact_sha=remote_workflow_artifact_sha,
                remote_config=remote_config,
            )
            remote_port = int(state["bindPort"])
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
            health = self._wait_for_runner_health(client, attempts=2)
            self._verify_database_template_catalog_for_reuse(client)
            bootstrap_metadata["deployment_action"] = "reused"
            bootstrap_metadata["reuse_check"] = {"ok": True, "reason": ""}
            mark_reuse_bootstrap_phases_skipped(bootstrap_metadata)
            return {
                "bootstrap_version": version,
                "runner_mode": mode,
                "tunnel_port": tunnel.local_port,
                "token_ref": token_ref,
                "health": health,
                "service_port": remote_port,
                "bootstrap_metadata": bootstrap_metadata,
            }
        except Exception as exc:
            return self._reuse_failed(bootstrap_metadata, str(exc) or "reuse check failed")

    def _acquire_remote_install_lock(
        self,
        *,
        ssh_service,
        lock_dir: str,
        remote_root: str,
        bootstrap_metadata: dict[str, Any],
        attempts: int = 60,
        delay_seconds: float = 1.0,
    ) -> None:
        parent = f"{remote_root}/locks"
        command = (
            "mkdir -p {parent} && "
            "if mkdir {lock} 2>/dev/null; then "
            "printf acquired; "
            "else "
            "printf busy; "
            "fi"
        ).format(parent=shlex.quote(parent), lock=shlex.quote(lock_dir))
        bootstrap_metadata["install_lock"] = {"path": lock_dir, "acquired": False, "waited": False}
        for attempt in range(attempts):
            exit_code, stdout, stderr = ssh_service.run(command, timeout=10)
            if exit_code != 0:
                detail = stderr.strip() or stdout.strip() or "remote install lock check failed"
                raise RemoteRunnerManagerError(f"acquire remote install lock: {detail}")
            marker = stdout.strip()
            if marker == "acquired" or marker == "":
                bootstrap_metadata["install_lock"] = {
                    "path": lock_dir,
                    "acquired": True,
                    "waited": attempt > 0,
                }
                owner = {
                    "version": str(lock_dir).rsplit("/", 1)[-1],
                    "createdAt": int(time.time()),
                }
                quoted_owner = shlex.quote(json.dumps(owner, separators=(",", ":")))
                ssh_service.run(
                    f"printf %s {quoted_owner} > {shlex.quote(f'{lock_dir}/owner.json')}",
                    timeout=10,
                )
                return
            if marker != "busy":
                raise RemoteRunnerManagerError(f"acquire remote install lock: unexpected response {marker!r}")
            bootstrap_metadata["install_lock"]["waited"] = True
            reclaimed = self._reclaim_stale_install_lock(
                ssh_service=ssh_service,
                lock_dir=lock_dir,
            )
            if reclaimed:
                bootstrap_metadata["install_lock"]["stale_reclaimed"] = True
                continue
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
        raise RemoteRunnerManagerError(f"remote runner install lock is busy: {lock_dir}")

    @staticmethod
    def _reclaim_stale_install_lock(*, ssh_service, lock_dir: str, min_age_seconds: int = 120) -> bool:
        command = r"""
set -u
LOCK=$1
MIN_AGE=$2
if [ ! -d "$LOCK" ]; then
  printf missing
  exit 0
fi
if [ -f "$LOCK/owner.json" ]; then
  printf owned
  exit 0
fi
NOW=$(date +%s)
MTIME=$(stat -c %Y "$LOCK" 2>/dev/null || printf "$NOW")
AGE=$((NOW - MTIME))
if [ "$AGE" -lt "$MIN_AGE" ]; then
  printf young
  exit 0
fi
if ps -ef | grep -E 'remote_runner\.run|launch_remote_runner|h2ometa-remote-runner' | grep -v grep >/dev/null; then
  printf active
  exit 0
fi
rm -rf "$LOCK"
printf reclaimed
""".strip()
        exit_code, stdout, _stderr = ssh_service.run(
            "bash -s -- {lock} {age} <<'H2OMETA_RECLAIM_LOCK'\n{script}\nH2OMETA_RECLAIM_LOCK".format(
                lock=shlex.quote(lock_dir),
                age=shlex.quote(str(min_age_seconds)),
                script=command,
            ),
            timeout=15,
        )
        return exit_code == 0 and stdout.strip() == "reclaimed"

    @staticmethod
    def _release_remote_install_lock(*, ssh_service, lock_dir: str) -> None:
        try:
            ssh_service.run(f"rm -rf {shlex.quote(lock_dir)}", timeout=10)
        except Exception:
            return

    def _resolve_workflow_artifact_for_bootstrap(
        self,
        *,
        ssh_service,
        version: str,
        platform: str,
        remote_dir: str,
        remote_bundle: str,
    ) -> WorkflowRuntimeArtifact:
        try:
            return self._workflow_artifact_provider.resolve(version=version, platform=platform)
        except RemoteRunnerArtifactError as exc:
            if not allow_remote_workflow_runtime_registration():
                raise RemoteRunnerManagerError(workflow_runtime_artifact_required_message()) from exc
            return self._resolve_remote_workflow_artifact(
                ssh_service=ssh_service,
                version=version,
                platform=platform,
                remote_dir=remote_dir,
                remote_bundle=remote_bundle,
                local_error=str(exc),
            )

    @classmethod
    def _resolve_remote_workflow_artifact(
        cls,
        *,
        ssh_service,
        version: str,
        platform: str,
        remote_dir: str,
        remote_bundle: str,
        local_error: str,
    ) -> WorkflowRuntimeArtifact:
        manifest = cls._read_remote_json(ssh_service, f"{remote_dir}/bootstrap_manifest.json", "remote workflow runtime manifest")
        if str(manifest.get("service") or "") != "h2ometa-workflow-runtime":
            raise RemoteRunnerManagerError("remote workflow runtime manifest has unexpected service")
        if str(manifest.get("version") or "") != version:
            raise RemoteRunnerManagerError("remote workflow runtime manifest version mismatch")
        if str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerManagerError("remote workflow runtime manifest platform mismatch")
        if str(manifest.get("provider") or "") != "conda-pack":
            raise RemoteRunnerManagerError("remote workflow runtime manifest must declare conda-pack provider")
        packages = manifest.get("packages") if isinstance(manifest.get("packages"), dict) else {}
        if not str(packages.get("snakemake") or "").strip():
            raise RemoteRunnerManagerError("remote workflow runtime manifest must declare snakemake package version")

        sha256 = cls._read_remote_workflow_artifact_sha(
            ssh_service=ssh_service,
            remote_dir=remote_dir,
            remote_bundle=remote_bundle,
        )
        if not sha256:
            raise RemoteRunnerManagerError(
                "workflow runtime artifact unavailable locally and remote artifact checksum unavailable: "
                f"{local_error}"
            )

        entrypoints = manifest.get("entrypoints") if isinstance(manifest.get("entrypoints"), dict) else {}
        python_entrypoint = str(entrypoints.get("python") or "workflow-env/bin/python")
        snakemake_entrypoint = str(entrypoints.get("snakemake") or "workflow-env/bin/snakemake")
        conda_unpack_entrypoint = str(entrypoints.get("condaUnpack") or "workflow-env/bin/conda-unpack")
        conda_entrypoint = str(entrypoints.get("conda") or "workflow-env/bin/conda")
        for label, value in (
            ("python", python_entrypoint),
            ("snakemake", snakemake_entrypoint),
            ("condaUnpack", conda_unpack_entrypoint),
            ("conda", conda_entrypoint),
        ):
            if value.startswith("/") or ".." in Path(value).parts:
                raise RemoteRunnerManagerError(f"remote workflow runtime manifest has invalid {label} entrypoint")

        return WorkflowRuntimeArtifact(
            version=version,
            platform=platform,
            archive_path=Path(""),
            sha256=sha256,
            manifest=manifest,
            snakemake_entrypoint=snakemake_entrypoint,
            conda_unpack_entrypoint=conda_unpack_entrypoint,
            python_entrypoint=python_entrypoint,
            conda_entrypoint=conda_entrypoint,
        )

    @staticmethod
    def _read_remote_workflow_artifact_sha(*, ssh_service, remote_dir: str, remote_bundle: str) -> str:
        exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(f'{remote_dir}/artifact.sha256')}", timeout=10)
        if exit_code == 0 and stdout.strip():
            return stdout.strip()
        exit_code, stdout, _stderr = ssh_service.run(
            "test -f {bundle} && sha256sum {bundle}".format(bundle=shlex.quote(remote_bundle)),
            timeout=60,
        )
        if exit_code == 0 and stdout.strip():
            return stdout.strip().split(maxsplit=1)[0]
        return ""

    @classmethod
    def _verify_workflow_runtime_for_reuse(
        cls,
        *,
        ssh_service,
        artifact: WorkflowRuntimeArtifact,
        remote_dir: str,
        remote_artifact_sha: str,
        remote_config: str,
    ) -> None:
        expected = cls._build_workflow_runtime_metadata(artifact=artifact, remote_dir=remote_dir)
        exit_code, stdout, stderr = ssh_service.run(f"cat {shlex.quote(remote_artifact_sha)}", timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or "workflow runtime artifact marker missing"
            raise RemoteRunnerManagerError(detail)
        if stdout.strip() != artifact.sha256:
            raise RemoteRunnerManagerError("workflow runtime artifact sha mismatch")

        config = cls._read_remote_json(ssh_service, remote_config, "remote runner config")
        expected_config = {
            "managed_conda_command": str(expected.get("command") or ""),
            "managed_conda_root_prefix": str(expected.get("root_prefix") or ""),
            "workflow_runtime_provider": str(expected.get("provider") or ""),
            "workflow_runtime_source": str(expected.get("source") or ""),
            "workflow_runtime_version": str(expected.get("version") or ""),
            "snakemake_command": str(expected.get("snakemake_command") or ""),
            "snakemake_version": str(expected.get("snakemake_version") or ""),
        }
        for key, value in expected_config.items():
            if str(config.get(key) or "") != value:
                raise RemoteRunnerManagerError(f"workflow runtime config mismatch: {key}")

        cls._verify_workflow_runtime_command(
            ssh_service,
            cls._workflow_runtime_command(
                python_command=str(expected["python"]),
                snakemake_command=str(expected["snakemake_command"]),
                conda_command=str(expected["command"]),
            ),
        )

    def _ensure_workflow_runtime(
        self,
        *,
        ssh_service,
        artifact: WorkflowRuntimeArtifact,
        remote_bundle: str,
        remote_dir: str,
        remote_artifact_sha: str,
        bootstrap_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        runtime = self._build_workflow_runtime_metadata(artifact=artifact, remote_dir=remote_dir)
        workflow_metadata = {"action": "reused", "path": remote_dir, "artifact_sha": artifact.sha256}
        exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(remote_artifact_sha)}", timeout=10)
        reusable = exit_code == 0 and stdout.strip() == artifact.sha256
        runtime_verified = False
        if reusable:
            try:
                self._verify_workflow_runtime_command(
                    ssh_service,
                    self._workflow_runtime_command(
                        python_command=str(runtime["python"]),
                        snakemake_command=str(runtime["snakemake_command"]),
                        conda_command=str(runtime["command"]),
                    ),
                )
                runtime_verified = True
            except RemoteRunnerManagerError:
                reusable = False
                workflow_metadata["action"] = "reinstalled"
        if not reusable:
            if allow_remote_workflow_runtime_registration() and self._can_register_existing_workflow_runtime(ssh_service=ssh_service, runtime=runtime):
                workflow_metadata["action"] = "registered"
                runtime_verified = True
            else:
                if workflow_metadata["action"] != "reinstalled":
                    workflow_metadata["action"] = "installed"
                if not self._remote_file_has_sha256(
                    ssh_service=ssh_service,
                    path=remote_bundle,
                    sha256=artifact.sha256,
                ):
                    if not artifact.archive_path or not artifact.archive_path.exists():
                        raise RemoteRunnerManagerError(
                            "workflow runtime artifact unavailable locally and remote bundle is missing or has the wrong checksum"
                        )
                    ssh_service.upload(str(artifact.archive_path), remote_bundle)
                self._extract_workflow_runtime(
                    ssh_service=ssh_service,
                    remote_bundle=remote_bundle,
                    remote_dir=remote_dir,
                    runtime=runtime,
                )
        if not runtime_verified:
            self._verify_workflow_runtime_command(
                ssh_service,
                self._workflow_runtime_command(
                    python_command=str(runtime["python"]),
                    snakemake_command=str(runtime["snakemake_command"]),
                    conda_command=str(runtime["command"]),
                ),
            )
            runtime_verified = True
        if not reusable:
            self._write_remote_text_atomic(
                ssh_service,
                path=remote_artifact_sha,
                content=artifact.sha256,
                step="write workflow runtime artifact marker",
                timeout=10,
            )
            self._cleanup_remote_bundle(
                ssh_service,
                remote_bundle,
                step="cleanup workflow runtime bundle",
            )
        tooling = bootstrap_metadata.setdefault("tooling", {})
        tooling["workflow_runtime"] = runtime
        bootstrap_metadata["workflow_runtime"] = workflow_metadata
        return runtime

    @classmethod
    def _can_register_existing_workflow_runtime(cls, *, ssh_service, runtime: dict[str, Any]) -> bool:
        try:
            cls._verify_workflow_runtime_command(
                ssh_service,
                cls._workflow_runtime_command(
                    python_command=str(runtime["python"]),
                    snakemake_command=str(runtime["snakemake_command"]),
                    conda_command=str(runtime["command"]),
                ),
            )
            return True
        except RemoteRunnerManagerError:
            return False

    @classmethod
    def _extract_workflow_runtime(
        cls,
        *,
        ssh_service,
        remote_bundle: str,
        remote_dir: str,
        runtime: dict[str, Any],
    ) -> None:
        cls._run_checked(
            ssh_service,
            "rm -rf {runtime_dir} && mkdir -p {runtime_dir} && tar -xzf {bundle} -C {runtime_dir}".format(
                runtime_dir=shlex.quote(remote_dir),
                bundle=shlex.quote(remote_bundle),
            ),
            step="extract workflow runtime artifact",
            timeout=180,
        )
        cls._run_checked(
            ssh_service,
            "if [ -x {conda_unpack} ] && [ ! -f {marker} ]; then {python} {conda_unpack}; touch {marker}; fi".format(
                conda_unpack=shlex.quote(str(runtime["conda_unpack"])),
                marker=shlex.quote(f"{remote_dir}/.h2ometa-conda-unpacked"),
                python=shlex.quote(str(runtime["python"])),
            ),
            step="relocate workflow runtime",
            timeout=120,
        )

    @staticmethod
    def _remote_file_has_sha256(*, ssh_service, path: str, sha256: str) -> bool:
        command = "test -f {path} && sha256sum {path}".format(path=shlex.quote(path))
        exit_code, stdout, _stderr = ssh_service.run(command, timeout=60)
        digest = stdout.strip().split(maxsplit=1)[0] if stdout.strip() else ""
        return exit_code == 0 and digest == sha256

    @staticmethod
    def _workflow_runtime_command(*, python_command: str, snakemake_command: str, conda_command: str) -> str:
        path_entries = [
            str(PurePosixPath(snakemake_command).parent),
            str(PurePosixPath(conda_command).parent),
        ]
        path_prefix = ":".join(shlex.quote(entry) for entry in dict.fromkeys(path_entries) if entry)
        return "PATH={path_prefix}:$PATH {python} -c 'import snakemake' && PATH={path_prefix}:$PATH {snakemake} --version".format(
            path_prefix=path_prefix,
            python=shlex.quote(python_command),
            snakemake=shlex.quote(snakemake_command),
        )

    @classmethod
    def _verify_workflow_runtime_command(cls, ssh_service, cmd: str) -> tuple[int, str, str]:
        last_error: RemoteRunnerManagerError | None = None
        for attempt in range(5):
            try:
                return cls._run_checked(
                    ssh_service,
                    cmd,
                    step="verify workflow runtime snakemake",
                    timeout=30,
                )
            except RemoteRunnerManagerError as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(1)
        if last_error is not None:
            raise last_error
        raise RemoteRunnerManagerError("verify workflow runtime snakemake failed")

    @staticmethod
    def _verify_remote_manifest(manifest: dict[str, Any], *, version: str, platform: str) -> None:
        if str(manifest.get("service") or "") != "h2ometa-remote":
            raise RemoteRunnerManagerError("remote runner manifest has unexpected service")
        if str(manifest.get("version") or "") != version:
            raise RemoteRunnerManagerError("remote runner manifest version mismatch")
        if str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerManagerError("remote runner manifest platform mismatch")
        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        if str(runtime.get("provider") or "") != "bundled" or str(runtime.get("python") or "") != "runtime/bin/python":
            raise RemoteRunnerManagerError("remote runner manifest does not declare bundled runtime")

    @staticmethod
    def _verify_remote_manifest_for_reuse(manifest: dict[str, Any], *, version: str, platform: str) -> None:
        if str(manifest.get("service") or "") != "h2ometa-remote":
            raise RemoteRunnerManagerError("remote runner manifest has unexpected service")
        if str(manifest.get("version") or "") != version:
            raise RemoteRunnerManagerError("remote runner manifest version mismatch")
        if platform and str(manifest.get("platform") or "") != platform:
            raise RemoteRunnerManagerError("remote runner manifest platform mismatch")
        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        if str(runtime.get("provider") or "") != "bundled" or str(runtime.get("python") or "") != "runtime/bin/python":
            raise RemoteRunnerManagerError("remote runner manifest does not declare bundled runtime")

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
            "db_path",
            "runtime_state_path",
            "release_dir",
            "runner_python",
            "managed_conda_command",
            "managed_conda_root_prefix",
            "workflow_runtime_provider",
            "workflow_runtime_source",
            "workflow_runtime_version",
            "snakemake_command", "snakemake_version",
            "workflow_profile_dir",
            "workflow_profile_name",
        )
        for key in required_keys:
            if actual.get(key) != expected.get(key):
                raise RemoteRunnerManagerError(f"remote runner config verification failed: {key}")

    @staticmethod
    def _require_service_port(record: dict[str, Any]) -> int:
        raw = record.get("service_port")
        try:
            port = int(raw)
        except (TypeError, ValueError) as exc:
            raise RemoteRunnerManagerError("remote runner service_port is missing; bootstrap did not complete") from exc
        if port <= 0 or port > 65535:
            raise RemoteRunnerManagerError("remote runner service_port is invalid; bootstrap did not complete")
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
    def _read_current_release_target(ssh_service, remote_current: str) -> str:
        exit_code, stdout, _stderr = ssh_service.run(f"readlink -f {shlex.quote(remote_current)}", timeout=10)
        if exit_code != 0:
            return ""
        return stdout.strip()
