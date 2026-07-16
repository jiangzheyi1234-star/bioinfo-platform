from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_keeps_lifecycle_guard_through_canary() -> None:
    manager_source = (ROOT / "core" / "remote_runner" / "manager.py").read_text(encoding="utf-8")
    activation_start = manager_source.index("self._wait_for_runner_live(client)")
    activation_end = manager_source.index('release_switch["active_release"]', activation_start)
    activation_source = manager_source[activation_start:activation_end]

    live_index = activation_source.index("self._wait_for_runner_live(client)")
    release_index = activation_source.index("self._release_bootstrap_lifecycle_guard(")
    health_index = activation_source.index("health = self._wait_for_runner_health(client)")
    canary_index = activation_source.index("self._run_bootstrap_canary(")

    assert live_index < health_index < canary_index < release_index
