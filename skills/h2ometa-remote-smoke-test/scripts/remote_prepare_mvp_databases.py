#!/usr/bin/env python3
"""Prepare minimal real-ish remote databases for template smoke tests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}", flush=True)


def connect_ssh():
    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect

    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    result = ssh_connect(
        ip=str(resolved.get("host") or ""),
        port=int(resolved.get("port") or 22),
        user=str(resolved.get("user") or ""),
        password=password,
        key_file=key_file,
        use_agent=auth_mode == "agent",
        timeout=int(resolved.get("timeout_sec") or 5),
    )
    if not result.ok or result.client is None:
        raise RuntimeError(f"SSH failed: {result.message}")
    return result.client


def ssh_run(client, command: str, *, timeout: int = 900) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return exit_code, out, err


REMOTE_SCRIPT = r'''
set -u
BASE="$HOME/.h2ometa/runner/shared/data/database-mvp"
RUNNER="$HOME/.h2ometa/runner"
PY="$RUNNER/tools/workflow-runtime-__WORKFLOW_RUNTIME_VERSION__-linux-64/workflow-env/bin/python"
mkdir -p "$BASE"

record() {
  template="$1"; path="$2"; status="$3"; message="$4"
  "$PY" - "$template" "$path" "$status" "$message" <<'PY'
import json, sys
print("MVP_RESULT: " + json.dumps({
  "templateId": sys.argv[1],
  "path": sys.argv[2],
  "status": sys.argv[3],
  "message": sys.argv[4],
}, ensure_ascii=False, sort_keys=True), flush=True)
PY
}

write_taxdump() {
  dir="$1"
  mkdir -p "$dir"
  printf '1\t|\t1\t|\tno rank\t|\t\t|\t8\t|\t0\t|\t1\t|\t0\t|\t0\t|\t0\t|\t0\t|\t0\t|\t\t|\n2\t|\t1\t|\tspecies\t|\t\t|\t8\t|\t0\t|\t1\t|\t0\t|\t0\t|\t0\t|\t0\t|\t0\t|\t\t|\n' > "$dir/nodes.dmp"
  printf '1\t|\troot\t|\t\t|\tscientific name\t|\n2\t|\tmvp species\t|\t\t|\tscientific name\t|\n' > "$dir/names.dmp"
  : > "$dir/merged.dmp"
  : > "$dir/delnodes.dmp"
}

prepare_ncbi_taxonomy() {
  path="$BASE/ncbi_taxonomy/taxdump"
  rm -rf "$path"
  write_taxdump "$path"
  record ncbi_taxonomy "$path" available "minimal taxdump structure files written"
}

prepare_star() {
  path="$BASE/star/hg38"
  rm -rf "$path"
  mkdir -p "$path"
  printf '>chrMVP\nACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n' > "$path/genome.fa"
  printf 'mvp\n' > "$path/Genome"
  printf 'mvp\n' > "$path/SA"
  printf 'mvp\n' > "$path/SAindex"
  record star "$path" available "STAR structural index files written"
}

prepare_kraken2() {
  path="$BASE/kraken2/db"
  rm -rf "$path"
  mkdir -p "$path/taxonomy" "$path/library/mvp"
  write_taxdump "$path/taxonomy"
  printf 'seq1\t2\n' > "$path/seqid2taxid.map"
  printf '>seq1\nACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n' > "$path/library/mvp/seq.fa"
  printf 'mvp\n' > "$path/hash.k2d"
  printf 'mvp\n' > "$path/opts.k2d"
  printf 'mvp\n' > "$path/taxo.k2d"
  record kraken2 "$path" available "Kraken2 structural database files written"
}

prepare_bracken() {
  path="$BASE/bracken/db"
  if [ ! -d "$path" ]; then
    mkdir -p "$path"
  fi
  if [ -d "$BASE/kraken2/db" ]; then
    rm -rf "$path"
    cp -a "$BASE/kraken2/db" "$path"
  fi
  printf '1\t0\t0\n' > "$path/database100mers.kmer_distrib"
  if [ -f "$path/hash.k2d" ] && [ -f "$path/opts.k2d" ] && [ -f "$path/taxo.k2d" ]; then
    record bracken "$path" available "bracken-compatible kraken2 database files are present"
  else
    record bracken "$path" failed "bracken-compatible kraken2 structure is incomplete"
  fi
}

prepare_centrifuge() {
  prefix="$BASE/centrifuge/nt"
  rm -rf "$BASE/centrifuge"
  mkdir -p "$BASE/centrifuge"
  printf '>seq1\nACGTACGTACGTACGTACGTACGTACGTACGT\n' > "$BASE/centrifuge/seq.fa"
  printf 'seq1\t2\n' > "$BASE/centrifuge/seqid2taxid.map"
  write_taxdump "$BASE/centrifuge/taxonomy"
  printf 'mvp\n' > "$prefix.1.cf"
  printf 'mvp\n' > "$prefix.2.cf"
  printf 'mvp\n' > "$prefix.3.cf"
  record centrifuge "$prefix" available "Centrifuge structural index files written"
}

prepare_silva_qiime() {
  path="$BASE/silva/reference.fasta"
  rm -rf "$BASE/silva"
  mkdir -p "$BASE/silva"
  printf '>seq1\nACGTACGTACGT\n' > "$path"
  record silva_qiime "$path" failed "production SILVA/QIIME validation requires a .qza classifier artifact, not an MVP FASTA"
}

prepare_checkm() {
  path="$BASE/checkm"
  rm -rf "$path"
  mkdir -p "$path"
  printf '>seq1\nMAIVMGR\n' > "$path/marker.faa"
  record checkm "$path/diamond.dmnd" failed "production CheckM2 validation requires the official uniref100.KO*.dmnd database"
}

prepare_custom() {
  path="$BASE/custom"
  rm -rf "$path"
  mkdir -p "$path"
  printf 'custom mvp\n' > "$path/README.txt"
  record custom "$path" available "custom non-empty directory"
}

prepare_humann_probe() {
  path="$BASE/humann/db"
  mkdir -p "$path"
  printf '>seq1\nACGTACGTACGT\n' > "$path/mini.ffn"
  record humann "$path" failed "production HUMAnN validation requires ChocoPhlAn, UniRef, and utility_mapping directories"
}

prepare_gtdbtk_probe() {
  path="$BASE/gtdbtk/release"
  rm -rf "$path"
  mkdir -p "$path/masks" "$path/metadata"
  printf 'r232\n' > "$path/VERSION"
  printf 'VERSION_DATA=r232\nRED_DIST_BAC_DICT={}\nRED_DIST_ARC_DICT={}\n' > "$path/metadata/metadata.txt"
  printf 'VERSION_DATA=r232\n' > "$path/metadata.txt"
  record gtdbtk "$path" failed "production GTDB-Tk validation requires the full reference bundle and gtdbtk check_install"
}

prepare_ncbi_taxonomy
prepare_star
prepare_kraken2
prepare_bracken
prepare_centrifuge
prepare_silva_qiime
prepare_checkm
prepare_custom
prepare_humann_probe
prepare_gtdbtk_probe
'''


def main() -> int:
    from core.remote_runner.release_manifest import WORKFLOW_RUNTIME_VERSION

    parser = argparse.ArgumentParser(description="Prepare remote MVP databases for template smoke tests.")
    parser.parse_args()
    client = connect_ssh()
    try:
        remote_script = REMOTE_SCRIPT.replace("__WORKFLOW_RUNTIME_VERSION__", WORKFLOW_RUNTIME_VERSION)
        code, stdout, stderr = ssh_run(client, remote_script, timeout=1800)
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
