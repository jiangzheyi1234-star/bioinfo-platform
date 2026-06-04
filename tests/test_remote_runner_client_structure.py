from __future__ import annotations

from pathlib import Path

from core.remote_runner.client import _http_error_detail


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_remote_runner_http_client_does_not_use_broad_exception_parsing() -> None:
    client_source = _source("core/remote_runner/client.py")

    request_source = client_source.split("def _request_json(", 1)[1]
    request_source = request_source.split("def get_json(", 1)[0]
    assert "except Exception" not in request_source


def test_http_error_detail_preserves_structured_detail_as_json() -> None:
    detail = _http_error_detail('{"detail":{"status":"multiple_candidates","candidates":[{"id":"db"}]}}')

    assert detail == '{"status":"multiple_candidates","candidates":[{"id":"db"}]}'
