#!/usr/bin/env python3
"""Clean the installed H2OMeta remote runner release on the configured SSH server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple


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


class CleanupPlan(NamedTuple):
    command: str
    metadata: dict[str, Any]


def _rm_targets(paths: list[str]) -> str:
    return "rm -rf " + " ".join(f'"{path}"' for path in paths)


def _rm_current_symlink(path: str) -> str:
    return (
        f'if [ -e "{path}" ] || [ -L "{path}" ]; then '
        f'if ! test -L "{path}"; then echo "refusing to remove non-symlink current path: {path}" >&2; exit 2; fi; '
        f'rm -f "{path}"; '
        "fi"
    )


def build_cleanup_plan(
    *,
    runner_version: str,
    workflow_runtime_version: str,
    clean_runner_release: bool,
    clean_workflow_runtime: bool,
    clean_test_data: bool,
) -> CleanupPlan:
    commands = ["set -e"]
    targets: list[str] = []
    metadata: dict[str, Any] = {
        "removed_runner_release": "",
        "removed_workflow_runtime": "",
        "removed_test_data": [],
        "preserved_shared_data": True,
    }
    stop_runner = clean_runner_release or clean_workflow_runtime
    if stop_runner:
        commands.extend(
            [
                "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true",
                "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true",
            ]
        )
    if clean_runner_release:
        release = f"$HOME/.h2ometa/runner/releases/{runner_version}"
        bundle = f"$HOME/.h2ometa/runner/bundle-{runner_version}.tar.gz"
        targets.extend(
            [
                release,
                "$HOME/.h2ometa/runner/shared/runtime/runner-state.json",
                bundle,
            ]
        )
        commands.append(_rm_current_symlink("$HOME/.h2ometa/runner/current"))
        metadata["removed_runner_release"] = f"~/.h2ometa/runner/releases/{runner_version}"
    if clean_workflow_runtime:
        workflow_runtime = f"$HOME/.h2ometa/runner/tools/workflow-runtime-{workflow_runtime_version}-linux-64"
        targets.extend([workflow_runtime, f"{workflow_runtime}.tar.gz"])
        metadata["removed_workflow_runtime"] = f"~/.h2ometa/runner/tools/workflow-runtime-{workflow_runtime_version}-linux-64"
    if clean_test_data:
        test_data = [
            "$HOME/.h2ometa/runner/shared/data/database-mvp",
            "$HOME/.h2ometa/runner/shared/data/database-real-smoke",
            "$HOME/.h2ometa/runner/shared/database-probe-envs",
            "$HOME/.h2ometa/smoke-databases",
        ]
        targets.extend(test_data)
        metadata["removed_test_data"] = [path.replace("$HOME", "~", 1) for path in test_data]
    if targets:
        commands.append(_rm_targets(targets))
    else:
        commands.append("printf 'no cleanup targets selected\\n'")
    return CleanupPlan(command="; ".join(commands), metadata=metadata)


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean selected H2OMeta remote runner state on the configured SSH server.")
    parser.add_argument(
        "--runner-release",
        action="store_true",
        help="Remove the current runner release, current symlink, runtime state, and release bundle. This is the default when no cleanup target is selected.",
    )
    parser.add_argument(
        "--workflow-runtime",
        action="store_true",
        help="Also remove the managed workflow runtime directory and tarball.",
    )
    parser.add_argument(
        "--test-data",
        action="store_true",
        help="Remove known smoke-test database fixtures and probe environments only.",
    )
    args = parser.parse_args()
    clean_runner_release = bool(args.runner_release or (not args.workflow_runtime and not args.test_data))

    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect
    from core.remote_runner.release_manifest import REMOTE_RUNNER_VERSION, WORKFLOW_RUNTIME_VERSION

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
        print_json("SSH_RESULT", {"ok": False, "message": result.message})
        return 1

    plan = build_cleanup_plan(
        runner_version=REMOTE_RUNNER_VERSION,
        workflow_runtime_version=WORKFLOW_RUNTIME_VERSION,
        clean_runner_release=clean_runner_release,
        clean_workflow_runtime=bool(args.workflow_runtime),
        clean_test_data=bool(args.test_data),
    )
    try:
        stdin, stdout, stderr = result.client.exec_command(plan.command, timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        print_json(
            "REMOTE_CLEAN",
            {
                "exit_code": exit_code,
                "stdout": stdout.read().decode("utf-8", errors="replace").strip(),
                "stderr": stderr.read().decode("utf-8", errors="replace").strip(),
                **plan.metadata,
            },
        )
        return 0 if exit_code == 0 else 1
    finally:
        result.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
