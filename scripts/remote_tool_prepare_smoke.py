#!/usr/bin/env python3
"""Smoke-test the real /api/v1/tools/prepare FastQC path."""

from __future__ import annotations

import argparse
import json
import urllib.parse
from typing import Any

import remote_smoke
from remote_pipeline_common import http_json, print_failure, print_json
from remote_smoke_helpers import response_data_mapping, server_context, server_items_from_payload


DEFAULT_API_BASE = remote_smoke.DEFAULT_API_BASE
DEFAULT_TOOL_ID = "bioconda::fastqc-prepare-smoke"
REQUIRED_PHASES = ("dryRun", "smokeRun", "outputValidation")


def build_fastqc_prepare_payload(tool_id: str = DEFAULT_TOOL_ID) -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": "fastqc",
        "source": "bioconda",
        "sourceLabel": "Bioconda",
        "version": "0.12.1",
        "packageSpec": "bioconda::fastqc=0.12.1",
        "summary": "FastQC quality-control report generation.",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "platforms": ["linux-64"],
        "testCommand": "fastqc --version",
        "ruleTemplate": {
            "commandTemplate": "mkdir -p {output.qc_dir:q} && fastqc {input.reads:q} --outdir {output.qc_dir:q}",
            "inputs": [{"name": "reads", "type": "file", "kind": "sequence", "required": True}],
            "outputs": [
                {
                    "name": "qc_dir",
                    "path": "results/fastqc",
                    "kind": "report",
                    "mimeType": "application/vnd.h2ometa.directory",
                    "directory": True,
                }
            ],
            "params": {},
            "resources": {"threads": {"default": 1}, "mem_mb": {"default": 512}},
            "log": "logs/fastqc-prepare-smoke.log",
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["bioconda::fastqc=0.12.1"],
                }
            },
            "smokeTest": {
                "inputs": {
                    "reads": {
                        "filename": "reads.fastq",
                        "content": "@smoke\nACGT\n+\nFFFF\n",
                        "mimeType": "text/plain",
                    }
                }
            },
        },
    }


def summarize_prepared_tool(payload: dict[str, Any]) -> dict[str, Any]:
    data = response_data_mapping(payload, "tools prepare response")
    contract = _mapping(data.get("toolContract"))
    contract_status = _mapping(data.get("contractStatus"))
    validation = _mapping(contract.get("validation"))
    requirements = _mapping(contract.get("requirements"))
    phases = {
        phase: str(_mapping(contract_status.get(phase) or validation.get(phase)).get("status") or "")
        for phase in ("dryRun", "smokeRun", "outputValidation", "production")
    }
    return {
        "id": str(data.get("id") or ""),
        "status": str(data.get("status") or ""),
        "state": str(contract.get("state") or ""),
        "workflowReady": bool(contract.get("workflowReady")),
        "productionEnabled": bool(requirements.get("productionEnabled")),
        "phases": phases,
        "runIds": _phase_values(contract_status, "runId"),
        "logPaths": _phase_values(contract_status, "logPath"),
        "message": str(data.get("message") or ""),
    }


def prepared_tool_ready(summary: dict[str, Any]) -> bool:
    return (
        bool(summary.get("workflowReady"))
        and summary.get("state") in {"WorkflowReady", "ProductionEnabled"}
        and all(summary.get("phases", {}).get(phase) == "passed" for phase in REQUIRED_PHASES)
    )


def cleanup_tool(api_base: str, tool_id: str) -> None:
    path = f"/api/v1/tools/{urllib.parse.quote(tool_id, safe='')}"
    try:
        http_json("DELETE", api_base, path, timeout=10)
    except Exception as exc:
        print_json("TOOL_PREPARE_CLEANUP_SKIPPED", {"id": tool_id, "error": str(exc)})


def check_local_api_ready(api_base: str) -> bool:
    try:
        health = http_json("GET", api_base, "/health", timeout=5)
        servers_payload = http_json("GET", api_base, "/api/v1/servers", timeout=10)
        items = server_items_from_payload(servers_payload)
    except Exception as exc:
        print_failure(
            "local API preflight failed before tools/prepare smoke",
            hints=remote_smoke.local_api_diagnostics(api_base),
            detail=str(exc),
        )
        return False
    if not items:
        print_failure(
            "local API returned no registered servers",
            hints=[f"Inspect `{api_base.rstrip('/')}/api/v1/servers` before rerunning the tools/prepare smoke."],
        )
        return False

    selected = items[0]
    context = server_context(selected, stale_port=remote_smoke.FIXED_STALE_PORT)
    health_data = _mapping(selected.get("health"))
    ready = _mapping(health_data.get("ready"))
    workflow_runtime = _mapping(health_data.get("workflowRuntime"))
    summary = {
        **context,
        "localApiStatus": str(_mapping(health).get("status") or ""),
        "readyOk": bool(ready.get("ok")),
        "workflowRuntimeOk": bool(workflow_runtime.get("ok")),
        "workflowRuntimeSource": str(workflow_runtime.get("source") or ""),
        "snakemakeVersion": str(workflow_runtime.get("snakemakeVersion") or ""),
        "runnerVersion": str(selected.get("runnerVersion") or ""),
        "runnerMode": str(selected.get("runnerMode") or ""),
    }
    print_json("SERVER_SELECTED", summary)
    if not bool(summary["connected"]) or not bool(summary["ready"]) or not bool(summary["readyOk"]):
        print_failure(
            "selected server is not ready for tools/prepare smoke",
            hints=remote_smoke.runner_diagnostics(api_base, str(summary["serverId"] or "")),
            detail=json.dumps(summary, ensure_ascii=False, sort_keys=True),
        )
        return False
    return True


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _phase_values(status: dict[str, Any], key: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for phase in REQUIRED_PHASES:
        value = _mapping(status.get(phase)).get(key)
        if value:
            values[phase] = str(value)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test FastQC through POST /api/v1/tools/prepare.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--tool-id", default=DEFAULT_TOOL_ID)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--keep-tool", action="store_true")
    args = parser.parse_args()

    if not args.skip_preflight:
        if not check_local_api_ready(args.api_base):
            return 1

    payload = build_fastqc_prepare_payload(args.tool_id)
    print_json(
        "TOOL_PREPARE_REQUEST",
        {
            "id": payload["id"],
            "packageSpec": payload["packageSpec"],
            "path": "/api/v1/tools/prepare",
            "targetPlatform": payload["targetPlatform"],
        },
    )
    try:
        response = http_json("POST", args.api_base, "/api/v1/tools/prepare", payload=payload, timeout=args.timeout)
        summary = summarize_prepared_tool(response)
        print_json("TOOL_PREPARE_RESULT", summary)
        if not prepared_tool_ready(summary):
            print_failure(
                "tools/prepare did not produce a WorkflowReady FastQC tool",
                hints=remote_smoke.runner_diagnostics(args.api_base),
                detail=json.dumps(summary, ensure_ascii=False, sort_keys=True),
            )
            return 1
        print("RESULT: ok")
        return 0
    except Exception as exc:
        print_failure(
            "tools/prepare smoke failed",
            hints=remote_smoke.runner_diagnostics(args.api_base),
            detail=str(exc),
        )
        return 1
    finally:
        if not args.keep_tool:
            cleanup_tool(args.api_base, args.tool_id)


if __name__ == "__main__":
    raise SystemExit(main())
