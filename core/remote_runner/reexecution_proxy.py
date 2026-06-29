from __future__ import annotations

from typing import Any


class RemoteRunnerReexecutionProxyMixin:
    def retry_run_rules(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(f"/api/v1/runs/{kwargs['run_id']}/rules/retry", kwargs["payload"])["data"]

    def apply_rule_output_invalidation(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/output-invalidation/apply",
            kwargs["payload"],
        )["data"]

    def prepare_rule_cache_restore_pins(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/pins/prepare",
            kwargs["payload"],
        )["data"]

    def apply_rule_cache_restore_pins(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/pins/apply",
            kwargs["payload"],
        )["data"]

    def prepare_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/staged-files/prepare",
            kwargs["payload"],
        )["data"]

    def apply_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/staged-files/apply",
            kwargs["payload"],
        )["data"]

    def prepare_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/final-outputs/prepare",
            kwargs["payload"],
        )["data"]

    def apply_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/final-outputs/apply",
            kwargs["payload"],
        )["data"]

    def prepare_rule_cache_restore_adoption(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/adoption/prepare",
            kwargs["payload"],
        )["data"]

    def apply_rule_cache_restore_adoption(self, **kwargs) -> dict[str, Any]:
        client = self._get_client(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            record=kwargs["server_record"],
        )
        return client.post_json(
            f"/api/v1/runs/{kwargs['run_id']}/rules/cache-restore/adoption/apply",
            kwargs["payload"],
        )["data"]
