from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


COMMAND = (
    'rm -f "$HOME/.h2ometa/runner/shared/runtime/runner-state.json"\n'
    'rm -rf "$HOME/.h2ometa/runner/locks/install-0.1.1-control-plane.lock"\n'
)


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
