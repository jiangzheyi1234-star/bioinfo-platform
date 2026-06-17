from __future__ import annotations

import base64
import secrets
import shlex
import tempfile
import time
from pathlib import Path
from typing import Any

from config import resolve_runner_token
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient
from core.remote_runner.metadata import (
    build_remote_workflow_profile_content,
    compact_preview_payload,
    summarize_artifact,
)


class RemoteRunnerBootstrapActivationMixin:
    _manager_error: type[Exception]

    @classmethod
    def _bootstrap_failure(cls, detail: str, *, bootstrap_metadata: dict[str, Any]):
        message = str(detail or "remote runner bootstrap failed").strip() or "remote runner bootstrap failed"
        rollback = bootstrap_metadata.get("rollback") if isinstance(bootstrap_metadata, dict) else None
        if isinstance(rollback, dict) and bool(rollback.get("attempted")):
            outcome = "rollback restored previous release" if bool(rollback.get("restored")) else "rollback did not restore previous release"
            rollback_message = str(rollback.get("message") or "").strip()
            if rollback_message:
                message = f"{message}; {outcome}: {rollback_message}"
            else:
                message = f"{message}; {outcome}"
        return cls._manager_error(message, bootstrap_metadata=bootstrap_metadata)

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
        remote_wrapper_prefix: str,
        bootstrap_metadata: dict[str, Any],
    ) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".yaml", encoding="utf-8") as handle:
            handle.write(
                build_remote_workflow_profile_content(
                    conda_prefix=remote_conda_prefix,
                    wrapper_prefix=remote_wrapper_prefix,
                )
            )
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
            local_profile_path.unlink(missing_ok=True)
        profile_metadata = dict(bootstrap_metadata.get("workflow_profile") or {})
        profile_metadata["path"] = remote_profile_dir
        profile_metadata["config"] = remote_profile_path
        profile_metadata["conda_prefix"] = remote_conda_prefix
        profile_metadata["wrapper_prefix"] = remote_wrapper_prefix
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
                raise self._manager_error("bootstrap canary submission did not return a runId")
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
                raise self._manager_error(detail)
            run_results = client.get_run_results(run_id)
            listed_results = client.list_results()
            result_id = next((str(item.get("resultId") or "") for item in listed_results if str(item.get("runId") or "") == run_id), "")
            if not result_id:
                result_id = f"res_{run_id}"
            result_detail = client.get_result(result_id)
            artifacts = result_detail.get("artifacts") if isinstance(result_detail.get("artifacts"), list) else []
            if not artifacts:
                raise self._manager_error("bootstrap canary completed without artifacts")
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
        except (self._manager_error, RemoteRunnerClientError) as exc:
            detail = str(exc) or "bootstrap canary failed"
            canary["ok"] = False
            canary["status"] = "failed"
            canary["message"] = detail
            canary["completedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            bootstrap_metadata["canary"] = canary
            raise self._manager_error(
                f"bootstrap canary failed: {detail}",
                bootstrap_metadata=bootstrap_metadata,
            ) from exc

    @staticmethod
    def _canary_failure_needs_fresh_tunnel_retry(detail: str) -> bool:
        lowered = str(detail or "").lower()
        return (
            "connection refused" in lowered
            or "actively refused" in lowered
            or "无法连接" in lowered
            or "10054" in lowered
            or "强迫关闭" in lowered
            or "forcibly closed" in lowered
            or "runner unreachable" in lowered
        )

    @classmethod
    def _wait_for_terminal_run(
        cls,
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
            raise cls._manager_error(
                f"bootstrap canary run did not reach a terminal state: {str(last_run.get('status') or 'unknown')}"
            )
        raise cls._manager_error("bootstrap canary run did not reach a terminal state")

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
            except cls._manager_error as exc:
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
        except (cls._manager_error, RemoteRunnerClientError) as exc:
            rollback["message"] = str(exc) or "rollback failed"
        bootstrap_metadata["rollback"] = rollback
