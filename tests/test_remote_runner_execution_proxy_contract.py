from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_runner_execution_proxy_exposes_retry_run_path() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")

    assert "def retry_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/retry", kwargs["payload"])["data"]' in proxy_source


def test_remote_runner_execution_proxy_exposes_rule_retry_and_resume_paths() -> None:
    manager_source = _source("core/remote_runner/manager.py")
    proxy_source = _source("core/remote_runner/reexecution_proxy.py")

    assert "from core.remote_runner.reexecution_proxy import RemoteRunnerReexecutionProxyMixin" in manager_source
    assert "RemoteRunnerReexecutionProxyMixin" in manager_source
    assert "class RemoteRunnerReexecutionProxyMixin:" in proxy_source
    assert "def retry_run_rules(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/rules/retry", kwargs["payload"])["data"]' in proxy_source
    assert "def apply_rule_output_invalidation(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/output-invalidation/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/staged-files/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_staged_files(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/staged-files/apply"' in proxy_source
    assert "def prepare_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/final-outputs/prepare"' in proxy_source
    assert "def apply_rule_cache_restore_final_outputs(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'f"/api/v1/runs/{kwargs[\'run_id\']}/rules/cache-restore/final-outputs/apply"' in proxy_source
    assert "def resume_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/resume", kwargs["payload"])["data"]' in proxy_source


def test_remote_runner_execution_proxy_exposes_failure_locator_path() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")
    client_source = _source("core/remote_runner/client.py")

    assert "def get_run_failure_locator(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.get_json(f"/api/v1/runs/{kwargs[\'run_id\']}/failure-locator")["data"]' in proxy_source
    assert "def get_run_failure_locator(self, run_id: str) -> dict[str, Any]:" in client_source
    assert 'self.get_json(f"/api/v1/runs/{run_id}/failure-locator")["data"]' in client_source
    assert "def apply_rule_output_invalidation(self, run_id: str, payload: dict[str, Any])" in client_source
    assert "def prepare_rule_cache_restore_staged_files(self, run_id: str, payload: dict[str, Any])" in client_source
    assert "def apply_rule_cache_restore_staged_files(self, run_id: str, payload: dict[str, Any])" in client_source
    assert "def prepare_rule_cache_restore_final_outputs(self, run_id: str, payload: dict[str, Any])" in client_source
    assert "def apply_rule_cache_restore_final_outputs(self, run_id: str, payload: dict[str, Any])" in client_source
