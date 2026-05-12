#!/usr/bin/env python3
"""Run a generated single-tool Snakemake workflow through the Windows Local API."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from local_api_smoke_helpers import response_data, selected_server_id


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


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
        http_json("DELETE", api_base, f"/api/v1/tools/{tool_id}", timeout=10)
    except Exception as exc:
        print_json("TOOL_CLEANUP_SKIPPED", {"id": tool_id, "error": str(exc)})


def build_run_submit_payload(
    *,
    request_id: str,
    server_id: str,
    project_id: str,
    upload: dict[str, Any],
    tool: dict[str, Any],
) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "requestId": request_id,
        "runSpec": {
            "projectId": project_id,
            "pipelineId": "generated-tool-run-v1",
            "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "input"}],
            "tool": {
                "id": tool["id"],
            },
        },
    }


def main() -> int:
    find_repo_root()
    parser = argparse.ArgumentParser(description="Smoke-test generated-tool-run-v1 through the Local API.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    tool_id = "conda-forge::coreutils-generated-smoke"
    tool_payload = {
        "id": tool_id,
        "name": "coreutils",
        "source": "conda-forge",
        "sourceLabel": "conda-forge",
        "version": "9.5",
        "packageSpec": "conda-forge::coreutils=9.5",
        "summary": "GNU core utilities for generated Snakemake smoke testing.",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "platforms": ["linux-64"],
        "testCommand": "wc --version",
        "ruleTemplate": {
            "commandTemplate": "wc -c {input.primary:q} > {output.count:q}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": "count", "path": "wc-count.txt", "kind": "log", "mimeType": "text/plain"}],
        },
    }
    try:
        server_id = selected_server_id(args.api_base)
        tool = response_data(http_json("POST", args.api_base, "/api/v1/tools", payload=tool_payload, timeout=30))
        print_json("TOOL_REGISTERED", {"id": tool["id"], "status": tool["status"], "packageSpec": tool["packageSpec"]})

        sample = b"ABCDEF\n"
        upload = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/uploads",
            payload={
                "filename": "letters.txt",
                "contentBase64": base64.b64encode(sample).decode("ascii"),
                "mimeType": "text/plain",
            },
        ))
        print_json("UPLOAD", {"uploadId": upload["uploadId"], "filename": upload["filename"], "sizeBytes": upload["sizeBytes"]})

        request_id = f"req_generated_tool_smoke_{int(time.time() * 1000)}"
        submitted = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/runs",
            payload=build_run_submit_payload(
                request_id=request_id,
                server_id=server_id,
                project_id="proj_smoke",
                upload=upload,
                tool=tool,
            ),
            timeout=30,
        ))
        run_id = submitted["runId"]
        print_json("RUN_SUBMITTED", {"runId": run_id, "status": submitted["status"], "stage": submitted["stage"]})

        deadline = time.time() + args.timeout
        final = submitted
        while time.time() < deadline:
            final = response_data(http_json("GET", args.api_base, f"/api/v1/runs/{run_id}", timeout=10))
            if final["status"] in {"completed", "failed"}:
                break
            time.sleep(2)
        print_json(
            "RUN_FINAL",
            {
                "runId": run_id,
                "status": final.get("status"),
                "stage": final.get("stage"),
                "lastError": final.get("lastError"),
            },
        )
        if final.get("status") != "completed":
            return 1

        results = response_data(http_json("GET", args.api_base, f"/api/v1/runs/{run_id}/results", timeout=10))
        artifacts = results.get("artifacts") or []
        print_json(
            "RUN_ARTIFACTS",
            {
                "artifactCount": len(artifacts),
                "artifacts": [
                    {"name": Path(str(item.get("path") or "")).name, "mimeType": item.get("mimeType"), "sizeBytes": item.get("sizeBytes")}
                    for item in artifacts
                ],
            },
        )
        return 0 if any(str(item.get("path") or "").endswith("wc-count.txt") for item in artifacts) else 1
    finally:
        cleanup_tool(args.api_base, tool_id)


if __name__ == "__main__":
    raise SystemExit(main())
