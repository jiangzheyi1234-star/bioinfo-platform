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
    assert "export type LocalApiProblemDetails" in client
    assert "problem?: LocalApiProblemDetails" in client
    assert "problem: problemDetail" in client


def test_local_api_client_defaults_to_launcher_ipv4_api_address() -> None:
    root = Path(__file__).resolve().parents[1]
    client = (root / "apps" / "web" / "app" / "lib" / "local-api-client.ts").read_text(encoding="utf-8")

    assert 'process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8765"' in client
    assert '"http://localhost:8765"' not in client
