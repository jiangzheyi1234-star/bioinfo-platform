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
cat "$HOME/.h2ometa/runner/shared/config/runner.json" 2>/dev/null | head -40 || true
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
