from __future__ import annotations

from scripts.collect_diagnostics import (
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
        return FakeResponse({"status": "ok", "data": {"schemaVersion": "execution-diagnostics.v1"}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    health = collect_remote_runner_health("http://runner.local", "runner-token")

    assert any(url.endswith("/health/execution-diagnostics") for url in requested)
    assert health["/health/ready"]["httpStatus"] == 503
    assert health["/health/ready"]["reasonCode"] == "RUN_WORKER_UNAVAILABLE"
    assert health["/health/execution-diagnostics"]["data"]["schemaVersion"] == "execution-diagnostics.v1"
