from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


COMMAND = r'''
set -u
head -1 "$HOME/.h2ometa/runner/current/runtime/bin/conda" || true
ls -la "$HOME/.h2ometa/runner/current/runtime/.h2ometa-conda-unpacked" 2>/dev/null || true
"$HOME/.h2ometa/runner/current/runtime/bin/python" "$HOME/.h2ometa/runner/current/runtime/bin/conda-unpack" >/tmp/h2ometa-conda-unpack.log 2>&1 || cat /tmp/h2ometa-conda-unpack.log
head -1 "$HOME/.h2ometa/runner/current/runtime/bin/conda" || true
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
