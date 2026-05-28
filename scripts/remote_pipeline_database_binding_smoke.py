#!/usr/bin/env python3
"""Run a normal Snakemake pipeline with a database resource binding."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from typing import Any

import remote_pipeline_smoke
import remote_smoke


DEFAULT_PIPELINE_ID = "database-backed-analysis-v1"
DEFAULT_RESOURCE_KEY = "reference_database"


def database_matches_resource(database: dict[str, Any], resource_spec: dict[str, Any]) -> bool:
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    template_id = str(metadata.get("templateId") or database.get("templateId") or "").strip()
    accepted_templates = [str(item).strip() for item in resource_spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates and template_id not in accepted_templates:
        return False
    accepted_capabilities = [str(item).strip() for item in resource_spec.get("acceptedCapabilities") or [] if str(item).strip()]
    capabilities = metadata.get("capabilities") if isinstance(metadata.get("capabilities"), list) else []
    if accepted_capabilities and not any(item in capabilities for item in accepted_capabilities):
        return False
    return True


def _select_database(databases: list[dict[str, Any]], database_id: str, resource_spec: dict[str, Any]) -> dict[str, Any] | None:
    available = [item for item in databases if item.get("status") == "available"]
    if database_id:
        return next((item for item in available if item.get("id") == database_id and database_matches_resource(item, resource_spec)), None)
    return next((item for item in available if database_matches_resource(item, resource_spec)), None)


def build_run_submit_payload(
    *,
    request_id: str,
    server_id: str,
    project_id: str,
    pipeline_id: str,
    resource_key: str,
    upload: dict[str, Any],
    database: dict[str, Any],
) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "requestId": request_id,
        "idempotencyKey": request_id,
        "runSpec": {
            "projectId": project_id,
            "pipelineId": pipeline_id,
            "inputs": [
                {
                    "uploadId": upload["uploadId"],
                    "filename": upload["filename"],
                    "role": "reads",
                }
            ],
            "params": {"identity_threshold": 0.97},
            "resourceBindings": {resource_key: {"databaseId": database["id"]}},
        },
    }


def _wait_for_terminal_run(api_base: str, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] = {}
    while time.time() < deadline:
        final = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json("GET", api_base, f"/api/v1/runs/{run_id}", timeout=10)
        )
        if final.get("status") in {"completed", "failed"}:
            return final
        time.sleep(1.5)
    return final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute a normal bundled Snakemake pipeline with runSpec.resourceBindings. "
            "This validates the same database-resource contract used by workflow bundle import."
        )
    )
    parser.add_argument("--api-base", default=remote_smoke.DEFAULT_API_BASE, help="Local backend API base URL")
    parser.add_argument("--timeout", type=float, default=120, help="Run timeout in seconds")
    parser.add_argument("--pipeline-id", default=DEFAULT_PIPELINE_ID, help="Pipeline to execute")
    parser.add_argument("--resource-key", default=DEFAULT_RESOURCE_KEY, help="Pipeline resource key to bind")
    parser.add_argument("--database-id", default="", help="Specific available database id to bind")
    parser.add_argument("--skip-control-plane-smoke", action="store_true", help="Skip remote_smoke preflight")
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    remote_smoke.abort_for_wsl("remote_pipeline_database_binding_smoke.py", args_list)
    args = build_parser().parse_args(args_list)

    if not args.skip_control_plane_smoke:
        preflight_exit = remote_smoke.run_control_plane_smoke(args.api_base, 5.0, bootstrap=True)
        if preflight_exit != 0:
            remote_pipeline_smoke.print_failure(
                "control-plane preflight failed; skipping database-bound pipeline submission",
                hints=remote_smoke.runner_diagnostics(args.api_base),
            )
            return preflight_exit

    ready, context = remote_smoke.check_local_api(args.api_base, 5.0, bootstrap=False)
    if not ready or not context:
        remote_pipeline_smoke.print_failure(
            "local API did not return a ready server",
            hints=remote_smoke.runner_diagnostics(args.api_base),
        )
        return 1
    server_id = str(context["serverId"])

    try:
        catalog = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json("GET", args.api_base, "/api/v1/workflow-catalog?refresh=true", timeout=10)
        )
        workflow = next((item for item in catalog.get("items", []) if item.get("id") == args.pipeline_id), None)
        if not workflow:
            raise RuntimeError(f"pipeline not found in catalog: {args.pipeline_id}")
        resources = workflow.get("resources") or {}
        if args.resource_key not in resources:
            raise RuntimeError(f"pipeline resource not found: {args.resource_key}")
        resource_spec = resources[args.resource_key]

        databases = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json("GET", args.api_base, "/api/v1/databases?refresh=true", timeout=10)
        ).get("items", [])
        database = _select_database(databases, args.database_id, resource_spec)
        if not database:
            raise RuntimeError("no matching available database found; add or verify a database before running this smoke")

        sample = b"@resource-bound-read\nACGTACGT\n+\n!!!!!!!!\n"
        upload = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json(
                "POST",
                args.api_base,
                "/api/v1/uploads",
                payload={
                    "filename": "database-bound-sample.fastq",
                    "contentBase64": base64.b64encode(sample).decode("ascii"),
                    "mimeType": "text/plain",
                },
                timeout=30,
            )
        )
        request_id = f"req_database_binding_smoke_{int(time.time() * 1000)}"
        submitted = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json(
                "POST",
                args.api_base,
                "/api/v1/runs",
                payload=build_run_submit_payload(
                    request_id=request_id,
                    server_id=server_id,
                    project_id="proj_database_binding_smoke",
                    pipeline_id=args.pipeline_id,
                    resource_key=args.resource_key,
                    upload=upload,
                    database=database,
                ),
                timeout=30,
            )
        )
        run_id = submitted["runId"]
        remote_pipeline_smoke.print_json(
            "DATABASE_BOUND_RUN_SUBMITTED",
            {
                "runId": run_id,
                "pipelineId": args.pipeline_id,
                "resourceKey": args.resource_key,
                "databaseId": database["id"],
            },
        )

        final = _wait_for_terminal_run(args.api_base, run_id, args.timeout)
        remote_pipeline_smoke.print_json(
            "DATABASE_BOUND_RUN_FINAL",
            {"runId": run_id, "status": final.get("status"), "stage": final.get("stage"), "lastError": final.get("lastError")},
        )
        if final.get("status") != "completed":
            remote_pipeline_smoke.print_failure(
                "database-bound normal pipeline did not complete",
                detail=f"runId={run_id} status={final.get('status')} stage={final.get('stage')}",
                hints=remote_pipeline_smoke.pipeline_diagnostics(args.api_base, run_id),
            )
            return 1

        results = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json("GET", args.api_base, f"/api/v1/runs/{run_id}/results", timeout=10)
        )
        artifacts = results.get("artifacts") or []
        table = next((item for item in artifacts if item.get("mimeType") == "text/tab-separated-values"), None)
        if not table:
            raise RuntimeError("run completed but classified TSV artifact is missing")
        listed = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json("GET", args.api_base, "/api/v1/results", timeout=10)
        )["items"]
        result_id = next(item["resultId"] for item in listed if item["runId"] == run_id)
        preview = remote_pipeline_smoke.response_data(
            remote_pipeline_smoke.http_json(
                "GET",
                args.api_base,
                f"/api/v1/results/{result_id}/preview?artifact_id={table['artifactId']}",
                timeout=10,
            )
        )
        rows = (preview.get("preview") or {}).get("rows") or []
        if not any(database["id"] in cell for row in rows for cell in row):
            raise RuntimeError("classified TSV preview does not include the bound database id")
        remote_pipeline_smoke.print_json(
            "DATABASE_BOUND_RESULT_PREVIEW",
            {
                "artifactId": table["artifactId"],
                "artifactCount": len(artifacts),
                "databaseId": database["id"],
                "columns": (preview.get("preview") or {}).get("columns"),
                "rows": rows[:3],
            },
        )
        print("RESULT: ok")
        return 0
    except Exception as exc:
        remote_pipeline_smoke.print_failure(
            "database-bound normal pipeline smoke failed",
            detail=str(exc),
            hints=remote_pipeline_smoke.pipeline_diagnostics(args.api_base),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
