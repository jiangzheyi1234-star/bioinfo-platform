#!/usr/bin/env python3
"""Run built-in WorkflowReady tools as real generated Snakemake workflows."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
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
    response_data,
    selected_server_id,
    workflow_design_edge,
    workflow_design_node,
)


DEFAULT_PROFILES = ("fastp", "fastqc", "multiqc", "seqkit-stats")
READY_STATES = {"WorkflowReady", "ProductionEnabled"}


def http_json(
    method: str,
    api_base: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
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
        raise RuntimeError(f"HTTP {exc.code} {path}: {raw}") from exc


def fetch_profiles(api_base: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        payload = response_data(
            http_json(
                "GET",
                api_base,
                f"/api/v1/tool-capabilities/tool-profiles?page={page}&pageSize=100",
            )
        )
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                result[str(item.get("profileId") or "")] = item
        if not payload.get("hasMore"):
            return result
        page += 1


def fetch_ready_tool(api_base: str, profile: dict[str, Any]) -> dict[str, Any]:
    prepare_payload = _required_dict(profile, "preparePayload")
    tool_id = _required_text(prepare_payload, "id")
    query = urllib.parse.urlencode({"query": tool_id, "limit": 100, "offset": 0})
    payload = response_data(http_json("GET", api_base, f"/api/v1/tools/index?{query}"))
    tool = next(
        (
            item
            for item in payload.get("items") or []
            if isinstance(item, dict) and str(item.get("toolId") or "") == tool_id
        ),
        None,
    )
    if not isinstance(tool, dict):
        raise RuntimeError(f"WORKFLOW_READY_TOOL_NOT_FOUND: {tool_id}")
    state = str((tool.get("facets") or {}).get("state") or "")
    if state not in READY_STATES:
        raise RuntimeError(f"WORKFLOW_READY_TOOL_REQUIRED: {tool_id} state={state}")
    if not str(tool.get("latestStableRevisionId") or ""):
        raise RuntimeError(f"TOOL_REVISION_REQUIRED: {tool_id}")
    return tool


def run_profile(
    *,
    api_base: str,
    server_id: str,
    profile: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    profile_id = _required_text(profile, "profileId")
    prepare_payload = _required_dict(profile, "preparePayload")
    rule = _required_dict(prepare_payload, "ruleTemplate")
    outputs = [item for item in rule.get("outputs") or [] if isinstance(item, dict)]
    if not outputs:
        raise RuntimeError(f"DECLARED_OUTPUT_REQUIRED: {profile_id}")
    tool = fetch_ready_tool(api_base, profile)
    revision_id = _required_text(tool, "latestStableRevisionId")
    case = build_execution_case(
        api_base=api_base,
        profile=profile,
        profiles=profiles,
        tool_revision_id=revision_id,
    )
    fixture = case["fixture"]
    filename = _required_text(fixture, "filename")
    fixture_bytes = _fixture_bytes(profile_id, fixture)
    mime_type = str(fixture.get("mimeType") or "application/octet-stream")
    draft = build_workflow_design_draft(
        project_id="proj_builtin_tool_execution_acceptance",
        name=f"Built-in tool execution acceptance: {profile_id}",
        input_filename=filename,
        nodes=case["nodes"],
        edges=case["edges"],
        outputs=[
            {
                "from": {"nodeId": case["outputNodeId"], "port": _required_text(item, "name")},
                "as": _required_text(item, "name"),
            }
            for item in outputs
        ],
    )
    plan = create_and_plan_workflow_design(
        api_base=api_base,
        http_json=http_json,
        server_id=server_id,
        draft=draft,
        timeout=timeout,
    )
    if not plan.get("valid"):
        raise RuntimeError(f"WORKFLOW_DESIGN_PLAN_INVALID: {profile_id}: {plan.get('validationIssues')}")
    upload = response_data(
        http_json(
            "POST",
            api_base,
            "/api/v1/uploads",
            payload=build_upload_submit_payload(
                server_id=server_id,
                filename=filename,
                content_base64=base64.b64encode(fixture_bytes).decode("ascii"),
                mime_type=mime_type,
            ),
        )
    )
    request_id = f"req_builtin_tool_{profile_id.replace('-', '_')}_{int(time.time() * 1000)}"
    submitted = response_data(
        http_json(
            "POST",
            api_base,
            "/api/v1/runs",
            payload=build_workflow_design_run_submit_payload(
                request_id=request_id,
                server_id=server_id,
                upload=upload,
                plan=plan,
            ),
        )
    )
    run_id = _required_text(submitted, "runId")
    final = wait_for_run(api_base, run_id=run_id, timeout=timeout)
    if final.get("status") != "completed":
        raise RuntimeError(f"RUN_FAILED: {profile_id}: {final.get('lastError') or final.get('message')}")
    results = response_data(http_json("GET", api_base, f"/api/v1/runs/{run_id}/results"))
    validated_artifacts = validated_output_artifacts(profile_id=profile_id, outputs=outputs, results=results)
    expected_keys = sorted(_required_text(item, "name") for item in outputs)
    return {
        "profileId": profile_id,
        "toolId": tool.get("toolId"),
        "toolRevisionId": revision_id,
        "dependencyToolRevisionIds": case["dependencyToolRevisionIds"],
        "contractState": (tool.get("facets") or {}).get("state"),
        "runId": run_id,
        "status": "completed",
        "expectedArtifactKeys": expected_keys,
        "artifacts": validated_artifacts,
        "productionEvidenceSubmitted": False,
    }


def validated_output_artifacts(
    *,
    profile_id: str,
    outputs: list[dict[str, Any]],
    results: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_keys = {_required_text(item, "name") for item in outputs}
    artifacts = {
        str(item.get("artifactId") or ""): item
        for item in results.get("artifacts") or []
        if isinstance(item, dict) and str(item.get("artifactId") or "")
    }
    artifacts_by_key: dict[str, dict[str, Any]] = {}
    for edge in results.get("lineageEdges") or []:
        if not isinstance(edge, dict):
            continue
        payload = edge.get("payload") if isinstance(edge.get("payload"), dict) else {}
        key = str(payload.get("artifactKey") or "").strip()
        artifact = artifacts.get(str(payload.get("artifactId") or "").strip())
        if key in expected_keys and artifact is not None:
            artifacts_by_key[key] = artifact
    missing = sorted(expected_keys - set(artifacts_by_key))
    if missing:
        raise RuntimeError(f"EXPECTED_OUTPUT_KEYS_MISSING: {profile_id}: {missing}")
    empty = sorted(key for key, artifact in artifacts_by_key.items() if int(artifact.get("sizeBytes") or 0) <= 0)
    if empty:
        raise RuntimeError(f"EXPECTED_OUTPUTS_EMPTY: {profile_id}: {empty}")
    return [
        {
            "key": key,
            "name": Path(str(artifacts_by_key[key].get("path") or "")).name,
            "sizeBytes": int(artifacts_by_key[key].get("sizeBytes") or 0),
            "mimeType": artifacts_by_key[key].get("mimeType"),
        }
        for key in sorted(artifacts_by_key)
    ]


def build_execution_case(
    *,
    api_base: str,
    profile: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    tool_revision_id: str,
) -> dict[str, Any]:
    profile_id = _required_text(profile, "profileId")
    rule = _required_dict(_required_dict(profile, "preparePayload"), "ruleTemplate")
    smoke = _required_dict(rule, "smokeTest")
    if profile_id != "multiqc":
        input_name, fixture = _single_smoke_input(profile_id, smoke)
        node_id = f"run_{profile_id.replace('-', '_')}"
        return {
            "fixture": fixture,
            "nodes": [
                workflow_design_node(
                    node_id=node_id,
                    tool_revision_id=tool_revision_id,
                    inputs={input_name: {"fromInput": "input"}},
                    params=dict(smoke.get("params") or {}),
                )
            ],
            "edges": [],
            "outputNodeId": node_id,
            "dependencyToolRevisionIds": [],
        }

    fastqc_profile = profiles.get("fastqc")
    if not isinstance(fastqc_profile, dict):
        raise RuntimeError("MULTIQC_ACCEPTANCE_REQUIRES_FASTQC_PROFILE")
    fastqc_rule = _required_dict(_required_dict(fastqc_profile, "preparePayload"), "ruleTemplate")
    fastqc_smoke = _required_dict(fastqc_rule, "smokeTest")
    fastqc_input, fixture = _single_smoke_input("fastqc", fastqc_smoke)
    fastqc_tool = fetch_ready_tool(api_base, fastqc_profile)
    fastqc_revision_id = _required_text(fastqc_tool, "latestStableRevisionId")
    return {
        "fixture": fixture,
        "nodes": [
            workflow_design_node(
                node_id="run_fastqc",
                tool_revision_id=fastqc_revision_id,
                inputs={fastqc_input: {"fromInput": "input"}},
                params=dict(fastqc_smoke.get("params") or {}),
            ),
            workflow_design_node(
                node_id="run_multiqc",
                tool_revision_id=tool_revision_id,
                params=dict(smoke.get("params") or {}),
            ),
        ],
        "edges": [
            workflow_design_edge(
                from_node="run_fastqc",
                from_port="zip",
                to_node="run_multiqc",
                to_port="fastqc_data",
            )
        ],
        "outputNodeId": "run_multiqc",
        "dependencyToolRevisionIds": [fastqc_revision_id],
    }


def _single_smoke_input(profile_id: str, smoke: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    smoke_inputs = _required_dict(smoke, "inputs")
    if len(smoke_inputs) != 1:
        raise RuntimeError(f"SINGLE_INPUT_ACCEPTANCE_REQUIRED: {profile_id}")
    input_name, fixture = next(iter(smoke_inputs.items()))
    if not isinstance(fixture, dict):
        raise RuntimeError(f"SMOKE_FIXTURE_INVALID: {profile_id}.{input_name}")
    return str(input_name), fixture


def _fixture_bytes(profile_id: str, fixture: dict[str, Any]) -> bytes:
    if str(fixture.get("contentBase64") or "").strip():
        try:
            return base64.b64decode(str(fixture["contentBase64"]).encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
            raise RuntimeError(f"SMOKE_FIXTURE_BASE64_INVALID: {profile_id}") from exc
    content = str(fixture.get("content") or "")
    if not content:
        raise RuntimeError(f"SMOKE_FIXTURE_CONTENT_REQUIRED: {profile_id}")
    return content.encode("utf-8")


def wait_for_run(api_base: str, *, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = response_data(http_json("GET", api_base, f"/api/v1/runs/{run_id}"))
        if run.get("status") in {"completed", "failed"}:
            return run
        time.sleep(2)
    raise TimeoutError(f"RUN_TIMEOUT: {run_id}")


def _required_dict(value: dict[str, Any], key: str) -> dict[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise RuntimeError(f"REQUIRED_OBJECT_MISSING: {key}")
    return result


def _required_text(value: dict[str, Any], key: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result:
        raise RuntimeError(f"REQUIRED_TEXT_MISSING: {key}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()
    requested = args.profile or list(DEFAULT_PROFILES)
    profiles = fetch_profiles(args.api_base)
    server_id = selected_server_id(args.api_base)
    results: list[dict[str, Any]] = []
    for profile_id in requested:
        try:
            result = run_profile(
                api_base=args.api_base,
                server_id=server_id,
                profile=profiles[profile_id],
                profiles=profiles,
                timeout=args.timeout,
            )
        except Exception as exc:
            result = {"profileId": profile_id, "status": "failed", "error": str(exc)}
        results.append(result)
        print("BUILTIN_TOOL_EXECUTION_EVENT: " + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    summary = {
        "schemaVersion": "h2ometa.builtin-tool-execution-acceptance.v1",
        "serverId": server_id,
        "requestedProfiles": requested,
        "passedCount": sum(item.get("status") == "completed" for item in results),
        "failedCount": sum(item.get("status") != "completed" for item in results),
        "productionBoundary": "Smoke fixtures prove generated workflow execution, not ProductionEnabled real-data acceptance.",
        "results": results,
    }
    if args.output_json:
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print("BUILTIN_TOOL_EXECUTION_ACCEPTANCE: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["failedCount"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
