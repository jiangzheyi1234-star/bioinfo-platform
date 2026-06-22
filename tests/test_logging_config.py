from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from core.logging_config import (
    JsonFormatter,
    clear_log_context,
    configure_structured_logging,
    set_log_context,
)


def test_json_formatter_produces_valid_json():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["component"] == "test.logger"
    assert parsed["logger"] == "test.logger"
    assert parsed["message"] == "test message"
    assert "timestamp" in parsed


def test_json_formatter_includes_context():
    formatter = JsonFormatter()
    set_log_context(request_id="req_123", run_id="run_456", attempt_id="att_789", slot_id="slot-0")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="with context",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["context"]["requestId"] == "req_123"
        assert parsed["context"]["runId"] == "run_456"
        assert parsed["context"]["attemptId"] == "att_789"
        assert parsed["context"]["slotId"] == "slot-0"
    finally:
        clear_log_context()


def test_json_formatter_omits_empty_context():
    formatter = JsonFormatter()
    clear_log_context()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="no context",
        args=(),
        exc_info=None,
    )
    output = formatter.format(record)
    parsed = json.loads(output)
    assert "context" not in parsed


def test_configure_structured_logging():
    configure_structured_logging(level=logging.DEBUG)
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_local_api_runner_uses_structured_logging(monkeypatch):
    from apps.api import run as api_run

    captured: dict[str, Any] = {}

    def fake_uvicorn_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.delenv("H2OMETA_API_ACCESS_LOG", raising=False)
    monkeypatch.setattr(api_run.uvicorn, "run", fake_uvicorn_run)

    api_run.main()

    root = logging.getLogger()
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert captured["args"] == ("apps.api.main:app",)
    assert captured["kwargs"]["log_config"] is None
    assert captured["kwargs"]["access_log"] is False


def test_remote_runner_uses_structured_logging(monkeypatch):
    from apps.remote_runner import run as remote_run

    captured: dict[str, Any] = {}

    class FakeSocket:
        def setsockopt(self, *_args):
            return None

        def bind(self, address):
            captured["bound"] = address

        def listen(self, backlog):
            captured["backlog"] = backlog

        def getsockname(self):
            return ("127.0.0.1", 43210)

        def fileno(self):
            return 123

    class FakeServer:
        def __init__(self, config):
            captured["server_config"] = config

        def run(self, *, sockets):
            captured["server_sockets"] = sockets

    def fake_config(*args, **kwargs):
        captured["config_args"] = args
        captured["config_kwargs"] = kwargs
        return SimpleNamespace(kwargs=kwargs)

    fake_socket = FakeSocket()
    cfg = SimpleNamespace(bind_host="127.0.0.1", bind_port=0)
    monkeypatch.setattr(remote_run, "_set_process_name", lambda: None)
    monkeypatch.setattr(remote_run, "load_remote_runner_config", lambda: cfg)
    monkeypatch.setattr(remote_run, "ensure_runtime_layout", lambda _cfg: None)
    monkeypatch.setattr(remote_run, "write_runtime_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(remote_run.socket, "socket", lambda *_args, **_kwargs: fake_socket)
    monkeypatch.setattr(remote_run.uvicorn, "Config", fake_config)
    monkeypatch.setattr(remote_run.uvicorn, "Server", FakeServer)

    remote_run.main()

    root = logging.getLogger()
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert captured["bound"] == ("127.0.0.1", 0)
    assert captured["backlog"] == 2048
    assert captured["config_kwargs"]["log_config"] is None
    assert captured["config_kwargs"]["fd"] == 123
    assert captured["server_sockets"] == [fake_socket]


def test_set_and_clear_log_context():
    set_log_context(
        request_id="req_1",
        command_id="cmd_2",
        run_id="run_3",
        attempt_id="att_4",
        slot_id="slot_5",
        correlation_id="cor_6",
    )
    from core.logging_config import (
        attempt_id_var,
        command_id_var,
        correlation_id_var,
        request_id_var,
        run_id_var,
        slot_id_var,
    )

    assert request_id_var.get() == "req_1"
    assert command_id_var.get() == "cmd_2"
    assert run_id_var.get() == "run_3"
    assert attempt_id_var.get() == "att_4"
    assert slot_id_var.get() == "slot_5"
    assert correlation_id_var.get() == "cor_6"
    clear_log_context()
    assert request_id_var.get() == ""
    assert run_id_var.get() == ""
    assert slot_id_var.get() == ""
