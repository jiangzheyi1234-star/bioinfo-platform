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
ENV="$RUNNER/shared/database-probe-envs/ncbi-taxonomy"
BASE="$RUNNER/shared/data/database-mvp/taxonkit-cases"
rm -rf "$BASE"
mkdir -p "$BASE"
write_case() {
  d="$BASE/$1"
  mkdir -p "$d"
  printf '1\t|\t1\t|\tno rank\t|\t\t|\t8\t|\t0\t|\t1\t|\t0\t|\t0\t|\t0\t|\t0\t|\t0\t|\t\t|\n2\t|\t1\t|\tspecies\t|\t\t|\t8\t|\t0\t|\t1\t|\t0\t|\t0\t|\t0\t|\t0\t|\t0\t|\t\t|\n' > "$d/nodes.dmp"
  printf '1\t|\troot\t|\t\t|\tscientific name\t|\n2\t|\tmvp species\t|\t\t|\tscientific name\t|\n' > "$d/names.dmp"
}
write_case no_optional
write_case nonempty_optional
printf '0\t|\t1\t|\n' > "$BASE/nonempty_optional/merged.dmp"
printf '3\t|\t2\t|\n' > "$BASE/nonempty_optional/merged.dmp"
printf '4\t|\n' > "$BASE/nonempty_optional/delnodes.dmp"
write_case full_optional
printf '8\t|\tBCT\t|\tBacteria\t|\t\t|\n' > "$BASE/full_optional/division.dmp"
printf '1\t|\tStandard\t|\t\t|\tFFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG\t|\n' > "$BASE/full_optional/gencode.dmp"
printf '3\t|\t2\t|\n' > "$BASE/full_optional/merged.dmp"
printf '4\t|\n' > "$BASE/full_optional/delnodes.dmp"
printf 'superkingdom\tphylum\tclass\torder\tfamily\tgenus\tspecies\nBacteria\tMVPphylum\tMVPclass\tMVPorder\tMVPfamily\tMVPgenus\tMVP species\n' > "$BASE/lineages.tsv"
"$CONDA" run -p "$ENV" bash -lc "taxonkit create-taxdump '$BASE/lineages.tsv' --out-dir '$BASE/created' --force" || true
printf '99\t|\t1\t|\n' > "$BASE/created/merged.dmp"
printf '100\t|\n' > "$BASE/created/delnodes.dmp"
for c in no_optional nonempty_optional full_optional; do
  echo "--- CASE $c"
  "$CONDA" run -p "$ENV" bash -lc "taxonkit version; find '$BASE/$c' -maxdepth 1 -type f -printf '%f %s bytes\n' | sort; taxonkit list --data-dir '$BASE/$c' --ids 1 --show-name --show-rank --verbose" || true
  "$CONDA" run -p "$ENV" bash -lc "taxonkit list --data-dir '$BASE/$c' --ids 2 --show-name --show-rank --verbose" || true
done
echo "--- CASE created"
find "$BASE/created" -maxdepth 1 -type f -printf '%f %s bytes\n' | sort || true
"$CONDA" run -p "$ENV" bash -lc "taxonkit list --data-dir '$BASE/created' --ids 1 --show-name --show-rank --verbose" || true
"$CONDA" run -p "$ENV" bash -lc "taxonkit --data-dir '$BASE/created' list --ids 1 --show-name --show-rank --verbose" || true
"$CONDA" run -p "$ENV" bash -lc "printf '1\n' | taxonkit --data-dir '$BASE/created' list --show-name --show-rank --verbose" || true
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
