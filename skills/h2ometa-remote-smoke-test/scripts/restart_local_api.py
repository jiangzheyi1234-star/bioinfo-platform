#!/usr/bin/env python3
"""Restart the Windows Local API process for this repo."""

from __future__ import annotations

import csv
import os
import subprocess
import time
import urllib.request
from io import StringIO
from pathlib import Path


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


def list_api_pids() -> list[int]:
    try:
        raw = subprocess.check_output(
            [
                "wmic",
                "process",
                "where",
                "name='python.exe'",
                "get",
                "ProcessId,CommandLine",
                "/format:csv",
            ],
            text=True,
            errors="replace",
        )
    except Exception:
        return []
    pids: list[int] = []
    for row in csv.DictReader(StringIO(raw.strip())):
        command = row.get("CommandLine") or ""
        pid = row.get("ProcessId") or ""
        if "apps.api.run" not in command:
            continue
        try:
            pids.append(int(pid))
        except ValueError:
            continue
    return pids


def stop_processes(pids: list[int]) -> None:
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True, text=True)


def wait_for_health(timeout_seconds: float = 20.0) -> str:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.5)
    raise RuntimeError(last_error or "local API did not become healthy")


def main() -> int:
    repo_root = find_repo_root()
    pids = list_api_pids()
    print(f"API_PIDS_BEFORE: {pids}")
    stop_processes(pids)
    env = os.environ.copy()
    env["H2OMETA_WORKDIR"] = str(repo_root)
    env["PYTHONUTF8"] = "1"
    env["WSL_UTF8"] = "1"
    subprocess.Popen(
        ["cmd.exe", "/c", "scripts\\run-local-api-dev.bat"],
        cwd=str(repo_root),
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    health = wait_for_health()
    print(f"API_HEALTH: {health}")
    print(f"API_PIDS_AFTER: {list_api_pids()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
