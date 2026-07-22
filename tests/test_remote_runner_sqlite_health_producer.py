from __future__ import annotations

from types import SimpleNamespace

import apps.remote_runner.health_service as health_service


def test_health_payload_fails_closed_when_sqlite_runtime_is_unsafe(
    monkeypatch,
) -> None:
    unsafe = {
        "minimumVersion": "3.51.3",
        "loadedVersion": "3.51.2",
        "sqlVersion": "3.51.2",
        "ok": False,
    }
    monkeypatch.setattr(health_service, "_sqlite_runtime_inspection", lambda: unsafe)
    checks = {"process": True}

    payload = health_service._build_health_payload(
        "ok",
        checks,
        SimpleNamespace(version="test", mode="background_process"),
    )

    assert payload["status"] == "failed"
    assert payload["checks"]["sqlite_runtime"] is False
    assert payload["sqliteRuntime"] == unsafe


def test_sqlite_runtime_inspection_normalizes_observation_errors(
    monkeypatch,
) -> None:
    def fail_observation(**_kwargs):
        raise RuntimeError("observation failed")

    monkeypatch.setattr(
        health_service,
        "collect_remote_runner_sqlite_runtime_evidence",
        fail_observation,
    )

    assert health_service._sqlite_runtime_inspection() == {
        "minimumVersion": "3.51.3",
        "loadedVersion": "",
        "sqlVersion": "",
        "ok": False,
    }
