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
