from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


COMMAND = r'''
set -u
RUNNER="$HOME/.h2ometa/runner"
CONDA="$RUNNER/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda"
export PATH="$(dirname "$CONDA"):$PATH"
export CONDA_EXE="$CONDA"
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/gtdbtk" bash -lc '
sed -n "200,330p" "$CONDA_PREFIX/lib/python3.13/site-packages/gtdbtk/config/common.py"
sed -n "220,330p" "$CONDA_PREFIX/lib/python3.13/site-packages/gtdbtk/misc.py"
'
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
