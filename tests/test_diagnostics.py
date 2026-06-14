from __future__ import annotations

from scripts.collect_diagnostics import (
    build_operator_diagnostics_bundle,
    collect_remote_runner_health,
    collect_environment,
    collect_system_info,
    filter_sensitive,
)


def test_filter_sensitive_redacts_tokens():
    data = {
        "token": "abc123secret",
        "password": "hunter2",
        "name": "visible",
        "nested": {
            "api_key": "key123",
            "runner_token": "tok456",
            "status": "ok",
        },
    }
    result = filter_sensitive(data)
    assert result["token"] == "***REDACTED***"
    assert result["password"] == "***REDACTED***"
    assert result["name"] == "visible"
    assert result["nested"]["api_key"] == "***REDACTED***"
    assert result["nested"]["runner_token"] == "***REDACTED***"
    assert result["nested"]["status"] == "ok"


def test_filter_sensitive_redacts_paths():
    data = {
        "ssh_path": "/home/user/.ssh/id_rsa",
        "config_path": "/etc/h2ometa/config.json",
        "env_file": "/home/user/.env",
    }
    result = filter_sensitive(data)
    assert result["ssh_path"] == "***PATH_REDACTED***"
    assert result["config_path"] == "/etc/h2ometa/config.json"
    assert result["env_file"] == "***PATH_REDACTED***"


def test_filter_sensitive_redacts_bearer_tokens():
    data = {
        "header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "normal": "hello world",
    }
    result = filter_sensitive(data)
    assert result["header"] == "***REDACTED***"
    assert result["normal"] == "hello world"


def test_filter_sensitive_handles_lists():
    data = [
        {"token": "secret", "name": "item1"},
        {"password": "pass", "name": "item2"},
    ]
    result = filter_sensitive(data)
    assert result[0]["token"] == "***REDACTED***"
    assert result[0]["name"] == "item1"
    assert result[1]["password"] == "***REDACTED***"
    assert result[1]["name"] == "item2"


def test_filter_sensitive_preserves_non_sensitive():
    data = {
        "status": "ok",
        "count": 42,
        "items": [1, 2, 3],
        "nested": {"key": "value"},
    }
    result = filter_sensitive(data)
    assert result == data


def test_collect_system_info():
    info = collect_system_info()
    assert "platform" in info
    assert "python" in info
    assert "pid" in info
    assert "timestamp" in info
    assert "cpuCount" in info


def test_collect_environment_filters_secrets():
    import os

    os.environ["H2OMETA_TEST_VALUE"] = "visible"
    os.environ["H2OMETA_SECRET_TOKEN"] = "should_be_redacted"
    try:
        env = collect_environment()
        assert env.get("H2OMETA_TEST_VALUE") == "visible"
        assert env.get("H2OMETA_SECRET_TOKEN") == "***REDACTED***"
    finally:
        os.environ.pop("H2OMETA_TEST_VALUE", None)
        os.environ.pop("H2OMETA_SECRET_TOKEN", None)


def test_collect_remote_runner_health_includes_execution_diagnostics(monkeypatch):
    import io
    import json
    import urllib.error
    import urllib.request

    requested: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict, status: int = 200):
            self.payload = payload
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        if request.full_url.endswith("/health/ready"):
            body = io.BytesIO(b'{"status":"failed","reasonCode":"RUN_WORKER_UNAVAILABLE"}')
            raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, body)
        return FakeResponse({"status": "ok", "data": {"schemaVersion": "execution-diagnostics.v1"}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    health = collect_remote_runner_health("http://runner.local", "runner-token")

    assert any(url.endswith("/health/meta") for url in requested)
    assert any(url.endswith("/health/execution-diagnostics") for url in requested)
    assert health["/health/ready"]["httpStatus"] == 503
    assert health["/health/ready"]["body"]["reasonCode"] == "RUN_WORKER_UNAVAILABLE"
    assert health["/health/execution-diagnostics"]["body"]["data"]["schemaVersion"] == "execution-diagnostics.v1"


def test_operator_diagnostics_bundle_summarizes_probe_statuses(monkeypatch, tmp_path):
    import io
    import json
    import urllib.error
    import urllib.request

    requested: list[str] = []

    class FakeResponse:
        status = 200

        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        requested.append(request.full_url)
        if request.full_url.endswith("/health/ready"):
            body = io.BytesIO(b'{"status":"failed","reasonCode":"RUN_WORKER_UNAVAILABLE"}')
            raise urllib.error.HTTPError(request.full_url, 503, "Service Unavailable", {}, body)
        if request.full_url.endswith("/health/execution-diagnostics"):
            return FakeResponse(
                {
                    "status": "ok",
                    "data": {
                        "schemaVersion": "execution-diagnostics.v1",
                        "readiness": {"reasonCode": ""},
                    },
                }
            )
        return FakeResponse({"status": "ok", "data": {}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    output = tmp_path / "operator-diagnostics.json"

    bundle = build_operator_diagnostics_bundle(
        local_api_base="http://local-api",
        remote_runner_base="http://runner.local",
        runner_token="runner-token",
        server_id="srv_1",
        run_id="run_1",
        scenario_id="resource-wait",
        release_tag="v1.2.3",
        source_commit="abc123",
        output_path=str(output),
    )

    assert bundle["schemaVersion"] == "operator-diagnostics-bundle.v1"
    assert bundle["identity"] == {"serverId": "srv_1", "runId": "run_1", "scenarioId": "resource-wait"}
    assert bundle["summary"]["remoteRunnerReachable"] is True
    assert bundle["summary"]["readinessOk"] is False
    assert bundle["summary"]["reasonCodes"] == ["RUN_WORKER_UNAVAILABLE"]
    assert bundle["summary"]["endpointStatuses"]["ready"]["httpStatus"] == 503
    assert bundle["remoteRunner"]["/health/ready"]["body"]["reasonCode"] == "RUN_WORKER_UNAVAILABLE"
    assert any(url.endswith("/health/meta") for url in requested)
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["bundleId"].startswith("opdiag_")


def test_operator_diagnostics_bundle_records_unreachable_reason(monkeypatch):
    import urllib.error
    import urllib.request

    def fake_urlopen(request, timeout):
        if "runner.local" in request.full_url:
            raise urllib.error.URLError("connection refused")

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok"}'

        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    bundle = build_operator_diagnostics_bundle(
        local_api_base="http://local-api",
        remote_runner_base="http://runner.local",
        server_id="srv_unreachable",
    )

    assert bundle["summary"]["remoteRunnerReachable"] is False
    assert bundle["summary"]["reasonCodes"] == ["RUNNER_UNREACHABLE"]
    assert bundle["summary"]["endpointStatuses"]["startup"]["error"]["reasonCode"] == "RUNNER_UNREACHABLE"
