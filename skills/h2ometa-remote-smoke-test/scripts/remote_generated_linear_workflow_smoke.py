#!/usr/bin/env python3
"""Run a generated two-step Snakemake workflow through the Windows Local API."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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


def register_tool(api_base: str, *, tool_id: str, command: str, output_name: str, output_path: str) -> dict[str, Any]:
    payload = {
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
            "commandTemplate": command,
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": output_name, "path": output_path, "kind": "log", "mimeType": "text/plain"}],
        },
    }
    return http_json("POST", api_base, "/api/v1/tools", payload=payload, timeout=30)["data"]


def main() -> int:
    find_repo_root()
    parser = argparse.ArgumentParser(description="Smoke-test a generated two-step Snakemake workflow through the Local API.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=420)
    args = parser.parse_args()

    count_tool_id = "conda-forge::coreutils-count-smoke"
    copy_tool_id = "conda-forge::coreutils-copy-smoke"
    try:
        count_tool = register_tool(
            args.api_base,
            tool_id=count_tool_id,
            command="wc -c {input.primary:q} > {output.count:q}",
            output_name="count",
            output_path="wc-count.txt",
        )
        copy_tool = register_tool(
            args.api_base,
            tool_id=copy_tool_id,
            command="cp {input.primary:q} {output.final:q}",
            output_name="final",
            output_path="final-count.txt",
        )
        print_json(
            "TOOLS_REGISTERED",
            [
                {"id": count_tool["id"], "status": count_tool["status"], "packageSpec": count_tool["packageSpec"]},
                {"id": copy_tool["id"], "status": copy_tool["status"], "packageSpec": copy_tool["packageSpec"]},
            ],
        )

        sample = b"ABCDEF\n"
        upload = http_json(
            "POST",
            args.api_base,
            "/api/v1/uploads",
            payload={
                "filename": "letters.txt",
                "contentBase64": base64.b64encode(sample).decode("ascii"),
                "mimeType": "text/plain",
            },
        )["data"]
        print_json("UPLOAD", {"uploadId": upload["uploadId"], "filename": upload["filename"], "sizeBytes": upload["sizeBytes"]})

        request_id = f"req_generated_linear_smoke_{int(time.time() * 1000)}"
        submitted = http_json(
            "POST",
            args.api_base,
            "/api/v1/runs",
            payload={
                "requestId": request_id,
                "runSpec": {
                    "projectId": "proj_smoke",
                    "pipelineId": "generated-tool-run-v1",
                    "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "input"}],
                    "workflow": {
                        "steps": [
                            {"id": "count_bytes", "tool": {"id": count_tool["id"]}},
                            {"id": "copy_summary", "tool": {"id": copy_tool["id"]}},
                        ],
                    },
                },
            },
            timeout=30,
        )["data"]
        run_id = submitted["runId"]
        print_json("RUN_SUBMITTED", {"runId": run_id, "status": submitted["status"], "stage": submitted["stage"]})

        deadline = time.time() + args.timeout
        final = submitted
        while time.time() < deadline:
            final = http_json("GET", args.api_base, f"/api/v1/runs/{run_id}", timeout=10)["data"]
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

        results = http_json("GET", args.api_base, f"/api/v1/runs/{run_id}/results", timeout=10)["data"]
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
        return 0 if any(str(item.get("path") or "").endswith("copy_summary-final-count.txt") for item in artifacts) else 1
    finally:
        cleanup_tool(args.api_base, count_tool_id)
        cleanup_tool(args.api_base, copy_tool_id)


if __name__ == "__main__":
    raise SystemExit(main())
