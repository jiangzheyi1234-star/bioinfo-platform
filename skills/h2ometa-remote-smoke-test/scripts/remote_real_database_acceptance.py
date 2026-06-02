#!/usr/bin/env python3
"""Validate production database template acceptance through the Local API.

This script is intentionally stricter than the generic all-database Snakemake
smoke: it fails when required templates are missing, declared-only, missing
probe metadata, or missing the stable metadata contract needed by generated
workflows.
"""

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

from local_api_smoke_helpers import (
    build_upload_submit_payload,
    build_workflow_design_draft,
    build_workflow_design_run_submit_payload,
    create_and_plan_workflow_design,
    prepare_tool_with_job,
    selected_server_id,
    workflow_design_node,
)


PRODUCTION_TEMPLATE_IDS = [
    "kraken2",
    "bracken",
    "blast",
    "diamond",
    "bowtie2",
    "bwa",
    "minimap2",
    "hisat2",
    "star",
    "salmon",
    "kallisto",
    "ncbi_taxonomy",
    "metaphlan",
    "centrifuge",
    "kaiju",
    "gtdbtk",
    "interproscan",
    "silva_qiime",
    "sourmash",
    "mmseqs2",
    "hmmer_pfam",
    "checkm",
    "humann",
    "card_rgi",
    "eggnog_mapper",
]


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", flush=True)


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


def api_data(response: dict[str, Any]) -> Any:
    data = response["data"]
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return data


def template_id_for_database(database: dict[str, Any]) -> str:
    return str((database.get("metadata") or {}).get("templateId") or database.get("templateId") or "").strip().lower()


def role_for_template(template_id: str, index: int) -> str:
    role = re.sub(r"[^a-zA-Z0-9_]+", "_", template_id).strip("_").lower()
    if not role:
        role = f"db{index}"
    if role[0].isdigit():
        role = f"db_{role}"
    return role


def _resolved_value(metadata: dict[str, Any], path_kind: str) -> Any:
    resolved = metadata.get("resolved") if isinstance(metadata.get("resolved"), dict) else {}
    resolved_path = metadata.get("resolvedPath") if isinstance(metadata.get("resolvedPath"), dict) else {}
    if path_kind == "composite":
        return resolved or resolved_path.get("entries") or {}
    return str(resolved_path.get("prefix") or resolved_path.get("path") or resolved.get("default") or "").strip()


def validate_database_contract(database: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    template_id = str(template.get("id") or "").strip().lower()
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    path_kind = str(template.get("pathKind") or metadata.get("pathMode") or "").strip()
    issues: list[str] = []

    if database.get("status") != "available":
        issues.append(f"status is {database.get('status') or 'unknown'}")
    if template_id_for_database(database) != template_id:
        issues.append(f"metadata.templateId is {template_id_for_database(database) or 'missing'}")

    input_metadata = metadata.get("input")
    if not isinstance(input_metadata, dict):
        issues.append("metadata.input missing")
    elif path_kind == "composite":
        fields = input_metadata.get("fields")
        if input_metadata.get("kind") != "multi" or not isinstance(fields, dict) or not fields:
            issues.append("metadata.input.fields missing for composite template")
    elif not str(input_metadata.get("path") or "").strip():
        issues.append("metadata.input.path missing")

    resolved_path = metadata.get("resolvedPath")
    if not isinstance(resolved_path, dict):
        issues.append("metadata.resolvedPath missing")
    elif path_kind and str(resolved_path.get("kind") or path_kind) != path_kind:
        issues.append(f"metadata.resolvedPath.kind is {resolved_path.get('kind') or 'missing'}")

    resolved_value = _resolved_value(metadata, path_kind)
    if path_kind == "composite":
        required_fields = set((template.get("fields") or {}).keys())
        resolved_fields = set(resolved_value.keys()) if isinstance(resolved_value, dict) else set()
        if not resolved_fields:
            issues.append("metadata.resolved missing for composite template")
        missing_fields = sorted(required_fields - resolved_fields)
        if missing_fields:
            issues.append(f"metadata.resolved missing fields: {', '.join(missing_fields)}")
    elif not resolved_value:
        issues.append("metadata.resolved default path missing")

    return {
        "id": database.get("id"),
        "templateId": template_id,
        "status": "accepted" if not issues else "rejected",
        "issues": issues,
        "pathKind": path_kind,
        "inputPath": metadata.get("inputPath") or database.get("path"),
        "resolvedValue": resolved_value,
    }


def build_acceptance_scope(
    *,
    templates: list[dict[str, Any]],
    databases: list[dict[str, Any]],
    required_templates: list[str],
) -> dict[str, Any]:
    template_by_id = {str(item.get("id") or "").strip().lower(): item for item in templates}
    required = [str(item).strip().lower() for item in required_templates if str(item).strip()]
    database_by_template: dict[str, dict[str, Any]] = {}
    duplicates: dict[str, list[str]] = {}
    for database in databases:
        template_id = template_id_for_database(database)
        if not template_id or template_id not in required:
            continue
        if template_id in database_by_template:
            duplicates.setdefault(template_id, [str(database_by_template[template_id].get("id") or "")]).append(str(database.get("id") or ""))
            continue
        database_by_template[template_id] = database

    missing_templates = [template_id for template_id in required if template_id not in template_by_id or template_id not in database_by_template]
    selected_template_ids = [template_id for template_id in required if template_id in database_by_template and template_id in template_by_id]
    return {
        "ok": not missing_templates and not duplicates,
        "requiredTemplates": required,
        "missingTemplates": missing_templates,
        "duplicateTemplates": duplicates,
        "selectedTemplateIds": selected_template_ids,
        "selectedDatabases": [database_by_template[template_id] for template_id in selected_template_ids],
    }


def wait_for_run(api_base: str, run_id: str, *, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    final: dict[str, Any] = {}
    while time.time() < deadline:
        final = api_data(http_json("GET", api_base, f"/api/v1/runs/{run_id}", timeout=10))
        if final.get("status") in {"completed", "failed"}:
            return final
        time.sleep(2)
    return final


def cleanup_tool(api_base: str, tool_id: str) -> None:
    try:
        http_json("DELETE", api_base, f"/api/v1/tools/{urllib.parse.quote(tool_id, safe='')}", timeout=10)
    except Exception as exc:
        print_json("ACCEPTANCE_TOOL_CLEANUP_SKIPPED", {"id": tool_id, "error": str(exc)})


def build_database_tool_payload(
    *,
    tool_id: str,
    role: str,
    database: dict[str, Any],
    output_name: str,
) -> dict[str, Any]:
    template_id = template_id_for_database(database)
    resource_spec: dict[str, Any] = {
        "type": "database",
        "configKey": role,
    }
    if template_id:
        resource_spec["acceptedTemplates"] = [template_id]
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
            "commandTemplate": f"printf '%s\\n' {{config.{role}:q}} > {{output.database_path:q}}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": "database_path", "path": output_name, "kind": "log", "mimeType": "text/plain"}],
            "params": {},
            "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}, role: resource_spec},
            "log": f"logs/coreutils-real-db-acceptance-{role}.log",
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": ["conda-forge::coreutils=9.5"],
                }
            },
            "smokeTest": {
                "inputs": {
                    "primary": {
                        "filename": f"real-db-acceptance-{role}.txt",
                        "content": "database acceptance smoke\n",
                        "mimeType": "text/plain",
                    }
                },
                "resourceBindings": {role: {"databaseId": str(database["id"]), "templateId": template_id}},
            },
        },
    }


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


def build_production_acceptance_payload(
    *,
    run_id: str,
    database: dict[str, Any],
    role: str,
    template_id: str,
    artifact_name: str,
) -> dict[str, Any]:
    database_id = str(database.get("id") or "")
    label = template_id or role
    return {
        "runId": run_id,
        "evidenceType": "real-database-acceptance",
        "databaseId": database_id,
        "templateId": template_id,
        "role": role,
        "artifactName": artifact_name,
        "message": f"Accepted {label} database {database_id} in real database acceptance Snakemake run.",
    }


def run_snakemake_injection_smoke(
    api_base: str,
    database: dict[str, Any],
    *,
    server_id: str,
    index: int,
    timeout: float,
    keep_production_tools: bool,
) -> dict[str, Any]:
    template_id = template_id_for_database(database)
    role = role_for_template(template_id, index)
    tool_id = f"conda-forge::coreutils-real-db-acceptance-{role}-{index}"
    output_name = f"real-database-{role}-path.txt"
    keep_tool = False
    try:
        tool = prepare_tool_with_job(
            api_base=api_base,
            http_json=http_json,
            payload=build_database_tool_payload(tool_id=tool_id, role=role, database=database, output_name=output_name),
            timeout=timeout,
        )
        if not bool((tool.get("toolContract") or {}).get("workflowReady")):
            return {
                "id": database.get("id"),
                "templateId": template_id,
                "role": role,
                "status": "failed",
                "error": f"tool contract validation failed: {tool.get('toolContract')}",
            }
        draft = build_workflow_design_draft(
            project_id="proj_real_database_acceptance",
            name=f"Real database acceptance {role}",
            input_filename=f"real-db-acceptance-{role}.txt",
            resource_bindings={role: {"databaseId": database["id"], "templateId": template_id_for_database(database)}},
            nodes=[
                workflow_design_node(
                    node_id="database_path",
                    tool_id=tool["id"],
                    inputs={"primary": {"fromInput": "input"}},
                )
            ],
            outputs=[{"from": {"nodeId": "database_path", "port": "database_path"}, "as": "database_path"}],
        )
        plan = create_and_plan_workflow_design(
            api_base=api_base,
            http_json=http_json,
            server_id=server_id,
            draft=draft,
            timeout=timeout,
        )
        if not plan.get("valid"):
            return {
                "id": database.get("id"),
                "templateId": template_id,
                "role": role,
                "status": "failed",
                "error": f"workflow design plan failed: {plan.get('validationIssues')}",
            }
        upload = api_data(http_json(
            "POST",
            api_base,
            "/api/v1/uploads",
            payload=build_upload_submit_payload(
                server_id=server_id,
                filename=f"real-db-acceptance-{role}.txt",
                content_base64=base64.b64encode(b"database acceptance smoke\n").decode("ascii"),
                mime_type="text/plain",
            ),
            timeout=30,
        ))
        submitted = api_data(http_json(
            "POST",
            api_base,
            "/api/v1/runs",
            payload=build_run_submit_payload(
                request_id=f"req_real_db_acceptance_{index}_{int(time.time() * 1000)}",
                server_id=server_id,
                upload=upload,
                plan=plan,
            ),
            timeout=30,
        ))
        final = wait_for_run(api_base, submitted["runId"], timeout=timeout)
        result = {
            "id": database.get("id"),
            "templateId": template_id,
            "role": role,
            "runId": submitted["runId"],
            "status": final.get("status"),
            "lastError": final.get("lastError"),
        }
        if final.get("status") != "completed":
            return result
        results = api_data(http_json("GET", api_base, f"/api/v1/runs/{submitted['runId']}/results", timeout=10))
        artifact_names = [Path(str(item.get("path") or "")).name for item in (results.get("artifacts") or [])]
        result["artifactNames"] = artifact_names
        if output_name not in artifact_names:
            result["status"] = "failed"
            return result
        production = api_data(http_json(
            "POST",
            api_base,
            f"/api/v1/tools/{urllib.parse.quote(tool_id, safe='')}/production",
            payload=build_production_acceptance_payload(
                run_id=submitted["runId"],
                database=database,
                role=role,
                template_id=template_id,
                artifact_name=output_name,
            ),
            timeout=30,
        ))
        contract = production.get("toolContract") if isinstance(production.get("toolContract"), dict) else {}
        production_status = (production.get("contractStatus") or {}).get("production") or {}
        result["productionState"] = contract.get("state")
        result["productionStatus"] = production_status.get("status")
        if contract.get("state") != "ProductionEnabled" or production_status.get("status") != "passed":
            result["status"] = "failed"
            result["error"] = "production acceptance evidence was not recorded"
            return result
        result["status"] = "completed"
        if keep_production_tools and contract.get("state") == "ProductionEnabled":
            keep_tool = True
            result["retainedToolId"] = tool_id
        return result
    except Exception as exc:
        return {"id": database.get("id"), "templateId": template_id, "status": "failed", "error": str(exc)}
    finally:
        if not keep_tool:
            cleanup_tool(api_base, tool_id)


def parse_template_list(values: list[str], *, default: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip().lower() for item in value.split(",") if item.strip())
    return parsed or default


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate real registered databases against the production template contract.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--template", action="append", default=[], help="Required template id. Can be repeated or comma-separated.")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--skip-snakemake", action="store_true", help="Only validate template coverage, status, probe, and metadata contract.")
    parser.add_argument("--rerun-check", action="store_true", help="POST /databases/{id}/check before validating metadata.")
    parser.add_argument("--keep-production-tools", action="store_true", help="Keep accepted generated smoke tools so their ProductionEnabled evidence remains queryable.")
    args = parser.parse_args()

    required_templates = parse_template_list(args.template, default=PRODUCTION_TEMPLATE_IDS)
    templates = api_data(http_json("GET", args.api_base, "/api/v1/database-templates", timeout=30))["items"]
    databases = api_data(http_json("GET", args.api_base, "/api/v1/databases", timeout=30))["items"]
    scope = build_acceptance_scope(templates=templates, databases=databases, required_templates=required_templates)
    print_json("REAL_DATABASE_ACCEPTANCE_SCOPE", {k: v for k, v in scope.items() if k != "selectedDatabases"})

    template_by_id = {str(item.get("id") or "").strip().lower(): item for item in templates}
    selected_databases = list(scope["selectedDatabases"])
    if args.rerun_check:
        refreshed = []
        for database in selected_databases:
            checked = api_data(http_json("POST", args.api_base, f"/api/v1/databases/{urllib.parse.quote(str(database['id']), safe='')}/check", timeout=1800))
            refreshed.append(checked)
            print_json("REAL_DATABASE_RERUN_CHECK", {"id": checked.get("id"), "templateId": template_id_for_database(checked), "status": checked.get("status")})
        selected_databases = refreshed

    contract_results = [
        validate_database_contract(database, template_by_id[template_id_for_database(database)])
        for database in selected_databases
        if template_id_for_database(database) in template_by_id
    ]
    for result in contract_results:
        print_json("REAL_DATABASE_CONTRACT_RESULT", result)

    snakemake_results: list[dict[str, Any]] = []
    if not args.skip_snakemake:
        server_id = selected_server_id(args.api_base)
        accepted_by_id = {item["id"] for item in contract_results if item.get("status") == "accepted"}
        for index, database in enumerate(selected_databases, start=1):
            if database.get("id") not in accepted_by_id:
                continue
            result = run_snakemake_injection_smoke(
                args.api_base,
                database,
                server_id=server_id,
                index=index,
                timeout=args.timeout,
                keep_production_tools=args.keep_production_tools,
            )
            snakemake_results.append(result)
            print_json("REAL_DATABASE_SNAKEMAKE_RESULT", result)

    rejected = [item for item in contract_results if item.get("status") != "accepted"]
    failed_snakemake = [item for item in snakemake_results if item.get("status") != "completed"]
    summary = {
        "required": len(required_templates),
        "selected": len(selected_databases),
        "contractAccepted": len(contract_results) - len(rejected),
        "contractRejected": len(rejected),
        "snakemakeCompleted": len(snakemake_results) - len(failed_snakemake),
        "snakemakeFailed": len(failed_snakemake),
        "missingTemplates": scope["missingTemplates"],
        "duplicateTemplates": scope["duplicateTemplates"],
    }
    print_json("REAL_DATABASE_ACCEPTANCE_SUMMARY", summary)
    return 0 if scope["ok"] and not rejected and not failed_snakemake else 1


if __name__ == "__main__":
    raise SystemExit(main())
