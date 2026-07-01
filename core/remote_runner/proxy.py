from __future__ import annotations

from typing import Any

from config import resolve_runner_token
from core.contracts.remote_endpoints import EXECUTION_LIFECYCLE_GUARD, EXECUTION_LIFECYCLE_GUARD_RELEASE
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.client import RemoteRunnerClientError, RemoteRunnerConflictError, RemoteRunnerHttpClient
from core.remote_runner.diagnostics import (
    build_execution_diagnostics,
    build_operator_diagnostics_bundle,
    build_remote_runner_lifecycle_diagnostics,
    build_remote_runner_lifecycle_unavailable,
)
from core.remote_runner.endpoint_caller import call_remote_endpoint as execute_remote_endpoint
from core.remote_runner.health import build_runner_health
from core.remote_runner.layout import remote_runner_bootstrap_layout


def _is_manager_error(exc: Exception) -> bool:
    return exc.__class__.__name__ == "RemoteRunnerManagerError"


def _record_service_port(record: dict[str, Any]) -> int | None:
    try:
        port = int(record.get("service_port") or 0)
    except (TypeError, ValueError):
        return None
    if port <= 0 or port > 65535:
        return None
    return port


def _manager_error_blocks_runtime_state_resync(exc: Exception) -> bool:
    detail = str(exc)
    return (
        "runner token not available" in detail
        or "service_port is missing" in detail
        or "service_port is invalid" in detail
    )


class RemoteRunnerProxyMixin:
    def call_remote_endpoint(self, **kwargs) -> Any:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
            timeout=int(kwargs.get("timeout") or 5),
        )
        return execute_remote_endpoint(
            client,
            str(kwargs["endpoint_id"]),
            path_values=dict(kwargs.get("path_values") or {}),
            query_values=dict(kwargs.get("query_values") or {}),
            payload=kwargs.get("payload"),
            raw_body=kwargs.get("raw_body"),
            extra_headers=kwargs.get("extra_headers"),
        )

    def get_health(self, **kwargs) -> dict[str, Any]:
        return self._get_health_with_runtime_state_resync(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=dict(kwargs["server_record"]),
        )

    def get_execution_diagnostics(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return build_execution_diagnostics(client)

    def request_execution_lifecycle_guard(self, **kwargs) -> dict[str, Any]:
        return self._call_lifecycle_guard_endpoint(
            endpoint_id=EXECUTION_LIFECYCLE_GUARD,
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            server_record=kwargs["server_record"],
            payload={
                "action": str(kwargs["action"]),
                "owner": str(kwargs["owner"]),
                "ttlSeconds": int(kwargs.get("ttl_seconds") or 600),
            },
            timeout=int(kwargs.get("timeout") or 30),
        )

    def release_execution_lifecycle_guard(self, **kwargs) -> dict[str, Any]:
        return self._call_lifecycle_guard_endpoint(
            endpoint_id=EXECUTION_LIFECYCLE_GUARD_RELEASE,
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            server_record=kwargs["server_record"],
            payload={
                "action": str(kwargs["action"]),
                "owner": str(kwargs["owner"]),
            },
            timeout=int(kwargs.get("timeout") or 30),
        )

    def _call_lifecycle_guard_endpoint(
        self,
        *,
        endpoint_id: str,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        payload: dict[str, Any],
        timeout: int,
    ) -> dict[str, Any]:
        client = self._get_client(
            server_id=server_id,
            ssh_service=ssh_service,
            record=server_record,
            timeout=timeout,
        )
        return self._call_lifecycle_guard_endpoint_with_client(
            client=client,
            endpoint_id=endpoint_id,
            payload=payload,
        )

    @classmethod
    def _call_lifecycle_guard_endpoint_with_client(
        cls,
        *,
        client: RemoteRunnerHttpClient,
        endpoint_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            result = execute_remote_endpoint(
                client,
                endpoint_id,
                path_values={},
                payload=payload,
            )
        except RemoteRunnerConflictError as exc:
            raise cls._manager_error(
                "remote runner execution lifecycle guard blocked",
                status_code=409,
                detail=exc.payload,
            ) from exc
        if not isinstance(result, dict):
            raise cls._manager_error("remote runner execution lifecycle guard returned a non-object response")
        return result

    def get_operator_diagnostics(self, **kwargs) -> dict[str, Any]:
        record = kwargs["server_record"]
        ssh_service = kwargs["ssh_service"]
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=ssh_service,
            record=record,
        )
        metadata = record.get("bootstrap_metadata") if isinstance(record.get("bootstrap_metadata"), dict) else {}
        release = metadata.get("release") if isinstance(metadata.get("release"), dict) else {}
        release_tag = str(release.get("releaseTag") or record.get("bootstrap_version") or "")
        lifecycle = self._build_operator_lifecycle_diagnostics(
            ssh_service=ssh_service,
            release_tag=release_tag,
        )
        return build_operator_diagnostics_bundle(
            client,
            server_id=str(kwargs["server_id"]),
            run_id=str(kwargs.get("run_id") or ""),
            scenario_id=str(kwargs.get("scenario_id") or ""),
            release_tag=release_tag,
            source_commit=str(release.get("sourceCommit") or ""),
            lifecycle=lifecycle,
        )

    def _build_operator_lifecycle_diagnostics(
        self,
        *,
        ssh_service,
        release_tag: str,
    ) -> dict[str, Any]:
        try:
            home_dir = self._resolve_remote_home(ssh_service)
            return build_remote_runner_lifecycle_diagnostics(
                ssh_service,
                home_dir=home_dir,
                release_tag=release_tag,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics must be best-effort evidence.
            return build_remote_runner_lifecycle_unavailable(
                reason_code="RUNNER_LIFECYCLE_DIAGNOSTICS_UNAVAILABLE",
                detail=str(exc) or "runner lifecycle diagnostics unavailable",
                error_type=type(exc).__name__,
            )

    def _open_runner_tunnel(self, *, server_id: str, ssh_service, remote_port: int):
        try:
            return ssh_service.ensure_local_tunnel(
                f"runner-{server_id}",
                remote_host="127.0.0.1",
                remote_port=remote_port,
            )
        except (RuntimeError, OSError, EOFError) as exc:
            if _is_manager_error(exc):
                raise
            detail = str(exc) or exc.__class__.__name__
            raise self._manager_error(detail) from exc

    def _get_health_with_runtime_state_resync(
        self,
        *,
        server_id: str,
        ssh_service,
        record: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            client, service_port, tunnel_port = self._get_client_connection(
                server_id=server_id,
                ssh_service=ssh_service,
                record=record,
            )
        except Exception as exc:
            if not _is_manager_error(exc) or _manager_error_blocks_runtime_state_resync(exc):
                raise
            stale_service_port = _record_service_port(record)
            if stale_service_port is None:
                raise
            return self._get_health_after_runtime_state_resync(
                server_id=server_id,
                ssh_service=ssh_service,
                record=record,
                stale_service_port=stale_service_port,
                stale_error=exc,
            )
        try:
            health = build_runner_health(client)
        except RemoteRunnerClientError as exc:
            return self._get_health_after_runtime_state_resync(
                server_id=server_id,
                ssh_service=ssh_service,
                record=record,
                stale_service_port=service_port,
                stale_error=exc,
            )
        return self._attach_connection_metadata(
            health,
            service_port=service_port,
            tunnel_port=tunnel_port,
        )

    def _get_health_after_runtime_state_resync(
        self,
        *,
        server_id: str,
        ssh_service,
        record: dict[str, Any],
        stale_service_port: int,
        stale_error: Exception,
    ) -> dict[str, Any]:
        version = str(record.get("bootstrap_version") or REMOTE_RUNNER_VERSION)
        home_dir = self._resolve_remote_home(ssh_service)
        paths = remote_runner_bootstrap_layout(home_dir, version)
        state = self._wait_for_runtime_state(
            ssh_service=ssh_service,
            remote_runtime_state=paths.runtime_state,
            version=version,
            attempts=1,
            delay_seconds=0,
        )
        service_port = int(state["bindPort"])
        if service_port == stale_service_port:
            raise stale_error
        token = self._resolve_runner_token(record)
        tunnel = self._open_runner_tunnel(
            server_id=server_id,
            ssh_service=ssh_service,
            remote_port=service_port,
        )
        client = RemoteRunnerHttpClient(
            base_url=f"http://127.0.0.1:{tunnel.local_port}",
            token=token,
            timeout=5,
        )
        runtime_state = {
            "bindPort": service_port,
            "pid": int(state.get("pid") or 0),
            "version": str(state.get("version") or version),
        }
        try:
            health = build_runner_health(client)
        except RemoteRunnerClientError as exc:
            detail_payload = dict(exc.detail) if isinstance(exc.detail, dict) else {}
            detail_payload.setdefault("message", str(exc))
            detail_payload["servicePort"] = service_port
            detail_payload["tunnelPort"] = int(tunnel.local_port)
            detail_payload["runtimeState"] = runtime_state
            detail_payload["connectionResynced"] = True
            raise RemoteRunnerClientError(
                str(exc),
                status_code=exc.status_code,
                detail=detail_payload,
            ) from exc
        health = self._attach_connection_metadata(
            health,
            service_port=service_port,
            tunnel_port=int(tunnel.local_port),
        )
        health["runtimeState"] = runtime_state
        health["connectionResynced"] = True
        return health

    @classmethod
    def _attach_connection_metadata(
        cls,
        health: dict[str, Any],
        *,
        service_port: int,
        tunnel_port: int,
    ) -> dict[str, Any]:
        health["servicePort"] = service_port
        health["tunnelPort"] = tunnel_port
        return health

    @classmethod
    def _resolve_runner_token(cls, record: dict[str, Any]) -> str:
        token = resolve_runner_token(str(record.get("token_ref", "") or ""))
        if not token:
            raise cls._manager_error("runner token not available")
        return token

    def _get_client_connection(
        self,
        *,
        server_id: str,
        ssh_service,
        record: dict[str, Any],
        timeout: int = 5,
    ) -> tuple[RemoteRunnerHttpClient, int, int]:
        token = self._resolve_runner_token(record)
        remote_port = self._require_service_port(record)
        tunnel = self._open_runner_tunnel(
            server_id=server_id,
            ssh_service=ssh_service,
            remote_port=remote_port,
        )
        return (
            RemoteRunnerHttpClient(
                base_url=f"http://127.0.0.1:{tunnel.local_port}",
                token=token,
                timeout=timeout,
            ),
            remote_port,
            int(tunnel.local_port),
        )

    def _get_client(self, *, server_id: str, ssh_service, record: dict[str, Any], timeout: int = 5) -> RemoteRunnerHttpClient:
        client, _, _ = self._get_client_connection(
            server_id=server_id,
            ssh_service=ssh_service,
            record=record,
            timeout=timeout,
        )
        return client


    @staticmethod
    def _manager_error(message: str, **kwargs) -> RuntimeError:
        from core.remote_runner.manager import RemoteRunnerManagerError

        return RemoteRunnerManagerError(message, **kwargs)
