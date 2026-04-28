#!/usr/bin/env python3
"""Call local RuntimeService methods directly for debugging."""

from __future__ import annotations

import json
import argparse
import sys
import traceback
from pathlib import Path


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    from core.app_runtime.service import RuntimeService

    parser = argparse.ArgumentParser(description="Call local RuntimeService methods directly for debugging.")
    parser.add_argument("--ensure-runner", action="store_true", help="Mutating: run ensure_remote_runner_ready")
    args = parser.parse_args()

    service = RuntimeService()
    service.initialize()
    for label, func in (
        ("list_servers", service.list_servers),
        ("get_server_health", lambda: service.get_server_health("srv_6fc8b0974984")),
        ("get_server", lambda: service.get_server("srv_6fc8b0974984")),
    ):
        try:
            print(f"{label}: {json.dumps(func(), ensure_ascii=False, indent=2)}")
        except Exception:
            print(f"{label}: ERROR")
            traceback.print_exc()
    if args.ensure_runner:
        try:
            print(
                "ensure_remote_runner_ready:",
                json.dumps(service.ensure_remote_runner_ready("srv_6fc8b0974984"), ensure_ascii=False, indent=2),
            )
        except Exception:
            print("ensure_remote_runner_ready: ERROR")
            traceback.print_exc()
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
