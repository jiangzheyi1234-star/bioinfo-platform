#!/usr/bin/env python3
"""Finalize P0-8C after the GTDB-Tk R232 database download becomes ready."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.register_gtdbtk_r232_database import DEFAULT_DATABASE_ID


EXPECTED_PROFILE_COUNT = 123
GTDBTK_PROFILE_ID = "gtdbtk-classify"


def main() -> int:
    args = parse_args()
    output_json = str(Path(args.output_json))
    run_step(
        [
            sys.executable,
            "-B",
            "scripts/register_gtdbtk_r232_database.py",
            "--api-base",
            args.api_base,
            "--database-id",
            args.database_id,
        ]
    )
    run_step(
        [
            sys.executable,
            "-B",
            "scripts/validate_builtin_tool_profiles.py",
            "--api-base",
            args.api_base,
            "--profile",
            GTDBTK_PROFILE_ID,
            "--max-active",
            "1",
            "--poll-interval",
            str(args.poll_interval),
            "--timeout",
            str(args.validation_timeout),
            "--output-json",
            output_json,
            "--template-database",
            f"gtdbtk={args.database_id}",
        ]
    )
    graph = response_data(
        http_json(
            "GET",
            args.api_base,
            "/api/v1/tool-capabilities/capability-graph",
            query={"refresh": "true"},
        )
    )
    audit = audit_capability_graph_completion(graph)
    print("P0_8C_GTDBTK_FINALIZATION: " + json.dumps(audit, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Register the completed GTDB-Tk R232 database, validate gtdbtk-classify, "
            "and assert the P0-8C CapabilityGraph reaches 123/123."
        )
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--database-id", default=DEFAULT_DATABASE_ID)
    parser.add_argument("--validation-timeout", type=float, default=7200.0)
    parser.add_argument("--poll-interval", type=float, default=15.0)
    parser.add_argument("--output-json", default=".tmp/p0-8c-gtdbtk-validation.json")
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    print("RUN_STEP: " + json.dumps(command, ensure_ascii=False), flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def audit_capability_graph_completion(graph: dict[str, Any]) -> dict[str, Any]:
    agent_selectable_tools = [
        item for item in graph.get("agentSelectableTools") or [] if isinstance(item, dict)
    ]
    agent_profile_ids = {
        str(value)
        for value in graph.get("agentSelectableProfileIds") or []
        if str(value).strip()
    }
    if not agent_profile_ids:
        agent_profile_ids = {
            str(item.get("profileId") or item.get("id") or "")
            for item in agent_selectable_tools
            if str(item.get("profileId") or item.get("id") or "").strip()
        }
    capability_bundles = [
        item for item in graph.get("capabilityBundles") or [] if isinstance(item, dict)
    ]
    validation_items = _queue_items(graph.get("validationQueue"))
    gtdb_validation_items = [
        item
        for item in validation_items
        if str(item.get("profileId") or "") == GTDBTK_PROFILE_ID
        or str(item.get("candidateId") or "").endswith(f"::{GTDBTK_PROFILE_ID}")
    ]
    audit = {
        "profileCount": int(graph.get("profileCount") or 0),
        "agentSelectableCount": len(agent_selectable_tools),
        "capabilityBundleCount": len(capability_bundles),
        "validationRemaining": len(validation_items),
        "gtdbtkAgentSelectable": GTDBTK_PROFILE_ID in agent_profile_ids,
        "gtdbtkValidationRemaining": len(gtdb_validation_items),
    }
    failures: list[str] = []
    if audit["profileCount"] != EXPECTED_PROFILE_COUNT:
        failures.append(f"profileCount={audit['profileCount']} expected={EXPECTED_PROFILE_COUNT}")
    if audit["agentSelectableCount"] != EXPECTED_PROFILE_COUNT:
        failures.append(
            f"agentSelectableCount={audit['agentSelectableCount']} expected={EXPECTED_PROFILE_COUNT}"
        )
    if audit["capabilityBundleCount"] != EXPECTED_PROFILE_COUNT:
        failures.append(
            f"capabilityBundleCount={audit['capabilityBundleCount']} expected={EXPECTED_PROFILE_COUNT}"
        )
    if audit["validationRemaining"] != 0:
        failures.append(f"validationRemaining={audit['validationRemaining']} expected=0")
    if not audit["gtdbtkAgentSelectable"]:
        failures.append(f"{GTDBTK_PROFILE_ID} is not agent selectable")
    if audit["gtdbtkValidationRemaining"] != 0:
        failures.append(f"{GTDBTK_PROFILE_ID} is still in validation queue")
    if failures:
        audit["ok"] = False
        audit["failures"] = failures
        raise SystemExit("P0-8C CapabilityGraph audit failed: " + "; ".join(failures))
    audit["ok"] = True
    audit["failures"] = []
    return audit


def _queue_items(queue: Any) -> list[dict[str, Any]]:
    if not isinstance(queue, dict):
        return []
    return [item for item in queue.get("items") or [] if isinstance(item, dict)]


def http_json(
    method: str,
    api_base: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = api_base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, method=method.upper(), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
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


if __name__ == "__main__":
    raise SystemExit(main())
