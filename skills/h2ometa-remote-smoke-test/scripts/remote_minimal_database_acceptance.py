#!/usr/bin/env python3
"""Run real minimal database validation and delete the created fixtures.

This smoke is intentionally small: it creates structural fixture files for the
registered database templates, registers them through the Local API, runs a
generated Snakemake resource-binding smoke, then removes the database records
and remote fixture directory.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import shlex
import sys
import tempfile
import time
import urllib.error
import urllib.parse
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
SCRIPT_DIR = Path(__file__).resolve().parent
for import_path in (REPO_ROOT, SCRIPT_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from apps.remote_runner.database_template_fixtures import materialize_template_selection  # noqa: E402
from apps.remote_runner.database_templates import DATABASE_TEMPLATES  # noqa: E402
from local_api_smoke_helpers import response_data, selected_server_id  # noqa: E402
from remote_all_databases_snakemake_smoke import run_database_smoke  # noqa: E402
from remote_cleanup_test_databases import connect_ssh, ssh_run  # noqa: E402


REMOTE_FIXTURE_PARENT = "$HOME/.h2ometa/runner/shared/data/database-real-smoke"


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


def parse_templates(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip().lower() for item in value.split(",") if item.strip())
    unknown = sorted(set(parsed) - set(DATABASE_TEMPLATES))
    if unknown:
        raise SystemExit(f"ERROR: unknown database template(s): {', '.join(unknown)}")
    return parsed or list(DATABASE_TEMPLATES)


def remote_home(client) -> str:
    code, stdout, stderr = ssh_run(client, "printf '%s' \"$HOME\"", timeout=30)
    if code != 0:
        raise RuntimeError(f"Could not resolve remote home: {stderr.strip() or stdout.strip()}")
    home = stdout.strip()
    if not home.startswith("/"):
        raise RuntimeError(f"Remote home is not absolute: {home}")
    return home


def mkdir_p(sftp, remote_path: str) -> None:
    normalized = posixpath.normpath(remote_path)
    current = "/" if normalized.startswith("/") else ""
    for part in normalized.strip("/").split("/"):
        if not part:
            continue
        current = posixpath.join(current, part) if current != "/" else f"/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def upload_tree(sftp, local_root: Path, remote_root: str) -> None:
    mkdir_p(sftp, remote_root)
    for local_path in sorted(local_root.rglob("*")):
        relative = local_path.relative_to(local_root).as_posix()
        remote_path = posixpath.join(remote_root, relative)
        if local_path.is_dir():
            mkdir_p(sftp, remote_path)
        else:
            mkdir_p(sftp, posixpath.dirname(remote_path))
            sftp.put(str(local_path), remote_path)


def build_fixtures(local_root: Path, remote_root: str, template_ids: list[str]) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for template_id in template_ids:
        local_template_root = local_root / template_id
        _target, selected_path = materialize_template_selection(local_template_root, template_id)
        selected_relative = selected_path.relative_to(local_template_root).as_posix()
        remote_template_root = posixpath.join(remote_root, template_id)
        remote_selected = remote_template_root if selected_relative == "." else posixpath.join(remote_template_root, selected_relative)
        template = DATABASE_TEMPLATES[template_id]
        fixtures.append(
            {
                "templateId": template_id,
                "label": str(template.get("label") or template_id),
                "localRoot": local_template_root,
                "remoteRoot": remote_template_root,
                "remoteSelectedPath": remote_selected,
            }
        )
    return fixtures


def register_fixture_database(api_base: str, fixture: dict[str, Any], *, run_id: str, index: int) -> dict[str, Any]:
    template_id = str(fixture["templateId"])
    database_id = f"h2ometa-minimal-db-smoke-{run_id}-{index:02d}-{template_id}"
    payload = {
        "id": database_id,
        "name": f"Minimal smoke {fixture['label']}",
        "templateId": template_id,
        "version": "minimal-fixture",
        "path": fixture["remoteSelectedPath"],
        "source": "minimal-real-smoke",
        "description": "Temporary minimal fixture for real database template acceptance smoke.",
        "metadata": {"templateId": template_id, "smokeRunId": run_id, "fixtureKind": "minimal-real-smoke"},
    }
    return response_data(http_json("POST", api_base, "/api/v1/databases", payload=payload, timeout=1800))


def delete_database_records(api_base: str, database_ids: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for database_id in database_ids:
        try:
            http_json("DELETE", api_base, f"/api/v1/databases/{urllib.parse.quote(database_id, safe='')}", timeout=30)
            results.append({"id": database_id, "deleted": True})
        except Exception as exc:
            results.append({"id": database_id, "deleted": False, "error": str(exc)})
    return results


def remove_remote_fixtures(client, remote_root: str) -> dict[str, Any]:
    if "/.h2ometa/runner/shared/data/database-real-smoke/" not in remote_root:
        raise RuntimeError(f"Refusing to delete unexpected remote path: {remote_root}")
    command = (
        "set -e; "
        f"target={shlex.quote(remote_root)}; "
        "if [ -e \"$target\" ]; then rm -rf -- \"$target\"; printf 'deleted %s\\n' \"$target\"; "
        "else printf 'missing %s\\n' \"$target\"; fi"
    )
    code, stdout, stderr = ssh_run(client, command, timeout=300)
    return {"exitCode": code, "stdout": stdout, "stderr": stderr, "remoteRoot": remote_root}


def verify_api_templates(api_base: str, template_ids: list[str]) -> None:
    templates = response_data(http_json("GET", api_base, "/api/v1/database-templates", timeout=30))["items"]
    available_ids = {str(item.get("id") or "").strip().lower() for item in templates}
    missing = sorted(set(template_ids) - available_ids)
    if missing:
        raise RuntimeError(f"Local API database template catalog is missing: {', '.join(missing)}")


def run_acceptance(args: argparse.Namespace) -> int:
    template_ids = parse_templates(args.template)
    verify_api_templates(args.api_base, template_ids)
    server_id = selected_server_id(args.api_base)
    run_id = args.run_id or str(int(time.time()))
    registered: list[dict[str, Any]] = []
    registration_failures: list[dict[str, Any]] = []
    snakemake_results: list[dict[str, Any]] = []

    client = connect_ssh()
    remote_root = ""
    try:
        home = remote_home(client)
        remote_parent = REMOTE_FIXTURE_PARENT.replace("$HOME", home)
        remote_root = posixpath.join(remote_parent, f"minimal-{run_id}")
        with tempfile.TemporaryDirectory(prefix="h2ometa-minimal-db-") as temp_name:
            local_root = Path(temp_name) / "fixtures"
            fixtures = build_fixtures(local_root, remote_root, template_ids)
            sftp = client.open_sftp()
            try:
                for fixture in fixtures:
                    upload_tree(sftp, Path(fixture["localRoot"]), str(fixture["remoteRoot"]))
            finally:
                sftp.close()

            print_json("MINIMAL_DATABASE_FIXTURE_SCOPE", {"runId": run_id, "remoteRoot": remote_root, "templates": template_ids})
            for index, fixture in enumerate(fixtures, start=1):
                try:
                    database = register_fixture_database(args.api_base, fixture, run_id=run_id, index=index)
                    registered.append(database)
                    print_json(
                        "MINIMAL_DATABASE_REGISTERED",
                        {
                            "id": database.get("id"),
                            "templateId": (database.get("metadata") or {}).get("templateId"),
                            "status": database.get("status"),
                            "path": database.get("path"),
                            "entryPath": database.get("entryPath"),
                        },
                    )
                except Exception as exc:
                    failure = {"templateId": fixture["templateId"], "status": "failed", "error": str(exc)}
                    registration_failures.append(failure)
                    print_json("MINIMAL_DATABASE_REGISTER_FAILED", failure)

            if not args.skip_snakemake:
                for index, database in enumerate(registered, start=1):
                    result = run_database_smoke(
                        args.api_base,
                        database,
                        server_id=server_id,
                        index=index,
                        timeout=args.timeout,
                    )
                    snakemake_results.append(result)
                    print_json("MINIMAL_DATABASE_SNAKEMAKE_RESULT", result)
    finally:
        cleanup_records = delete_database_records(args.api_base, [str(item.get("id") or "") for item in registered if item.get("id")])
        if cleanup_records:
            print_json("MINIMAL_DATABASE_RECORD_CLEANUP", cleanup_records)
        if remote_root:
            print_json("MINIMAL_DATABASE_REMOTE_CLEANUP", remove_remote_fixtures(client, remote_root))
        client.close()

    failed_snakemake = [item for item in snakemake_results if item.get("status") != "completed"]
    summary = {
        "templates": len(template_ids),
        "registered": len(registered),
        "registrationFailed": len(registration_failures),
        "snakemakeCompleted": len(snakemake_results) - len(failed_snakemake),
        "snakemakeFailed": len(failed_snakemake),
        "deletedRecords": len(registered),
        "remoteFixtureDeleted": bool(remote_root),
    }
    print_json("MINIMAL_DATABASE_ACCEPTANCE_SUMMARY", summary)
    return 0 if not registration_failures and not failed_snakemake and len(registered) == len(template_ids) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real minimal database acceptance and clean up created fixtures.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--template", action="append", default=[], help="Template id. Can be repeated or comma-separated.")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--run-id", default="", help="Optional cleanup-scoped run id.")
    parser.add_argument("--skip-snakemake", action="store_true", help="Only register and validate database templates.")
    args = parser.parse_args()
    return run_acceptance(args)


if __name__ == "__main__":
    raise SystemExit(main())
