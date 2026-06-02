#!/usr/bin/env python3
"""Smoke-test remote reference database registration through the Windows Local API."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from local_api_smoke_helpers import (
    build_upload_submit_payload,
    build_workflow_design_draft,
    build_workflow_design_run_submit_payload,
    create_and_plan_workflow_design,
    prepare_tool_with_job,
    response_data,
    selected_server_id,
    workflow_design_node,
)


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


def connect_ssh():
    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect

    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    result = ssh_connect(
        ip=str(resolved.get("host") or ""),
        port=int(resolved.get("port") or 22),
        user=str(resolved.get("user") or ""),
        password=password,
        key_file=key_file,
        use_agent=auth_mode == "agent",
        timeout=int(resolved.get("timeout_sec") or 5),
    )
    if not result.ok or result.client is None:
        raise RuntimeError(f"SSH failed: {result.message}")
    return result.client


def ssh_run(client, command: str, *, timeout: int = 20) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if exit_code != 0:
        raise RuntimeError(f"SSH command failed ({exit_code}): {err or out}")
    return out.strip()


def cleanup(api_base: str, tool_id: str, database_ids: list[str]) -> None:
    paths = [
        f"/api/v1/tools/{urllib.parse.quote(tool_id, safe='')}",
        *(f"/api/v1/databases/{urllib.parse.quote(database_id, safe='')}" for database_id in database_ids),
    ]
    for path in paths:
        try:
            http_json("DELETE", api_base, path, timeout=10)
        except Exception as exc:
            print_json("CLEANUP_SKIPPED", {"path": path, "error": str(exc)})


def build_run_submit_payload(
    *,
    request_id: str,
    server_id: str,
    upload: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    return build_workflow_design_run_submit_payload(
        request_id=request_id,
        server_id=server_id,
        upload=upload,
        plan=plan,
    )


def build_database_tool_payload(*, tool_id: str, database_id: str) -> dict[str, Any]:
    return {
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
            "commandTemplate": "printf '%s\\n' {config.taxonomy:q} > {output.tool_output:q}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": "tool_output", "path": "database-path.txt", "kind": "log", "mimeType": "text/plain"}],
            "params": {},
            "resources": {
                "threads": {"default": 1},
                "mem_mb": {"default": 128},
                "taxonomy": {
                    "type": "database",
                    "configKey": "taxonomy",
                }
            },
            "log": "logs/coreutils-database-smoke.log",
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["conda-forge::coreutils=9.5"],
                }
            },
            "smokeTest": {
                "inputs": {
                    "primary": {
                        "filename": "reads.txt",
                        "content": "ABCDEF\n",
                        "mimeType": "text/plain",
                    }
                },
                "resourceBindings": {"taxonomy": {"databaseId": database_id}},
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test reference database registration through the Local API.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    tool_id = "conda-forge::coreutils-database-smoke"
    invalid_database_id = "taxonomy-db-real-validation-smoke"
    database_id = "taxonomy-db-custom-smoke"
    client = connect_ssh()
    try:
        server_id = selected_server_id(args.api_base)
        database_path = ssh_run(
            client,
            "set -e; DB=\"$HOME/.h2ometa/smoke-databases/taxonomy-mini\"; "
            "mkdir -p \"$DB\"; "
            "printf 'hash\\n' > \"$DB/hash.k2d\"; "
            "printf 'opts\\n' > \"$DB/opts.k2d\"; "
            "printf 'taxo\\n' > \"$DB/taxo.k2d\"; "
            "printf 'taxonomy\\n' > \"$DB/manifest.txt\"; printf '%s' \"$DB\"",
        )
        print_json("REMOTE_DATABASE_PATH", {"path": database_path})

        invalid_database = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/databases",
            payload={
                "id": invalid_database_id,
                "name": "Taxonomy Real Validation Smoke DB",
                "templateId": "kraken2",
                "version": "smoke",
                "path": database_path,
                "manifestPath": f"{database_path}/manifest.txt",
                "source": "manual",
                "metadata": {"templateId": "kraken2", "buildCommand": "smoke fixture"},
            },
            timeout=30,
        ))
        invalid_checked = response_data(http_json(
            "POST",
            args.api_base,
            f"/api/v1/databases/{urllib.parse.quote(str(invalid_database['id']), safe='')}/check",
            timeout=120,
        ))
        print_json(
            "REAL_DATABASE_VALIDATION_CHECKED",
            {
                "id": invalid_checked["id"],
                "status": invalid_checked["status"],
                "message": invalid_checked["message"],
            },
        )
        if invalid_checked["status"] not in {"failed", "missing"}:
            return 1

        database = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/databases",
            payload={
                "id": database_id,
                "name": "Taxonomy Custom Smoke DB",
                "templateId": "custom",
                "type": "taxonomy",
                "version": "smoke",
                "path": database_path,
                "manifestPath": f"{database_path}/manifest.txt",
                "source": "manual",
                "metadata": {"templateId": "custom", "buildCommand": "smoke fixture"},
            },
            timeout=30,
        ))
        checked = response_data(http_json(
            "POST",
            args.api_base,
            f"/api/v1/databases/{urllib.parse.quote(database_id, safe='')}/check",
            timeout=30,
        ))
        print_json("CUSTOM_DATABASE_CHECKED", {"id": checked["id"], "status": checked["status"], "path": checked["path"]})
        if checked["status"] != "available":
            return 1

        tool = prepare_tool_with_job(
            api_base=args.api_base,
            http_json=http_json,
            payload=build_database_tool_payload(tool_id=tool_id, database_id=database["id"]),
            timeout=args.timeout,
        )
        print_json("TOOL_VALIDATED", {"id": tool["id"], "contract": tool.get("toolContract"), "status": tool["status"]})
        if not bool((tool.get("toolContract") or {}).get("workflowReady")):
            return 1
        draft = build_workflow_design_draft(
            project_id="proj_smoke",
            name="Database smoke",
            input_filename="reads.txt",
            resource_bindings={"taxonomy": {"databaseId": database["id"]}},
            nodes=[
                workflow_design_node(
                    node_id="database_path",
                    tool_id=tool["id"],
                    inputs={"primary": {"fromInput": "input"}},
                )
            ],
            outputs=[{"from": {"nodeId": "database_path", "port": "tool_output"}, "as": "tool_output"}],
        )
        plan = create_and_plan_workflow_design(
            api_base=args.api_base,
            http_json=http_json,
            server_id=server_id,
            draft=draft,
            timeout=args.timeout,
        )
        if not plan.get("valid"):
            print_json("WORKFLOW_DESIGN_PLAN_INVALID", plan)
            return 1

        upload = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/uploads",
            payload=build_upload_submit_payload(
                server_id=server_id,
                filename="reads.txt",
                content_base64=base64.b64encode(b"ABCDEF\n").decode("ascii"),
                mime_type="text/plain",
            ),
            timeout=30,
        ))

        request_id = f"req_database_smoke_{int(time.time() * 1000)}"
        submitted = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/runs",
            payload=build_run_submit_payload(
                request_id=request_id,
                server_id=server_id,
                upload=upload,
                plan=plan,
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
        print_json("RUN_FINAL", {"runId": run_id, "status": final.get("status"), "lastError": final.get("lastError")})
        if final.get("status") != "completed":
            return 1

        results = response_data(http_json("GET", args.api_base, f"/api/v1/runs/{run_id}/results", timeout=10))
        artifact_names = [Path(str(item.get("path") or "")).name for item in (results.get("artifacts") or [])]
        print_json("RUN_ARTIFACTS", {"artifacts": artifact_names})
        return 0 if "database-path.txt" in artifact_names else 1
    finally:
        cleanup(args.api_base, tool_id, [invalid_database_id, database_id])
        try:
            ssh_run(client, "rm -rf \"$HOME/.h2ometa/smoke-databases/taxonomy-mini\"", timeout=20)
        except Exception as exc:
            print_json("REMOTE_CLEANUP_SKIPPED", {"error": str(exc)})
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
