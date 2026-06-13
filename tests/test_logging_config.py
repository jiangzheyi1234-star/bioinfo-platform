from __future__ import annotations

import json
import logging

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
    assert parsed["logger"] == "test.logger"
    assert parsed["message"] == "test message"
    assert "timestamp" in parsed


def test_json_formatter_includes_context():
    formatter = JsonFormatter()
    set_log_context(request_id="req_123", run_id="run_456")
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


def test_set_and_clear_log_context():
    set_log_context(
        request_id="req_1",
        command_id="cmd_2",
        run_id="run_3",
        attempt_id="att_4",
        correlation_id="cor_5",
    )
    from core.logging_config import (
        attempt_id_var,
        command_id_var,
        correlation_id_var,
        request_id_var,
        run_id_var,
    )

    assert request_id_var.get() == "req_1"
    assert command_id_var.get() == "cmd_2"
    assert run_id_var.get() == "run_3"
    assert attempt_id_var.get() == "att_4"
    assert correlation_id_var.get() == "cor_5"
    clear_log_context()
    assert request_id_var.get() == ""
    assert run_id_var.get() == ""
