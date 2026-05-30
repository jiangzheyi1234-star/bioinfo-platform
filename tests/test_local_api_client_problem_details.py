from __future__ import annotations

from pathlib import Path


def test_local_api_client_extracts_nested_problem_details() -> None:
    root = Path(__file__).resolve().parents[1]
    client = (root / "apps" / "web" / "app" / "lib" / "local-api-client.ts").read_text(encoding="utf-8")

    assert "const problemDetail =" in client
    assert 'typeof payload?.detail === "object"' in client
    assert "problemDetail.detail" in client
    assert "problemDetail.title" in client
    assert "problemDetail.requestId" in client
    assert "problemDetail.code" in client
