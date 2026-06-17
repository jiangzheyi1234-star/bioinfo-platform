#!/usr/bin/env python3
"""Register the completed GTDB-Tk R232 database download through the Local API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_REMOTE_ROOT = "/home/zyserver/databases/gtdbtk-r232-official"
DEFAULT_DATABASE_ID = "p0-8c-gtdbtk-r232-official"
GTDBTK_R232_MD5 = "25a59e0352b1fd150c589f56559767d4"
GTDBTK_R232_ARCHIVE_BYTES = 60806405195
GTDBTK_R232_SOURCE_URL = (
    "https://data.gtdb.aau.ecogenomic.org/releases/release232/232.0/"
    "auxillary_files/gtdbtk_package/full_package/gtdbtk_r232_data.tar.gz"
)


def main() -> int:
    args = parse_args()
    remote_status = fetch_remote_status(args.remote_root)
    print("GTDBTK_REMOTE_STATUS: " + json.dumps(remote_status, ensure_ascii=False, sort_keys=True))
    validate_remote_status_ready(remote_status)
    ready_dir = str(remote_status.get("readyDir") or "").strip()

    existing = find_database(args.api_base, args.database_id)
    if existing:
        if str(existing.get("path") or "") != ready_dir:
            raise SystemExit(
                f"database {args.database_id!r} already exists with a different path: "
                f"{existing.get('path')!r}"
            )
        checked = check_database(args.api_base, args.database_id)
        print("GTDBTK_DATABASE_EXISTS: " + json.dumps(checked, ensure_ascii=False, sort_keys=True))
        return 0

    payload = build_database_payload(
        database_id=args.database_id,
        ready_dir=ready_dir,
        archive_path=str(remote_status.get("archive") or ""),
    )
    created = response_data(http_json("POST", args.api_base, "/api/v1/databases", payload=payload))
    print("GTDBTK_DATABASE_REGISTERED: " + json.dumps(created, ensure_ascii=False, sort_keys=True))
    checked = check_database(args.api_base, args.database_id)
    print("GTDBTK_DATABASE_CHECKED: " + json.dumps(checked, ensure_ascii=False, sort_keys=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register a completed GTDB-Tk R232 reference directory through /api/v1/databases."
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8765")
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--database-id", default=DEFAULT_DATABASE_ID)
    return parser.parse_args()


def parse_status_tsv(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        parts = [part.strip() for part in raw_line.split("\t")]
        if len(parts) < 2 or not parts[0]:
            continue
        key = parts[0]
        if key == "state" and len(parts) >= 3:
            parsed["state"] = parts[1]
            parsed["stateAt"] = parts[2]
            continue
        parsed[key] = parts[1]
    return parsed


def build_database_payload(*, database_id: str, ready_dir: str, archive_path: str) -> dict[str, Any]:
    return {
        "id": database_id,
        "name": "P0-8C GTDB-Tk R232 official reference",
        "templateId": "gtdbtk",
        "type": "taxonomy",
        "version": "R232",
        "path": ready_dir,
        "description": "Official GTDB-Tk R232 data package downloaded from the GTDB AAU mirror.",
        "source": GTDBTK_R232_SOURCE_URL,
        "sizeBytes": GTDBTK_R232_ARCHIVE_BYTES,
        "checksum": f"md5:{GTDBTK_R232_MD5}",
        "metadata": {
            "templateId": "gtdbtk",
            "sourceMirror": "GTDB AAU Europe",
            "sourceUrl": GTDBTK_R232_SOURCE_URL,
            "archivePath": archive_path,
            "archiveBytes": GTDBTK_R232_ARCHIVE_BYTES,
            "archiveMd5": GTDBTK_R232_MD5,
            "validationScope": "P0-8C gtdbtk-classify real tool validation",
        },
    }


def validate_remote_status_ready(remote_status: dict[str, Any]) -> None:
    if remote_status.get("state") != "ready":
        raise SystemExit(f"GTDB-Tk download is not ready: {remote_status.get('state') or 'missing'}")
    if not str(remote_status.get("readyDir") or "").strip():
        raise SystemExit("GTDB-Tk ready status did not include readyDir")
    if str(remote_status.get("md5") or "").strip() != GTDBTK_R232_MD5:
        raise SystemExit("GTDB-Tk ready status did not include the expected R232 MD5")
    checks = remote_status.get("checks") if isinstance(remote_status.get("checks"), dict) else {}
    missing_checks = [
        name
        for name in ("archiveExists", "readyDirExists", "requiredDirsPresent", "metadataTxtPresent")
        if not bool(checks.get(name))
    ]
    if missing_checks:
        raise SystemExit(
            "GTDB-Tk ready status failed required structure checks: " + ", ".join(missing_checks)
        )


def fetch_remote_status(remote_root: str) -> dict[str, Any]:
    command = _remote_status_command(remote_root)
    env = os.environ.copy()
    env["REMOTE_EXEC_COMMAND_B64"] = base64.b64encode(command.encode("utf-8")).decode("ascii")
    result = subprocess.run(
        [sys.executable, "-B", "scripts/remote_exec.py"],
        check=False,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"remote status probe failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout)


def _remote_status_command(remote_root: str) -> str:
    root_json = json.dumps(remote_root)
    return f"""python3 - <<'PY'
import json
from pathlib import Path

root = Path({root_json})
status_path = root / "status.tsv"
status = {{}}
if status_path.exists():
    for raw_line in status_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [part.strip() for part in raw_line.split("\\t")]
        if len(parts) < 2 or not parts[0]:
            continue
        if parts[0] == "state" and len(parts) >= 3:
            status["state"] = parts[1]
            status["stateAt"] = parts[2]
        else:
            status[parts[0]] = parts[1]

ready_dir = status.get("ready_dir", "")
archive = status.get("archive", "")
checks = {{
    "rootExists": root.exists(),
    "statusExists": status_path.exists(),
    "readyDirExists": bool(ready_dir) and Path(ready_dir).is_dir(),
    "archiveExists": bool(archive) and Path(archive).is_file(),
    "requiredDirsPresent": False,
    "metadataTxtPresent": False,
}}
if checks["readyDirExists"]:
    required = ["markers", "masks", "metadata", "mrca_red", "msa", "pplacer", "radii", "skani", "split", "taxonomy"]
    ready_path = Path(ready_dir)
    checks["requiredDirsPresent"] = all((ready_path / name).is_dir() for name in required)
    checks["metadataTxtPresent"] = any(ready_path.glob("**/metadata.txt"))
print(json.dumps({{
    "state": status.get("state", ""),
    "stateAt": status.get("stateAt", ""),
    "archive": archive,
    "readyDir": ready_dir,
    "md5": status.get("md5", ""),
    "checks": checks,
}}, sort_keys=True))
PY"""


def find_database(api_base: str, database_id: str) -> dict[str, Any] | None:
    payload = response_data(http_json("GET", api_base, "/api/v1/databases", query={"refresh": "true"}))
    for item in payload.get("items") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == database_id:
            return item
    return None


def check_database(api_base: str, database_id: str) -> dict[str, Any]:
    return response_data(http_json("POST", api_base, f"/api/v1/databases/{urllib.parse.quote(database_id)}/check"))


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
