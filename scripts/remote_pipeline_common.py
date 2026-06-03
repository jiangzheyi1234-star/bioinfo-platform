from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


TERMINAL_RUN_STATUSES = {"completed", "failed"}


def response_data(payload: dict[str, Any]) -> Any:
    data = payload["data"]
    if isinstance(data, dict) and set(data.keys()) == {"data"}:
        return data["data"]
    return data


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def http_json(
    method: str,
    api_base: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc


def print_failure(summary: str, *, hints: list[str], detail: str | None = None) -> None:
    print(f"ERROR: {summary}")
    if detail:
        print(f"DETAIL: {detail}")
    print("NEXT:")
    for hint in hints:
        print(f"  - {hint}")


def pipeline_diagnostics(api_base: str, run_id: str | None = None) -> list[str]:
    hints = [
        "Rerun `python skills/h2ometa-remote-smoke-test/scripts/remote_smoke.py --bootstrap` to re-check control-plane readiness/canary/rollback phases before another pipeline attempt.",
        "Run `python scripts/inspect_remote_runner_service.py` to inspect the remote service log.",
        f"Inspect `{api_base.rstrip('/')}/api/v1/results` after the run if result registration may have failed.",
    ]
    if run_id:
        hints.insert(1, f"Inspect `{api_base.rstrip('/')}/api/v1/runs/{run_id}` and `/api/v1/runs/{run_id}/logs?stream=stderr`.")
    else:
        hints.insert(1, f"Inspect `{api_base.rstrip('/')}/api/v1/runs` for submission failures.")
    return hints


def wait_for_terminal_run(api_base: str, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] = {}
    while time.time() < deadline:
        final = response_data(http_json("GET", api_base, f"/api/v1/runs/{run_id}", timeout=10))
        if final.get("status") in TERMINAL_RUN_STATUSES:
            return final
        time.sleep(1.5)
    return final


def result_id_for_run(items: list[dict[str, Any]], run_id: str) -> str:
    return next(item["resultId"] for item in items if item["runId"] == run_id)


def preview_table(payload: dict[str, Any]) -> dict[str, Any]:
    preview = payload.get("preview")
    if not isinstance(preview, dict):
        return {}
    return preview
