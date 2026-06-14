from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path


COMMAND = r'''
set -u
echo STATUS
systemctl --user status h2ometa-remote.service --no-pager -l || true
echo JOURNAL
journalctl --user -u h2ometa-remote.service --no-pager -n 200 2>/dev/null || true
echo CURRENT
readlink -f "$HOME/.h2ometa/runner/current" || true
ls -la "$HOME/.h2ometa/runner/current" | head || true
echo CONFIG
python3 - <<'PY'
import json
from pathlib import Path


def _redact(value):
    if isinstance(value, dict):
        redacted = {}
        for key, nested in value.items():
            lowered = key.lower()
            if "token" in lowered or "password" in lowered or lowered.endswith("_ref"):
                redacted[key] = "<redacted>" if nested else nested
            else:
                redacted[key] = _redact(nested)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


path = Path.home() / ".h2ometa" / "runner" / "shared" / "config" / "runner.json"
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except FileNotFoundError:
    print("CONFIG_MISSING")
except Exception as exc:
    print(f"CONFIG_UNREADABLE: {type(exc).__name__}: {exc}")
else:
    print(json.dumps(_redact(payload), indent=2, sort_keys=True))
PY
echo STATE
cat "$HOME/.h2ometa/runner/shared/runtime/runner-state.json" 2>/dev/null || true
echo LOG
tail -200 "$HOME/.h2ometa/runner/shared/logs/runner.log" 2>/dev/null || true
'''


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["REMOTE_EXEC_COMMAND_B64"] = base64.b64encode(COMMAND.encode("utf-8")).decode("ascii")
    cmd = [sys.executable, "scripts\\remote_exec.py"]
    return subprocess.call(cmd, cwd=repo, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
