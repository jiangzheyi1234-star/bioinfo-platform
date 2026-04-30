from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path


COMMAND = r'''
set -u
RUNNER="$HOME/.h2ometa/runner"
CONDA="$RUNNER/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/conda"
export PATH="$(dirname "$CONDA"):$PATH"
export CONDA_EXE="$CONDA"
BASE="$RUNNER/shared/data/database-mvp"

echo TAXONKIT_REPRO
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/ncbi-taxonomy" bash -lc "set -x; ls -la '$BASE/ncbi_taxonomy/taxdump'; cat -A '$BASE/ncbi_taxonomy/taxdump/nodes.dmp'; cat -A '$BASE/ncbi_taxonomy/taxdump/names.dmp'; taxonkit list --data-dir '$BASE/ncbi_taxonomy/taxdump' --ids 1 --verbose" || true

echo GTDBTK_REPRO
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/gtdbtk" bash -lc "set -x; GTDBTK_DATA_PATH='$BASE/gtdbtk/release' gtdbtk check_install --debug" || true

echo GTDBTK_SOURCE
"$CONDA" run -p "$RUNNER/shared/database-probe-envs/gtdbtk" bash -lc "python - <<'PY'
import os
import gtdbtk
print(gtdbtk.__file__)
base=os.path.dirname(gtdbtk.__file__)
for root, dirs, files in os.walk(base):
    for f in files:
        if not f.endswith('.py'):
            continue
        p=os.path.join(root,f)
        try:
            s=open(p,encoding='utf-8').read()
        except Exception:
            continue
        if 'check_install' in s or 'GTDBTK_DATA_PATH' in s or 'metadata.txt' in s:
            print('---FILE', p)
            for i,line in enumerate(s.splitlines(),1):
                if 'check_install' in line or 'GTDBTK_DATA_PATH' in line or 'metadata.txt' in line or 'masks' in line or 'VERSION' in line:
                    print(f'{i}: {line}')
PY" || true

echo CLEAN_BROKEN_ENVS
rm -rf "$RUNNER/shared/database-probe-envs/checkm" "$RUNNER/shared/database-probe-envs/humann" "$RUNNER/shared/database-probe-envs/silva-qiime"
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
