#!/usr/bin/env python3
"""Run the minimal end-to-end remote smoke path through the Windows Local API."""

from __future__ import annotations

import argparse
import base64
import sys
import time
from typing import Any

import remote_pipeline_common
import remote_smoke


DEFAULT_API_BASE = remote_smoke.DEFAULT_API_BASE
DEFAULT_PIPELINE_ID = remote_smoke.MINIMAL_PIPELINE_ID


def build_run_submit_payload(
    *,
    request_id: str,
    server_id: str,
    project_id: str,
    pipeline_id: str,
    upload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "requestId": request_id,
        "runSpec": {
            "projectId": project_id,
            "pipelineId": pipeline_id,
            "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "reads"}],
            "params": {"threads": 1},
        },
    }


def response_data(payload: dict[str, Any]) -> Any:
    return remote_pipeline_common.response_data(payload)


def print_json(label: str, payload: Any) -> None:
    remote_pipeline_common.print_json(label, payload)


def http_json(
    method: str,
    api_base: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> Any:
    return remote_pipeline_common.http_json(method, api_base, path, payload=payload, timeout=timeout)


def print_failure(summary: str, *, hints: list[str], detail: str | None = None) -> None:
    remote_pipeline_common.print_failure(summary, hints=hints, detail=detail)


def pipeline_diagnostics(api_base: str, run_id: str | None = None) -> list[str]:
    return remote_pipeline_common.pipeline_diagnostics(api_base, run_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Step 2 of the minimal remote smoke path: run the control-plane bootstrap phase check, then execute "
            f"`{DEFAULT_PIPELINE_ID}` end-to-end through the Local API."
        )
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="Local backend API base URL")
    parser.add_argument("--timeout", type=float, default=120, help="Overall run timeout in seconds")
    parser.add_argument(
        "--pipeline-id",
        default=DEFAULT_PIPELINE_ID,
        help=f"Pipeline to execute. Defaults to the minimal smoke pipeline `{DEFAULT_PIPELINE_ID}`.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(args_list)

    print(f"SMOKE_PATH: control-plane bootstrap readiness/canary/rollback check -> `{args.pipeline_id}` end-to-end execution")
    preflight_exit = remote_smoke.run_control_plane_smoke(args.api_base, 5.0, bootstrap=True)
    if preflight_exit != 0:
        print_failure(
            "control-plane preflight failed; skipping pipeline submission",
            hints=remote_smoke.runner_diagnostics(args.api_base),
        )
        return preflight_exit

    ready, context = remote_smoke.check_local_api(args.api_base, 5.0, bootstrap=False)
    if not ready or not context:
        print_failure(
            "local API did not return a ready server after control-plane preflight",
            hints=remote_smoke.runner_diagnostics(args.api_base),
        )
        return 1
    server_id = str(context["serverId"])

    sample = b"@read1\nACGT\n+\n!!!!\n@read2\nTGCA\n+\n####\n"
    run_id: str | None = None
    try:
        upload = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/uploads",
            payload={
                "filename": "sample.fastq",
                "contentBase64": base64.b64encode(sample).decode("ascii"),
                "mimeType": "text/plain",
            },
        ))
        print_json("UPLOAD", {"uploadId": upload["uploadId"], "filename": upload["filename"], "sizeBytes": upload["sizeBytes"]})

        request_id = f"req_remote_pipeline_smoke_{int(time.time() * 1000)}"
        submitted = response_data(http_json(
            "POST",
            args.api_base,
            "/api/v1/runs",
            payload=build_run_submit_payload(
                request_id=request_id,
                server_id=server_id,
                project_id="proj_smoke",
                pipeline_id=args.pipeline_id,
                upload=upload,
            ),
        ))
        run_id = submitted["runId"]
        print_json("RUN_SUBMITTED", {"runId": run_id, "status": submitted["status"], "stage": submitted["stage"]})

        final = remote_pipeline_common.wait_for_terminal_run(args.api_base, run_id, args.timeout)
        if final.get("status") not in remote_pipeline_common.TERMINAL_RUN_STATUSES:
            print_json(
                "RUN_FINAL",
                {
                    "runId": run_id,
                    "status": final.get("status"),
                    "stage": final.get("stage"),
                    "lastError": final.get("lastError"),
                },
            )
            print_failure(
                f"`{args.pipeline_id}` did not reach a terminal state before timeout",
                detail=f"runId={run_id} timeout={args.timeout}s",
                hints=pipeline_diagnostics(args.api_base, run_id),
            )
            return 1

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
            print_failure(
                f"`{args.pipeline_id}` finished in a non-success state",
                detail=f"runId={run_id} status={final.get('status')} stage={final.get('stage')}",
                hints=pipeline_diagnostics(args.api_base, run_id),
            )
            return 1

        results = response_data(http_json("GET", args.api_base, f"/api/v1/runs/{run_id}/results", timeout=10))
        artifacts = results.get("artifacts") or []
        if not artifacts:
            print_failure(
                "run completed but produced no result artifacts",
                detail=f"runId={run_id}",
                hints=pipeline_diagnostics(args.api_base, run_id),
            )
            return 1

        summary = next((item for item in artifacts if item.get("mimeType") == "text/tab-separated-values"), artifacts[0])
        listed = response_data(http_json("GET", args.api_base, "/api/v1/results", timeout=10))["items"]
        result_id = remote_pipeline_common.result_id_for_run(listed, run_id)
        preview = response_data(http_json(
            "GET",
            args.api_base,
            f"/api/v1/results/{result_id}/preview?artifact_id={summary['artifactId']}",
            timeout=10,
        ))
        preview_table = remote_pipeline_common.preview_table(preview)
        print_json(
            "RESULT_PREVIEW",
            {
                "artifactId": summary["artifactId"],
                "artifactCount": len(artifacts),
                "previewKind": preview_table.get("kind"),
                "columns": preview_table.get("columns"),
                "rows": preview_table.get("rows"),
            },
        )
        print("RESULT: ok")
        return 0
    except Exception as exc:
        print_failure(
            f"minimal pipeline `{args.pipeline_id}` smoke failed",
            detail=str(exc),
            hints=pipeline_diagnostics(args.api_base, run_id),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
