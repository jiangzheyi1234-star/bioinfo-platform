from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path


COMMAND = r'''
set -u
RUNNER="$HOME/.h2ometa/runner"
CONDA="$RUNNER/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda"
ENV="$RUNNER/shared/database-probe-envs/blast"
DIR="/home/zyserver/project_ssd/common_data/core_nt_database"
PREFIX="$DIR/core_nt"
export PATH="$(dirname "$CONDA"):$PATH"
export CONDA_EXE="$CONDA"
echo DIR_DB_TEST
"$CONDA" run -p "$ENV" bash -lc "blastdbcmd -db '$DIR' -info >/tmp/blast-dir-info.txt 2>/tmp/blast-dir-err.txt; code=\$?; echo exit=\$code; head -5 /tmp/blast-dir-info.txt 2>/dev/null; head -5 /tmp/blast-dir-err.txt 2>/dev/null" || true
echo PREFIX_DB_TEST
"$CONDA" run -p "$ENV" bash -lc "blastdbcmd -db '$PREFIX' -info | head -8"
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
