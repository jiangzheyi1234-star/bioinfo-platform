from __future__ import annotations

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
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient


class RemoteRunnerManagerError(RuntimeError):
    pass


class RemoteRunnerManager:
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
            remote_runtime_state = f"{remote_shared}/runtime/runner-state.json"
            remote_log = f"{remote_shared}/logs/runner.log"
            remote_current = f"{remote_root}/current"
            remote_artifact_sha = f"{remote_release}/artifact.sha256"
            remote_tools = f"{remote_root}/tools"
            remote_install_lock = f"{remote_root}/locks/install-{version}.lock"
            requested_remote_port = 0
            remote_service_python = f"{remote_release}/runtime/bin/python"
            fast_platform = self._platform_from_metadata(server_record) or "linux-64"
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

            fast_reuse_metadata = self._build_fast_reuse_metadata(
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
            remote_platform = self._detect_remote_platform(ssh_service)
            artifact = self._artifact_provider.resolve(version=version, platform=remote_platform)
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
            workflow_runtime = self._build_workflow_runtime_metadata(
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
                "deployment_action": "installed",
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
                if mode == "systemd_user":
                    self._run_checked(
                        ssh_service,
                        "mkdir -p ~/.config/systemd/user && cp {service} ~/.config/systemd/user/h2ometa-remote.service && {switch_current} && systemctl --user daemon-reload && systemctl --user restart h2ometa-remote.service".format(
                            service=shlex.quote(f"{remote_release}/h2ometa-remote.service"),
                            switch_current=self._atomic_symlink_command(
                                target=remote_release,
                                link_path=remote_current,
                            ),
                        ),
                        step="start remote runner service",
                        timeout=60,
                    )
                else:
                    self._run_checked(
                        ssh_service,
                        "{switch_current} && bash {start} {config} {log}".format(
                            switch_current=self._atomic_symlink_command(
                                target=remote_release,
                                link_path=remote_current,
                            ),
                            start=shlex.quote(f"{remote_current}/start_service.sh"),
                            config=shlex.quote(remote_config),
                            log=shlex.quote(remote_log),
                        ),
                        step="start remote runner service",
                        timeout=30,
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
                self._release_remote_install_lock(ssh_service=ssh_service, lock_dir=remote_install_lock)
        except RemoteRunnerManagerError:
            raise
        except RemoteRunnerArtifactError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc
        except Exception as exc:
            raise RemoteRunnerManagerError(str(exc) or "remote runner bootstrap failed") from exc

    @staticmethod
    def _build_fast_reuse_metadata(
        *,
        server_record: dict[str, Any],
        version: str,
        remote_service_python: str,
    ) -> dict[str, Any]:
        metadata = dict(server_record.get("bootstrap_metadata") or {})
        preflight = dict(metadata.get("preflight") or {})
        tooling = dict(metadata.get("tooling") or {})
        service_runtime = dict(tooling.get("service_runtime") or {})
        workflow_runtime = dict(tooling.get("workflow_runtime") or {})
        runner_mode = str(server_record.get("runner_mode") or "")
        platform = str(preflight.get("platform") or service_runtime.get("platform") or "")
        if runner_mode:
            preflight["launcher"] = {"mode": runner_mode}
        if platform:
            preflight["platform"] = platform
        service_runtime = {
            **service_runtime,
            "provider": "bundled",
            "source": "artifact",
            "python": str(service_runtime.get("python") or remote_service_python),
        }
        if platform:
            service_runtime["platform"] = platform
        tooling["service_runtime"] = service_runtime
        if workflow_runtime:
            tooling["workflow_runtime"] = workflow_runtime
        metadata["preflight"] = preflight
        metadata["tooling"] = tooling
        return metadata

    @staticmethod
    def _platform_from_metadata(server_record: dict[str, Any]) -> str:
        metadata = dict(server_record.get("bootstrap_metadata") or {})
        preflight = dict(metadata.get("preflight") or {})
        tooling = dict(metadata.get("tooling") or {})
        service_runtime = dict(tooling.get("service_runtime") or {})
        return str(preflight.get("platform") or service_runtime.get("platform") or "").strip()

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
            bootstrap_metadata["deployment_action"] = "reused"
            bootstrap_metadata["reuse_check"] = {"ok": True, "reason": ""}
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
            bootstrap_metadata["deployment_action"] = "reused"
            bootstrap_metadata["reuse_check"] = {"ok": True, "reason": ""}
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
                return
            if marker != "busy":
                raise RemoteRunnerManagerError(f"acquire remote install lock: unexpected response {marker!r}")
            bootstrap_metadata["install_lock"]["waited"] = True
            if attempt < attempts - 1:
                time.sleep(delay_seconds)
        raise RemoteRunnerManagerError(f"remote runner install lock is busy: {lock_dir}")

    @staticmethod
    def _release_remote_install_lock(*, ssh_service, lock_dir: str) -> None:
        try:
            ssh_service.run(f"rm -rf {shlex.quote(lock_dir)}", timeout=10)
        except Exception:
            return

    @classmethod
    def _write_remote_text_atomic(
        cls,
        ssh_service,
        *,
        path: str,
        content: str,
        step: str,
        timeout: int,
    ) -> None:
        tmp_path = f"{path}.tmp"
        quoted_content = shlex.quote(content)
        quoted_tmp = shlex.quote(tmp_path)
        quoted_path = shlex.quote(path)
        cls._run_checked(
            ssh_service,
            "printf %s {content} > {tmp} && test -s {tmp} && mv -f {tmp} {path}".format(
                content=quoted_content,
                tmp=quoted_tmp,
                path=quoted_path,
            ),
            step=step,
            timeout=timeout,
        )

    @classmethod
    def _upload_remote_file_atomic(
        cls,
        ssh_service,
        *,
        local_path: Path,
        remote_path: str,
        step: str,
        timeout: int,
    ) -> None:
        tmp_path = f"{remote_path}.tmp"
        ssh_service.upload(str(local_path), tmp_path)
        cls._run_checked(
            ssh_service,
            "test -s {tmp} && mv -f {tmp} {path}".format(
                tmp=shlex.quote(tmp_path),
                path=shlex.quote(remote_path),
            ),
            step=step,
            timeout=timeout,
        )

    @staticmethod
    def _atomic_symlink_command(*, target: str, link_path: str) -> str:
        tmp_link = f"{link_path}.tmp"
        return (
            "rm -f {tmp} && "
            "ln -sfn {target} {tmp} && "
            "test -L {tmp} && "
            "mv -Tf {tmp} {link}"
        ).format(
            target=shlex.quote(target),
            tmp=shlex.quote(tmp_link),
            link=shlex.quote(link_path),
        )

    @classmethod
    def _cleanup_remote_bundle(cls, ssh_service, path: str, *, step: str) -> None:
        cls._run_checked(
            ssh_service,
            f"rm -f {shlex.quote(path)}",
            step=step,
            timeout=10,
        )

    @staticmethod
    def _reuse_failed(bootstrap_metadata: dict[str, Any], reason: str) -> None:
        bootstrap_metadata["reuse_check"] = {"ok": False, "reason": reason}
        return None

    @staticmethod
    def _build_workflow_runtime_metadata(*, artifact: WorkflowRuntimeArtifact, remote_dir: str) -> dict[str, Any]:
        packages = artifact.manifest.get("packages") if isinstance(artifact.manifest.get("packages"), dict) else {}
        snakemake_version = str(packages.get("snakemake") or "")
        return {
            "provider": "conda-pack",
            "source": "artifact",
            "version": artifact.version,
            "platform": artifact.platform,
            "artifact_sha": artifact.sha256,
            "root": remote_dir,
            "python": f"{remote_dir}/{artifact.python_entrypoint}",
            "command": f"{remote_dir}/{artifact.conda_entrypoint}",
            "root_prefix": f"{remote_dir}/micromamba-root",
            "conda_unpack": f"{remote_dir}/{artifact.conda_unpack_entrypoint}",
            "snakemake_command": f"{remote_dir}/{artifact.snakemake_entrypoint}",
            "snakemake_version": snakemake_version,
        }

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
            if self._can_register_existing_workflow_runtime(ssh_service=ssh_service, runtime=runtime):
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

    @classmethod
    def _read_remote_json(cls, ssh_service, path: str, label: str) -> dict[str, Any]:
        exit_code, stdout, stderr = ssh_service.run(f"cat {shlex.quote(path)}", timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or f"{label} not readable"
            raise RemoteRunnerManagerError(detail)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RemoteRunnerManagerError(f"{label} is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise RemoteRunnerManagerError(f"{label} is not an object")
        return payload

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
            "snakemake_command",
        )
        for key in required_keys:
            if actual.get(key) != expected.get(key):
                raise RemoteRunnerManagerError(f"remote runner config verification failed: {key}")

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

    def list_pipelines(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/pipelines")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def get_pipeline(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json(f"/api/v1/pipelines/{kwargs['pipeline_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def list_tools(self, **kwargs) -> list[dict[str, Any]]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.get_json("/api/v1/tools")["data"]["items"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def add_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json("/api/v1/tools", kwargs["payload"])["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def delete_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.delete_json(f"/api/v1/tools/{kwargs['tool_id']}")["data"]
        except RemoteRunnerClientError as exc:
            raise RemoteRunnerManagerError(str(exc)) from exc

    def check_tool(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        try:
            return client.post_json(f"/api/v1/tools/{kwargs['tool_id']}/check", {})["data"]
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
        except RemoteRunnerManagerError:
            raise
        except Exception as exc:
            raise RemoteRunnerManagerError(str(exc) or "runner token rotation failed") from exc

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any]) -> RemoteRunnerHttpClient:
        try:
            token = resolve_runner_token(str(record.get("token_ref", "") or ""))
            if not token:
                raise RemoteRunnerManagerError("runner token not available")
            remote_port = self._require_service_port(record)
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
    def _build_remote_config_payload(
        *,
        version: str,
        mode: str,
        remote_port: int,
        token: str,
        remote_shared: str,
        remote_release: str,
        remote_runtime_state: str,
        runner_python: str,
        managed_conda_command: str,
        managed_conda_root_prefix: str,
        workflow_runtime_provider: str,
        workflow_runtime_source: str,
        workflow_runtime_version: str,
        snakemake_command: str,
        snakemake_version: str,
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
            "runtime_state_path": remote_runtime_state,
            "uploads_dir": f"{remote_shared}/uploads",
            "results_dir": f"{remote_shared}/results",
            "work_dir": f"{remote_shared}/work",
            "logs_dir": f"{remote_shared}/logs",
            "release_dir": f"{remote_release}/remote_runner",
            "runner_python": runner_python,
            "managed_conda_command": managed_conda_command,
            "managed_conda_root_prefix": managed_conda_root_prefix,
            "workflow_runtime_provider": workflow_runtime_provider,
            "workflow_runtime_source": workflow_runtime_source,
            "workflow_runtime_version": workflow_runtime_version,
            "snakemake_command": snakemake_command,
            "snakemake_version": snakemake_version,
        }

    @classmethod
    def _wait_for_runtime_state(
        cls,
        *,
        ssh_service,
        remote_runtime_state: str,
        version: str,
        attempts: int = 8,
        delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        last_error = "remote runner state not available"
        for attempt in range(attempts):
            exit_code, stdout, stderr = ssh_service.run(
                f"cat {shlex.quote(remote_runtime_state)}",
                timeout=10,
            )
            if exit_code == 0:
                try:
                    state = cls._parse_runtime_state(stdout, version=version)
                    cls._verify_runtime_state_pid(ssh_service, state)
                    return state
                except RemoteRunnerManagerError as exc:
                    last_error = str(exc)
            else:
                last_error = stderr.strip() or stdout.strip() or last_error
            if attempt != attempts - 1:
                time.sleep(delay_seconds)
        raise RemoteRunnerManagerError(f"remote runner runtime state unavailable: {last_error}")

    @staticmethod
    def _parse_runtime_state(raw: str, *, version: str) -> dict[str, Any]:
        try:
            state = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RemoteRunnerManagerError("remote runner runtime state is invalid JSON") from exc
        if not isinstance(state, dict):
            raise RemoteRunnerManagerError("remote runner runtime state is not an object")
        if str(state.get("service") or "") != "h2ometa-remote":
            raise RemoteRunnerManagerError("remote runner runtime state has unexpected service")
        if str(state.get("version") or "") != version:
            raise RemoteRunnerManagerError("remote runner runtime state has unexpected version")
        if str(state.get("bindHost") or "") != "127.0.0.1":
            raise RemoteRunnerManagerError("remote runner runtime state has unexpected bind host")
        try:
            port = int(state.get("bindPort"))
        except (TypeError, ValueError) as exc:
            raise RemoteRunnerManagerError("remote runner runtime state has invalid bind port") from exc
        if port <= 0 or port > 65535:
            raise RemoteRunnerManagerError("remote runner runtime state has invalid bind port")
        state["bindPort"] = port
        return state

    @staticmethod
    def _verify_runtime_state_pid(ssh_service, state: dict[str, Any]) -> None:
        try:
            pid = int(state.get("pid"))
        except (TypeError, ValueError) as exc:
            raise RemoteRunnerManagerError("remote runner runtime state has invalid pid") from exc
        if pid <= 0:
            raise RemoteRunnerManagerError("remote runner runtime state has invalid pid")
        exit_code, _stdout, stderr = ssh_service.run(f"kill -0 {pid}", timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or f"pid {pid}"
            raise RemoteRunnerManagerError(f"remote runner process is not running: {detail}")

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
