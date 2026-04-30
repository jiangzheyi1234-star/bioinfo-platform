from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_config, normalize_ssh_config, resolve_ssh_password


def main() -> int:
    ssh = normalize_ssh_config(get_config().get("ssh", {}))
    payload = {
        "auth_mode": ssh["auth_mode"],
        "ssh_host_alias": ssh["ssh_host_alias"],
        "identity_ref": ssh["identity_ref"],
        "remember_auth": ssh["remember_auth"],
        "auto_connect_on_startup": ssh["auto_connect_on_startup"],
        "host": ssh["host"],
        "port": ssh["port"],
        "user": ssh["user"],
        "timeout_sec": ssh["timeout_sec"],
    }
    if ssh["auth_mode"] == "password_ref":
        payload["password"] = resolve_ssh_password({"ssh": ssh})
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "http://127.0.0.1:8765/api/v1/ssh/connect",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    payload.pop("password", None)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
