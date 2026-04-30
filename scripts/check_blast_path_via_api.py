from __future__ import annotations

import json
import sys
import urllib.request


def request(method: str, path: str, payload: dict | None = None) -> str:
    base = "http://127.0.0.1:8765"
    body = json.dumps(payload).encode("utf-8") if payload is not None else (b"{}" if method == "POST" else None)
    req = urllib.request.Request(
        base + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=20).read().decode()


def main() -> int:
    database_id = "blast-ui-check"
    path = "/home/zyserver/project_ssd/common_data/core_nt_database"
    print(
        request(
            "POST",
            "/api/v1/databases",
            {
                "id": database_id,
                "name": "BLAST UI Check",
                "templateId": "blast",
                "path": path,
                "source": "manual",
                "metadata": {"templateId": "blast"},
            },
        )
    )
    print(request("POST", f"/api/v1/databases/{database_id}/check"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
