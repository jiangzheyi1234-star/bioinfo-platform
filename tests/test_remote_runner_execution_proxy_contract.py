from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_runner_execution_proxy_exposes_retry_run_path() -> None:
    proxy_source = _source("core/remote_runner/proxy.py")

    assert "def retry_run(self, **kwargs) -> dict[str, Any]:" in proxy_source
    assert 'client.post_json(f"/api/v1/runs/{kwargs[\'run_id\']}/retry", kwargs["payload"])["data"]' in proxy_source
