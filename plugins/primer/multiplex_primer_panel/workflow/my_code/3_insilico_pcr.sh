#!/bin/bash
set -euo pipefail

INPUT_TSV="${1:?missing current pool}"
REF_DIR="${2:?missing ref dir}"
OUTPUT_TXT="${3:?missing output path}"

python - "$INPUT_TSV" "$REF_DIR" "$OUTPUT_TXT" <<'PY'
from __future__ import annotations

import csv
import sys
from pathlib import Path


def load_pool(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.readline()
        handle.seek(0)
        if sample.startswith("pathogen\t"):
            return list(csv.DictReader(handle, delimiter="\t"))
        return []


def load_genomes(ref_dir: Path) -> list[tuple[str, str]]:
    genomes: list[tuple[str, str]] = []
    for fasta in sorted(ref_dir.glob("*")):
        if fasta.suffix.lower() not in {".fasta", ".fna", ".fa"}:
            continue
        seq_parts = []
        for line in fasta.read_text(encoding="utf-8").splitlines():
            if line.startswith(">"):
                continue
            seq_parts.append(line.strip())
        genomes.append((fasta.stem, "".join(seq_parts).upper()))
    return genomes


rows = load_pool(Path(sys.argv[1]))
genomes = load_genomes(Path(sys.argv[2]))
lines = ["pathogen\tregion_id\toff_target_genome\tstatus\tnotes"]

for row in rows:
    fwd = row.get("forward_primer", "").upper()
    rev = row.get("reverse_primer", "").upper()
    pathogen = row.get("pathogen", "")
    region = row.get("region_id", "")
    matched = False
    for genome_name, genome_seq in genomes:
        if not genome_seq:
            continue
        if genome_name == pathogen:
            continue
        if fwd and rev and fwd in genome_seq and rev in genome_seq:
            lines.append(f"{pathogen}\t{region}\t{genome_name}\tconflict\tboth primers found in non-target genome")
            matched = True
    if not matched:
        lines.append(f"{pathogen}\t{region}\t-\tpass\tno obvious off-target amplification")

Path(sys.argv[3]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
