from __future__ import annotations

from typing import Any, Optional


class BaseRuntimeManager:
    def __init__(self, service: Any) -> None:
        self._service = service

    def _existing_runner_context(
        self,
        *,
        preferred_server_id: Optional[str] = None,
    ) -> tuple[Any, str, Any, dict[str, Any]]:
        with self._service._lock:
            self._service._ensure_initialized()
            server_id, ssh, record = self._service._require_existing_runner_ready(
                preferred_server_id=preferred_server_id
            )
            manager = self._service._service_locator.remote_runner_manager
        return manager, server_id, ssh, record

    def _runner_context(
        self,
        *,
        preferred_server_id: Optional[str] = None,
    ) -> tuple[Any, str, Any, dict[str, Any]]:
        with self._service._lock:
            self._service._ensure_initialized()
            server_id, ssh, record = self._service._require_runner_ready(
                preferred_server_id=preferred_server_id
            )
            manager = self._service._service_locator.remote_runner_manager
        return manager, server_id, ssh, record

    def call_existing_runner(
        self,
        method_name: str,
        *,
        preferred_server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        manager, server_id, ssh, record = self._existing_runner_context(
            preferred_server_id=preferred_server_id
        )
        method = getattr(manager, method_name)
        return self._service._call_remote_runner(
            method,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            **kwargs,
        )

    def call_runner(
        self,
        method_name: str,
        *,
        preferred_server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        manager, server_id, ssh, record = self._runner_context(
            preferred_server_id=preferred_server_id
        )
        method = getattr(manager, method_name)
        return self._service._call_remote_runner(
            method,
            server_id=server_id,
            ssh_service=ssh,
            server_record=record,
            **kwargs,
        )

    def call_remote_endpoint(
        self,
        endpoint_id: str,
        *,
        path_values: dict[str, Any],
        query_values: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        preferred_server_id: Optional[str] = None,
        require_existing_runner: bool = False,
        timeout: int | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "endpoint_id": endpoint_id,
            "path_values": path_values,
            "query_values": dict(query_values or {}),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if payload is not None:
            kwargs["payload"] = dict(payload)
        caller = self.call_existing_runner if require_existing_runner else self.call_runner
        return caller(
            "call_remote_endpoint",
            preferred_server_id=preferred_server_id,
            **kwargs,
        )

    def call_existing_remote_endpoint(
        self,
        endpoint_id: str,
        *,
        path_values: dict[str, Any] | None = None,
        query_values: dict[str, Any] | None = None,
        preferred_server_id: Optional[str] = None,
    ) -> Any:
        return self.call_remote_endpoint(
            endpoint_id,
            path_values=dict(path_values or {}),
            query_values=query_values,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )

    def read_remote_endpoint(
        self,
        endpoint_id: str,
        *,
        path_values: dict[str, Any] | None = None,
        query_values: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        preferred_server_id: Optional[str] = None,
        require_existing_runner: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return {
            "data": self.call_remote_endpoint(
                endpoint_id,
                path_values=dict(path_values or {}),
                query_values=query_values,
                payload=payload,
                preferred_server_id=preferred_server_id,
                require_existing_runner=require_existing_runner,
                timeout=timeout,
            )
        }

    def read_existing_remote_endpoint(
        self,
        endpoint_id: str,
        *,
        query_values: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        preferred_server_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.read_remote_endpoint(
            endpoint_id,
            query_values=query_values,
            payload=payload,
            preferred_server_id=preferred_server_id,
            require_existing_runner=True,
        )
