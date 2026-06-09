from __future__ import annotations

import shlex
from typing import Any

from config import resolve_runner_token
from core.remote_runner.artifact import WorkflowRuntimeArtifact
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.metadata import mark_reuse_bootstrap_phases_skipped


class RemoteRunnerReuseMixin:
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
            self._refresh_reuse_workflow_runtime_metadata(
                bootstrap_metadata=bootstrap_metadata,
                workflow_artifact=workflow_artifact,
                workflow_runtime_dir=workflow_runtime_dir,
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
        except (RemoteRunnerManagerError, RemoteRunnerClientError) as exc:
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
            self._refresh_reuse_workflow_runtime_metadata(
                bootstrap_metadata=bootstrap_metadata,
                workflow_artifact=workflow_artifact,
                workflow_runtime_dir=workflow_runtime_dir,
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
        except (RemoteRunnerManagerError, RemoteRunnerClientError) as exc:
            return self._reuse_failed(bootstrap_metadata, str(exc) or "reuse check failed")

    def _refresh_reuse_workflow_runtime_metadata(
        self,
        *,
        bootstrap_metadata: dict[str, Any],
        workflow_artifact: WorkflowRuntimeArtifact,
        workflow_runtime_dir: str,
    ) -> None:
        runtime = self._build_workflow_runtime_metadata(
            artifact=workflow_artifact,
            remote_dir=workflow_runtime_dir,
        )
        tooling = dict(bootstrap_metadata.get("tooling") or {})
        tooling["workflow_runtime"] = runtime
        bootstrap_metadata["tooling"] = tooling
        bootstrap_metadata["workflow_runtime"] = {
            "action": "reused",
            "path": workflow_runtime_dir,
            "artifact_sha": workflow_artifact.sha256,
        }
