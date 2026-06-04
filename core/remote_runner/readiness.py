from __future__ import annotations

import json
import shlex
import time
from typing import Any

from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerHttpClient


class RemoteRunnerReadinessMixin:
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
                except RuntimeError as exc:
                    last_error = str(exc)
            else:
                last_error = stderr.strip() or stdout.strip() or last_error
            if attempt != attempts - 1:
                time.sleep(delay_seconds)
        raise cls._manager_error(f"remote runner runtime state unavailable: {last_error}")

    @classmethod
    def _parse_runtime_state(cls, raw: str, *, version: str) -> dict[str, Any]:
        try:
            state = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise cls._manager_error("remote runner runtime state is invalid JSON") from exc
        if not isinstance(state, dict):
            raise cls._manager_error("remote runner runtime state is not an object")
        if str(state.get("service") or "") != "h2ometa-remote":
            raise cls._manager_error("remote runner runtime state has unexpected service")
        if str(state.get("version") or "") != version:
            raise cls._manager_error("remote runner runtime state has unexpected version")
        if str(state.get("bindHost") or "") != "127.0.0.1":
            raise cls._manager_error("remote runner runtime state has unexpected bind host")
        try:
            port = int(state.get("bindPort"))
        except (TypeError, ValueError) as exc:
            raise cls._manager_error("remote runner runtime state has invalid bind port") from exc
        if port <= 0 or port > 65535:
            raise cls._manager_error("remote runner runtime state has invalid bind port")
        state["bindPort"] = port
        return state

    @classmethod
    def _verify_runtime_state_pid(cls, ssh_service, state: dict[str, Any]) -> None:
        try:
            pid = int(state.get("pid"))
        except (TypeError, ValueError) as exc:
            raise cls._manager_error("remote runner runtime state has invalid pid") from exc
        if pid <= 0:
            raise cls._manager_error("remote runner runtime state has invalid pid")
        exit_code, _stdout, stderr = ssh_service.run(f"kill -0 {pid}", timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or f"pid {pid}"
            raise cls._manager_error(f"remote runner process is not running: {detail}")

    @classmethod
    def _wait_for_runner_health(
        cls,
        client: RemoteRunnerHttpClient,
        *,
        attempts: int = 8,
        delay_seconds: float = 1.0,
    ) -> dict[str, Any]:
        last_error = "remote runner health check failed"
        for attempt in range(attempts):
            try:
                health = client.get_health()
            except RemoteRunnerClientError as exc:
                last_error = str(exc) or last_error
            else:
                ready_error = cls._ready_health_error(health)
                if not ready_error:
                    return health
                last_error = ready_error
            if attempt != attempts - 1:
                time.sleep(delay_seconds)
        raise cls._manager_error(last_error)

    @classmethod
    def _require_ready_health(cls, health: dict[str, Any]) -> None:
        ready_error = cls._ready_health_error(health)
        if ready_error:
            raise cls._manager_error(ready_error)

    @classmethod
    def _ready_health_error(cls, health: dict[str, Any]) -> str:
        ready = health.get("ready") if isinstance(health, dict) else None
        if not isinstance(ready, dict) or bool(ready.get("ok")):
            return ""
        return cls._describe_not_ready_health(health)

    @staticmethod
    def _describe_not_ready_health(health: dict[str, Any]) -> str:
        if not isinstance(health, dict):
            return "remote runner control plane is not ready"
        detail_parts: list[str] = []
        workflow = health.get("workflowRuntime")
        if isinstance(workflow, dict) and not bool(workflow.get("ok")):
            detail_parts.append(
                f"workflow runtime not ready: {str(workflow.get('message') or 'Workflow runtime is not ready.').strip()}"
            )
        pipeline_registry = health.get("pipelineRegistry")
        if isinstance(pipeline_registry, dict) and not bool(pipeline_registry.get("ok")):
            detail_parts.append(
                f"pipeline registry not ready: {str(pipeline_registry.get('message') or 'Pipeline registry is not ready.').strip()}"
            )
        ready = health.get("ready")
        ready_message = ""
        if isinstance(ready, dict):
            ready_message = str(ready.get("message") or "").strip()
        if ready_message and ready_message not in detail_parts:
            detail_parts.append(ready_message)
        return "; ".join(part for part in detail_parts if part) or "remote runner control plane is not ready"

    @classmethod
    def _verify_database_template_catalog_for_reuse(cls, client: RemoteRunnerHttpClient) -> None:
        payload = client.get_json("/api/v1/database-templates")
        data = payload.get("data") if isinstance(payload, dict) else None
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise cls._manager_error("runner database template catalog payload is invalid")
        for item in items:
            if not isinstance(item, dict):
                raise cls._manager_error("runner database template catalog item is invalid")
            for field in ("category", "pathLabel", "runtimeValue"):
                if not str(item.get(field) or "").strip():
                    raise cls._manager_error(f"runner database template catalog missing {field}")
            if str(item.get("pathKind") or "") == "prefix" and not item.get("prefixPatternSets"):
                raise cls._manager_error("runner database template catalog missing prefixPatternSets")

    @staticmethod
    def _manager_error(message: str) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message)
