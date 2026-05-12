#!/usr/bin/env python3
"""Run a generated Snakemake database-injection smoke for every available database."""

from __future__ import annotations

import argparse
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from local_api_smoke_helpers import response_data, selected_server_id


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def http_json(method: str, api_base: str, path: str, *, payload: dict[str, Any] | None = None, timeout: float = 10) -> Any:
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


def cleanup_tool(api_base: str, tool_id: str) -> None:
    try:
        http_json("DELETE", api_base, f"/api/v1/tools/{urllib.parse.quote(tool_id, safe='')}", timeout=10)
    except Exception as exc:
        print_json("TOOL_CLEANUP_SKIPPED", {"id": tool_id, "error": str(exc)})


def role_for_database(database: dict[str, Any], index: int) -> str:
    template_id = str((database.get("metadata") or {}).get("templateId") or database.get("type") or f"db{index}")
    role = re.sub(r"[^a-zA-Z0-9_]+", "_", template_id).strip("_").lower()
    if not role:
        role = f"db{index}"
    if role[0].isdigit():
        role = f"db_{role}"
    return role


def wait_for_run(api_base: str, run_id: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] = {}
    while time.time() < deadline:
        final = response_data(http_json("GET", api_base, f"/api/v1/runs/{run_id}", timeout=10))
        if final.get("status") in {"completed", "failed"}:
            return final
        time.sleep(2)
    return final


def run_database_smoke(api_base: str, database: dict[str, Any], *, server_id: str, index: int, timeout: float) -> dict[str, Any]:
    role = role_for_database(database, index)
    tool_id = f"conda-forge::coreutils-db-path-smoke-{role}-{index}"
    output_name = f"database-{role}-path.txt"
    try:
        tool = response_data(http_json(
            "POST",
            api_base,
            "/api/v1/tools",
            payload={
                "id": tool_id,
                "name": "coreutils",
                "source": "conda-forge",
                "sourceLabel": "conda-forge",
                "version": "9.5",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
                "platforms": ["linux-64"],
                "ruleTemplate": {
                    "commandTemplate": f"printf '%s\\n' {{database.{role}.path:q}} > {{output.database_path:q}}",
                    "inputs": [{"name": "primary", "type": "file", "required": True}],
                    "outputs": [{"name": "database_path", "path": output_name, "kind": "log", "mimeType": "text/plain"}],
                },
            },
            timeout=30,
        ))
        upload = response_data(http_json(
            "POST",
            api_base,
            "/api/v1/uploads",
            payload={
                "filename": f"db-smoke-{role}.txt",
                "contentBase64": base64.b64encode(b"database smoke\n").decode("ascii"),
                "mimeType": "text/plain",
            },
            timeout=30,
        ))
        submitted = response_data(http_json(
            "POST",
            api_base,
            "/api/v1/runs",
            payload={
                "serverId": server_id,
                "requestId": f"req_all_db_smoke_{index}_{int(time.time() * 1000)}",
                "runSpec": {
                    "projectId": "proj_smoke",
                    "pipelineId": "generated-tool-run-v1",
                    "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "input"}],
                    "databases": [{"id": database["id"], "role": role}],
                    "tool": {"id": tool["id"]},
                },
            },
            timeout=30,
        ))
        final = wait_for_run(api_base, submitted["runId"], timeout=timeout)
        if final.get("status") != "completed":
            return {
                "id": database["id"],
                "templateId": (database.get("metadata") or {}).get("templateId"),
                "status": "failed",
                "runId": submitted["runId"],
                "error": final.get("lastError") or final.get("stage") or "run did not complete",
            }
        results = response_data(http_json("GET", api_base, f"/api/v1/runs/{submitted['runId']}/results", timeout=10))
        artifacts = results.get("artifacts") or []
        artifact_names = [Path(str(item.get("path") or "")).name for item in artifacts]
        return {
            "id": database["id"],
            "templateId": (database.get("metadata") or {}).get("templateId"),
            "status": "completed" if output_name in artifact_names else "failed",
            "runId": submitted["runId"],
            "role": role,
            "artifact": output_name,
            "artifactNames": artifact_names,
        }
    except Exception as exc:
        return {
            "id": database["id"],
            "templateId": (database.get("metadata") or {}).get("templateId"),
            "status": "failed",
            "error": str(exc),
        }
    finally:
        cleanup_tool(api_base, tool_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test generated Snakemake database injection for each available database.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--one-per-template", action="store_true", help="Run only the first available database for each template.")
    args = parser.parse_args()

    databases = http_json("GET", args.api_base, "/api/v1/databases", timeout=30)["data"]["items"]
    unavailable = [item for item in databases if item.get("status") != "available"]
    available = [item for item in databases if item.get("status") == "available"]
    if args.one_per_template:
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in available:
            template_id = str((item.get("metadata") or {}).get("templateId") or item.get("type") or item["id"])
            if template_id in seen:
                continue
            seen.add(template_id)
            selected.append(item)
        available = selected

    print_json(
        "DATABASE_SMOKE_SCOPE",
        {
            "availableCount": len(available),
            "unavailableCount": len(unavailable),
            "unavailable": [
                {
                    "id": item.get("id"),
                    "templateId": (item.get("metadata") or {}).get("templateId"),
                    "status": item.get("status"),
                    "message": item.get("message"),
                }
                for item in unavailable
            ],
        },
    )
    server_id = selected_server_id(args.api_base)
    results = []
    for index, database in enumerate(available, start=1):
        result = run_database_smoke(args.api_base, database, server_id=server_id, index=index, timeout=args.timeout)
        results.append(result)
        print_json("DATABASE_SNAKEMAKE_RESULT", result)
    failed = [item for item in results if item.get("status") != "completed"]
    print_json("DATABASE_SNAKEMAKE_SUMMARY", {"completed": len(results) - len(failed), "failed": len(failed), "totalRun": len(results)})
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
