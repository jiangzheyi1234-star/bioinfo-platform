#!/usr/bin/env python3
"""Validate built-in H2OMeta tool profiles through the Local API."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {
    "cancelled",
    "exhausted",
    "failed",
    "succeeded",
    "waiting_resource",
}


def main() -> int:
    args = parse_args()
    args.max_active = max(1, int(args.max_active))
    args.poll_interval = max(0.5, float(args.poll_interval))
    template_database_bindings = parse_template_database_bindings(args.template_database)
    profiles = fetch_profiles(args.api_base, query=args.query)
    if args.profile:
        wanted = {value.strip() for value in args.profile if value.strip()}
        profiles = [
            profile for profile in profiles if str(profile.get("profileId") or "") in wanted
        ]
    if args.limit:
        profiles = profiles[: args.limit]
    if not profiles:
        raise SystemExit("no tool profiles matched the validation request")

    started_at = now()
    results: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    remaining = list(profiles)

    while remaining or active:
        while remaining and len(active) < args.max_active:
            profile = remaining.pop(0)
            job = create_prepare_job(
                args.api_base,
                profile,
                template_database_bindings=template_database_bindings,
            )
            active.append({"profile": profile, "job": job})
            print_status("queued", profile, job)

        time.sleep(args.poll_interval)
        next_active: list[dict[str, Any]] = []
        for item in active:
            profile = item["profile"]
            job_id = str(item["job"].get("jobId") or "")
            job = fetch_prepare_job(args.api_base, job_id)
            status = str(job.get("status") or "")
            print_status(status or "polling", profile, job)
            if status in TERMINAL_STATUSES:
                results.append(summarize_job(profile, job))
                continue
            next_active.append({"profile": profile, "job": job})
        active = next_active

        if time.time() - started_at > args.timeout:
            for item in active:
                results.append(
                    summarize_job(
                        item["profile"],
                        item["job"],
                        forced_status="timeout",
                    )
                )
            for profile in remaining:
                results.append(
                    {
                        "profileId": str(profile.get("profileId") or ""),
                        "toolId": "",
                        "jobId": "",
                        "status": "not_started",
                        "stage": "",
                        "message": "Validation run timed out before this profile started.",
                        "errorCode": "VALIDATION_RUN_TIMEOUT",
                        "workflowReady": False,
                        "toolRevisionId": "",
                        "validationResultId": "",
                        "evidenceId": "",
                    }
                )
            remaining = []
            active = []
            break

    summary = summarize_run(
        api_base=args.api_base,
        profiles=profiles,
        started_at=started_at,
        results=results,
        template_database_bindings=template_database_bindings,
    )
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print("BUILTIN_TOOL_PROFILE_VALIDATION: " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["failedCount"] == 0 and summary["timeoutCount"] == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate built-in tool profiles through /api/v1/tools/prepare-jobs."
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--query", default="")
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-active", type=int, default=3)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--output-json", default="")
    parser.add_argument(
        "--template-database",
        action="append",
        default=[],
        metavar="TEMPLATE_ID=DATABASE_ID",
        help="Bind database-backed smoke tests by accepted template id.",
    )
    return parser.parse_args()


def fetch_profiles(api_base: str, *, query: str) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = http_json(
            "GET",
            api_base,
            "/api/v1/tool-capabilities/tool-profiles",
            query={"q": query, "page": page, "pageSize": 100},
        )
        data = response_data(payload)
        items = data.get("items")
        if not isinstance(items, list):
            raise RuntimeError("tool profile catalog response did not include items")
        profiles.extend(item for item in items if isinstance(item, dict))
        if not bool(data.get("hasMore")):
            break
        page += 1
    return profiles


def parse_template_database_bindings(raw_bindings: list[str]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for raw in raw_bindings:
        template_id, separator, database_id = str(raw or "").partition("=")
        template_id = template_id.strip().lower()
        database_id = database_id.strip()
        if not separator or not template_id or not database_id:
            raise SystemExit(f"invalid --template-database binding: {raw!r}")
        if template_id in bindings and bindings[template_id] != database_id:
            raise SystemExit(f"conflicting --template-database binding for {template_id}")
        bindings[template_id] = database_id
    return bindings


def create_prepare_job(
    api_base: str,
    profile: dict[str, Any],
    *,
    template_database_bindings: dict[str, str],
) -> dict[str, Any]:
    payload = profile.get("preparePayload")
    if not isinstance(payload, dict):
        profile_id = str(profile.get("profileId") or "")
        raise RuntimeError(f"profile has no preparePayload: {profile_id}")
    payload = prepare_payload_with_database_bindings(payload, template_database_bindings)
    return response_data(http_json("POST", api_base, "/api/v1/tools/prepare-jobs", payload=payload))


def prepare_payload_with_database_bindings(
    payload: dict[str, Any],
    template_database_bindings: dict[str, str],
) -> dict[str, Any]:
    if not template_database_bindings:
        return payload
    prepared = json.loads(json.dumps(payload))
    rule_template = prepared.get("ruleTemplate")
    if not isinstance(rule_template, dict):
        return prepared
    resources = rule_template.get("resources")
    if not isinstance(resources, dict):
        return prepared
    smoke_test = rule_template.get("smokeTest")
    if not isinstance(smoke_test, dict):
        smoke_test = {}
        rule_template["smokeTest"] = smoke_test
    resource_bindings = smoke_test.get("resourceBindings")
    if not isinstance(resource_bindings, dict):
        resource_bindings = {}
        smoke_test["resourceBindings"] = resource_bindings
    for resource_key, spec in resources.items():
        if not isinstance(spec, dict) or str(spec.get("type") or "") != "database":
            continue
        for template_id in spec.get("acceptedTemplates") or []:
            normalized_template = str(template_id or "").strip().lower()
            database_id = template_database_bindings.get(normalized_template)
            if database_id:
                resource_bindings[str(resource_key)] = {
                    "databaseId": database_id,
                    "templateId": normalized_template,
                }
                break
    return prepared


def fetch_prepare_job(api_base: str, job_id: str) -> dict[str, Any]:
    if not job_id:
        raise RuntimeError("prepare job response did not include jobId")
    return response_data(http_json("GET", api_base, f"/api/v1/tools/prepare-jobs/{job_id}"))


def http_json(
    method: str,
    api_base: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = api_base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {text}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc


def response_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        return data
    if isinstance(payload, dict):
        return payload
    raise RuntimeError("API response was not a JSON object")


def summarize_job(
    profile: dict[str, Any],
    job: dict[str, Any],
    *,
    forced_status: str = "",
) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    contract = (
        result.get("toolContract") if isinstance(result.get("toolContract"), dict) else {}
    )
    return {
        "profileId": str(profile.get("profileId") or ""),
        "toolId": str(job.get("toolId") or ""),
        "jobId": str(job.get("jobId") or ""),
        "status": forced_status or str(job.get("status") or ""),
        "stage": str(job.get("stage") or ""),
        "message": str(job.get("message") or ""),
        "errorCode": str(job.get("errorCode") or ""),
        "workflowReady": bool(contract.get("workflowReady")),
        "toolRevisionId": str(result.get("toolRevisionId") or ""),
        "validationResultId": str(job.get("validationResultId") or result.get("validationResultId") or ""),
        "evidenceId": str(job.get("evidenceId") or result.get("evidenceId") or ""),
    }


def summarize_run(
    *,
    api_base: str,
    profiles: list[dict[str, Any]],
    started_at: float,
    results: list[dict[str, Any]],
    template_database_bindings: dict[str, str],
) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    for result in results:
        status = str(result.get("status") or "")
        statuses[status] = statuses.get(status, 0) + 1
    failed = [
        result
        for result in results
        if result.get("status") not in {"succeeded"}
        or not result.get("workflowReady")
        or not result.get("validationResultId")
        or not result.get("evidenceId")
    ]
    return {
        "schemaVersion": "builtin-tool-profile-validation.v1",
        "apiBase": api_base,
        "startedAt": started_at,
        "finishedAt": now(),
        "requestedCount": len(profiles),
        "completedCount": len(results),
        "succeededCount": statuses.get("succeeded", 0),
        "failedCount": len(failed),
        "timeoutCount": statuses.get("timeout", 0),
        "statusCounts": statuses,
        "templateDatabaseBindings": template_database_bindings,
        "failed": failed,
        "results": results,
    }


def print_status(status: str, profile: dict[str, Any], job: dict[str, Any]) -> None:
    payload = {
        "profileId": str(profile.get("profileId") or ""),
        "jobId": str(job.get("jobId") or ""),
        "toolId": str(job.get("toolId") or ""),
        "status": status,
        "stage": str(job.get("stage") or ""),
    }
    print("TOOL_PROFILE_VALIDATION_EVENT: " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    sys.stdout.flush()


def now() -> float:
    return time.time()


if __name__ == "__main__":
    raise SystemExit(main())
