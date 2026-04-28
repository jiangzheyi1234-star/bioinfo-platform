#!/usr/bin/env python3
"""Run a real file-summary pipeline through the Windows Local API."""

from __future__ import annotations

import argparse
import base64
import json
import sys
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


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test file-summary-v1 through the Local API.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()

    sample = b"@read1\nACGT\n+\n!!!!\n@read2\nTGCA\n+\n####\n"
    upload = http_json(
        "POST",
        args.api_base,
        "/api/v1/uploads",
        payload={
            "filename": "sample.fastq",
            "contentBase64": base64.b64encode(sample).decode("ascii"),
            "mimeType": "text/plain",
        },
    )["data"]
    print_json("UPLOAD", {"uploadId": upload["uploadId"], "filename": upload["filename"], "sizeBytes": upload["sizeBytes"]})

    request_id = f"req_file_summary_smoke_{int(time.time() * 1000)}"
    submitted = http_json(
        "POST",
        args.api_base,
        "/api/v1/runs",
        payload={
            "requestId": request_id,
            "runSpec": {
                "projectId": "proj_smoke",
                "pipelineId": "file-summary-v1",
                "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "reads"}],
                "params": {"threads": 1},
            },
        },
    )["data"]
    run_id = submitted["runId"]
    print_json("RUN_SUBMITTED", {"runId": run_id, "status": submitted["status"], "stage": submitted["stage"]})

    deadline = time.time() + args.timeout
    final = submitted
    while time.time() < deadline:
        final = http_json("GET", args.api_base, f"/api/v1/runs/{run_id}", timeout=10)["data"]
        if final["status"] in {"completed", "failed"}:
            break
        time.sleep(1.5)
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
    summary = next((item for item in artifacts if item.get("mimeType") == "text/tab-separated-values"), artifacts[0])
    listed = http_json("GET", args.api_base, "/api/v1/results", timeout=10)["data"]["items"]
    result_id = next(item["resultId"] for item in listed if item["runId"] == run_id)
    preview = http_json(
        "GET",
        args.api_base,
        f"/api/v1/results/{result_id}/preview?artifact_id={summary['artifactId']}",
        timeout=10,
    )["data"]
    print_json(
        "RESULT_PREVIEW",
        {
            "artifactId": summary["artifactId"],
            "artifactCount": len(artifacts),
            "previewKind": (preview.get("preview") or {}).get("kind"),
            "columns": (preview.get("preview") or {}).get("columns"),
            "rows": (preview.get("preview") or {}).get("rows"),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
