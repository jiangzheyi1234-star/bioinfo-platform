from __future__ import annotations

from typing import Any

from config import resolve_runner_token
from core.remote_runner.client import RemoteRunnerHttpClient


class RemoteRunnerBootstrapReuseGuardMixin:
    def _guard_upgrade_reuse(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        bootstrap_metadata: dict[str, Any],
        bootstrap_action: str,
        previous_release: str = "",
        previous_config_present: bool = False,
    ) -> None:
        if str(bootstrap_action or "").strip() != "upgrade":
            return
        self._guard_bootstrap_when_execution_idle(
            server_id=server_id,
            ssh_service=ssh_service,
            server_record=server_record,
            bootstrap_metadata=bootstrap_metadata,
            bootstrap_action=bootstrap_action,
            previous_release=previous_release,
            previous_config_present=previous_config_present,
        )

    def _copy_upgrade_guard_metadata(self, source: dict[str, Any], target: dict[str, Any]) -> None:
        guard = source.get("upgradeGuard")
        if isinstance(guard, dict):
            target["upgradeGuard"] = dict(guard)

    def _release_bootstrap_lifecycle_guard_for_reuse_result(
        self,
        *,
        server_id: str,
        bootstrap_action: str,
        bootstrap_metadata: dict[str, Any],
        reuse_result: dict[str, Any],
    ) -> None:
        if str(bootstrap_action or "").strip() != "upgrade":
            return
        guard = bootstrap_metadata.get("upgradeGuard")
        if not isinstance(guard, dict) or not str(guard.get("maintenanceOwner") or "").strip():
            return
        token_ref = str(reuse_result.get("token_ref") or "").strip()
        token = resolve_runner_token(token_ref)
        tunnel_port = int(reuse_result.get("tunnel_port") or 0)
        if not token or tunnel_port <= 0:
            raise self._manager_error(
                "remote runner upgrade reuse guard release requires a live reused runner client",
                bootstrap_metadata=bootstrap_metadata,
                status_code=409,
                detail={"reasonCode": "RUNNER_BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE", "serverId": server_id},
            )
        client = RemoteRunnerHttpClient(base_url=f"http://127.0.0.1:{tunnel_port}", token=token, timeout=30)
        self._release_bootstrap_lifecycle_guard(
            client=client,
            server_id=server_id,
            bootstrap_action=bootstrap_action,
            bootstrap_metadata=bootstrap_metadata,
        )
