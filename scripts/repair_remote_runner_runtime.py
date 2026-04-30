from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


COMMAND = r'''
set -u
RUNNER="$HOME/.h2ometa/runner"
RUNTIME="$RUNNER/current/runtime"
CONDA="$RUNTIME/bin/conda"
if [ ! -x "$CONDA" ]; then
  echo "missing conda in runtime: $CONDA" >&2
  exit 1
fi
PATH="$RUNTIME/bin:$PATH" CONDA_EXE="$CONDA" "$CONDA" install -y -p "$RUNTIME" -c conda-forge 'fastapi>=0.115.0' 'uvicorn>=0.34.0' 'pydantic>=2.10.0'
systemctl --user restart h2ometa-remote.service
sleep 3
systemctl --user status h2ometa-remote.service --no-pager -l || true
cat "$RUNNER/shared/runtime/runner-state.json" 2>/dev/null || true
'''


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["REMOTE_EXEC_COMMAND_B64"] = base64.b64encode(COMMAND.encode("utf-8")).decode("ascii")
    cmd = [
        r"C:\Users\Administrator\miniconda3\Scripts\conda.exe",
        "run",
        "-n",
        "bio_ui",
        "python",
        "scripts\\remote_exec.py",
    ]
    return subprocess.call(cmd, cwd=repo, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
