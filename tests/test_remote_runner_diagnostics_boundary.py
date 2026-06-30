from __future__ import annotations

import hashlib
import json
from typing import Any

from core.remote_runner.diagnostics import (
    OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS,
    build_execution_diagnostics,
    build_operator_diagnostics_bundle,
    build_remote_runner_lifecycle_diagnostics,
)
from core.remote_runner.proxy import RemoteRunnerProxyMixin


class FakeDiagnosticClient:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.probe_calls: list[tuple[str, list[int]]] = []

    def get_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.get_calls.append(path)
        return {
            "data": {
                "schemaVersion": "execution-diagnostics.v1",
                "readiness": {"ok": True},
            }
        }

    def probe_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.probe_calls.append((path, sorted(accepted_statuses or [])))
        if path == "/health/ready":
            return {
                "httpStatus": 503,
                "body": {"status": "failed", "reasonCode": "RUN_WORKER_UNAVAILABLE"},
            }
        return {"httpStatus": 200, "body": {"status": "ok", "data": {}}}


class UnreachableDiagnosticClient(FakeDiagnosticClient):
    def probe_json(
        self, path: str, *, accepted_statuses: set[int] | None = None
    ) -> dict[str, Any]:
        self.probe_calls.append((path, sorted(accepted_statuses or [])))
        return {
            "httpStatus": None,
            "body": None,
            "error": {
                "reasonCode": "RUNNER_UNREACHABLE",
                "message": "connection refused",
                "errorType": "URLError",
            },
        }


def test_execution_diagnostics_uses_transport_get_json() -> None:
    client = FakeDiagnosticClient()

    diagnostics = build_execution_diagnostics(client)

    assert diagnostics["schemaVersion"] == "execution-diagnostics.v1"
    assert client.get_calls == ["/health/execution-diagnostics"]


def test_operator_diagnostics_bundle_uses_explicit_health_probe_set() -> None:
    client = FakeDiagnosticClient()

    bundle = build_operator_diagnostics_bundle(
        client,
        server_id="srv_1",
        run_id="run_1",
        scenario_id="moving-pictures-16s",
        release_tag="v1.0.0",
        source_commit="abc123",
    )

    assert bundle["schemaVersion"] == "operator-diagnostics-bundle.v1"
    assert bundle["identity"] == {
        "serverId": "srv_1",
        "runId": "run_1",
        "scenarioId": "moving-pictures-16s",
    }
    assert bundle["release"] == {"releaseTag": "v1.0.0", "sourceCommit": "abc123"}
    assert bundle["summary"]["remoteRunnerReachable"] is True
    assert bundle["summary"]["readinessOk"] is False
    assert bundle["summary"]["reasonCodes"] == ["RUN_WORKER_UNAVAILABLE"]
    assert bundle["summary"]["endpointStatuses"]["ready"]["httpStatus"] == 503
    expected_hash = _expected_bundle_hash(bundle)
    assert bundle["bundleHash"] == expected_hash
    assert bundle["bundleId"] == f"opdiag_{expected_hash[:16]}"
    assert [path for path, _statuses in client.probe_calls] == list(
        OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS
    )
    assert all(statuses == [200, 503] for _path, statuses in client.probe_calls)


class FakeSshService:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands.append(cmd)
        if "readlink -f" in cmd:
            return 0, "/home/tester/.h2ometa/runner/releases/v1.0.0\n", ""
        if "artifact.sha256" in cmd:
            return 0, "a" * 64, ""
        if "runner-state.json" in cmd:
            return (
                0,
                json.dumps(
                    {
                        "service": "h2ometa-remote",
                        "version": "v1.0.0",
                        "pid": 123,
                        "bindHost": "127.0.0.1",
                        "bindPort": 43127,
                        "startedAt": "2026-06-30T00:00:00Z",
                    }
                ),
                "",
            )
        if "systemctl --user show" in cmd:
            return (
                0,
                "LoadState=loaded\nActiveState=active\nSubState=running\nUnitFileState=enabled\nNeedDaemonReload=no\n",
                "",
            )
        if "loginctl show-user" in cmd:
            return 0, "yes\n", ""
        if "journalctl --user" in cmd:
            return (
                0,
                "2026-06-30T00:00:00Z runner started\n2026-06-30T00:00:01Z token: hidden-value\n",
                "",
            )
        if "tail -n" in cmd:
            return (
                0,
                "runner online\nAuthorization: Bearer abc123\napi_key=secret-value\n",
                "",
            )
        raise AssertionError(f"unexpected command: {cmd}")


def test_lifecycle_diagnostics_collects_remote_agent_state_without_raw_paths() -> None:
    ssh = FakeSshService()

    diagnostics = build_remote_runner_lifecycle_diagnostics(
        ssh,
        home_dir="/home/tester",
        release_tag="v1.0.0",
        log_tail_lines=5,
    )

    assert diagnostics["schemaVersion"] == "remote-runner-lifecycle-diagnostics.v1"
    assert diagnostics["ok"] is True
    assert diagnostics["reasonCodes"] == []
    assert diagnostics["currentRelease"]["targetRelease"] == "v1.0.0"
    assert diagnostics["currentRelease"]["matchesExpectedRelease"] is True
    assert diagnostics["currentRelease"]["targetPathSha256"] == hashlib.sha256(
        b"/home/tester/.h2ometa/runner/releases/v1.0.0"
    ).hexdigest()
    assert diagnostics["artifactMarker"]["sha256"] == "a" * 64
    assert diagnostics["runtimeState"]["bindPort"] == 43127
    assert diagnostics["systemdUserService"]["properties"]["ActiveState"] == "active"
    assert diagnostics["systemdUserService"]["linger"]["enabled"] is True
    assert any(
        "token:***REDACTED***" in line
        for line in diagnostics["systemdUserService"]["journalTail"]["tail"]
    )
    assert "hidden-value" not in json.dumps(diagnostics)
    assert "Authorization:***REDACTED***" in diagnostics["runnerLogTail"]["tail"]
    assert "api_key=***REDACTED***" in diagnostics["runnerLogTail"]["tail"]
    assert "/home/tester" not in json.dumps(diagnostics)
    assert diagnostics["redactionPolicy"]["rawPathsExposed"] is False
    assert len(ssh.commands) == 7


def test_operator_diagnostics_summary_includes_lifecycle_reason_codes() -> None:
    client = FakeDiagnosticClient()

    bundle = build_operator_diagnostics_bundle(
        client,
        server_id="srv_1",
        lifecycle={
            "schemaVersion": "remote-runner-lifecycle-diagnostics.v1",
            "ok": False,
            "reasonCodes": ["RUNNER_RUNTIME_STATE_MISSING"],
        },
    )

    assert "remoteLifecycle" in bundle
    assert "remoteLifecycle" in bundle["includedSections"]
    assert bundle["summary"]["lifecycleDiagnosticsOk"] is False
    assert bundle["summary"]["lifecycleReasonCodes"] == ["RUNNER_RUNTIME_STATE_MISSING"]
    assert "RUNNER_RUNTIME_STATE_MISSING" in bundle["summary"]["reasonCodes"]


def test_operator_diagnostics_bundle_summarizes_unreachable_runner() -> None:
    client = UnreachableDiagnosticClient()

    bundle = build_operator_diagnostics_bundle(client, server_id="srv_down")

    assert bundle["summary"]["remoteRunnerReachable"] is False
    assert bundle["summary"]["reasonCodes"] == ["RUNNER_UNREACHABLE"]
    assert (
        bundle["summary"]["endpointStatuses"]["startup"]["error"]["reasonCode"]
        == "RUNNER_UNREACHABLE"
    )
    assert [path for path, _statuses in client.probe_calls] == list(
        OPERATOR_DIAGNOSTIC_HEALTH_ENDPOINTS
    )


class FakeDiagnosticsProxy(RemoteRunnerProxyMixin):
    def __init__(self) -> None:
        self.client = object()
        self.client_requests: list[dict[str, Any]] = []

    def _get_client(self, **kwargs: Any) -> object:
        self.client_requests.append(dict(kwargs))
        return self.client


def test_proxy_diagnostics_methods_delegate_after_connection(monkeypatch) -> None:
    proxy = FakeDiagnosticsProxy()
    ssh_service = object()
    record = {
        "bootstrap_version": "fallback-release",
        "bootstrap_metadata": {
            "release": {"releaseTag": "v1.2.3", "sourceCommit": "abc123"}
        },
    }
    captured: dict[str, Any] = {}

    def fake_execution(client: object) -> dict[str, Any]:
        captured["executionClient"] = client
        return {"schemaVersion": "execution-diagnostics.v1"}

    def fake_operator(client: object, **kwargs: Any) -> dict[str, Any]:
        captured["operatorClient"] = client
        captured["operatorKwargs"] = dict(kwargs)
        return {"schemaVersion": "operator-diagnostics-bundle.v1"}

    monkeypatch.setattr(
        "core.remote_runner.proxy.build_execution_diagnostics",
        fake_execution,
    )
    monkeypatch.setattr(
        "core.remote_runner.proxy.build_operator_diagnostics_bundle",
        fake_operator,
    )

    execution = proxy.get_execution_diagnostics(
        server_id="srv_1", ssh_service=ssh_service, server_record=record
    )
    operator = proxy.get_operator_diagnostics(
        server_id="srv_1",
        ssh_service=ssh_service,
        server_record=record,
        run_id="run_1",
        scenario_id="moving-pictures-16s",
    )

    assert execution["schemaVersion"] == "execution-diagnostics.v1"
    assert operator["schemaVersion"] == "operator-diagnostics-bundle.v1"
    assert captured["executionClient"] is proxy.client
    assert captured["operatorClient"] is proxy.client
    assert captured["operatorKwargs"] == {
        "server_id": "srv_1",
        "run_id": "run_1",
        "scenario_id": "moving-pictures-16s",
        "release_tag": "v1.2.3",
        "source_commit": "abc123",
        "lifecycle": {
            "schemaVersion": "remote-runner-lifecycle-diagnostics.v1",
            "status": "unavailable",
            "ok": False,
            "reasonCodes": ["RUNNER_LIFECYCLE_DIAGNOSTICS_UNAVAILABLE"],
            "error": {
                "type": "AttributeError",
                "message": "'FakeDiagnosticsProxy' object has no attribute '_resolve_remote_home'",
            },
            "redactionPolicy": {
                "schemaVersion": "diagnostics-redaction.v1",
                "rawPathsExposed": False,
                "secretsExposed": False,
            },
        },
    }
    assert proxy.client_requests == [
        {"server_id": "srv_1", "ssh_service": ssh_service, "record": record},
        {"server_id": "srv_1", "ssh_service": ssh_service, "record": record},
    ]


def _expected_bundle_hash(bundle: dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in bundle.items()
        if key not in {"bundleHash", "bundleId"}
    }
    payload = json.dumps(
        comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
