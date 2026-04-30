from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path


COMMAND = r'''
set -e
RUNNER="$HOME/.h2ometa/runner"
CONDA="$RUNNER/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda"
export PATH="$(dirname "$CONDA"):$PATH"
export CONDA_EXE="$CONDA"
echo ENV_DIRS
for e in ncbi-taxonomy silva-qiime checkm humann gtdbtk; do
  p="$RUNNER/shared/database-probe-envs/$e"
  echo "--- $e $p"
  test -e "$p" && ls -la "$p" | head || echo missing
  test -f "$p/.h2ometa-package-spec" && cat "$p/.h2ometa-package-spec" || true
done
echo TAXONKIT_HELP
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/ncbi-taxonomy" bash -lc "taxonkit list --help | head -60" || true
echo QIIME_IMPORT_HELP
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/silva-qiime" bash -lc "qiime tools import --help | head -80" || true
echo CHECKM_HELP
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/checkm" bash -lc "checkm data setRoot --help | head -80" || true
echo HUMANN_ENV
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/humann" bash -lc 'which humann_config; head -1 "$(which humann_config)"; python - <<PY
import sys, pkgutil
print(sys.executable)
print("humann module", bool(pkgutil.find_loader("humann")))
PY' || true
echo GTDBTK_HELP
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/gtdbtk" bash -lc "gtdbtk check_install --help | head -80" || true
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
