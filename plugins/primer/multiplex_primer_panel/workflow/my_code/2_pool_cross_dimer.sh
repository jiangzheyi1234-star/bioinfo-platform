#!/bin/bash
set -euo pipefail

INPUT_TSV="${1:?missing input tsv}"
OUTPUT_TXT="${2:?missing output path}"
MAX_SCORE="${3:-10}"
MAX_DG="${4:-6}"

python - "$INPUT_TSV" "$OUTPUT_TXT" "$MAX_SCORE" "$MAX_DG" <<'PY'
from __future__ import annotations

import csv
import sys
from pathlib import Path


COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def revcomp(seq: str) -> str:
    return seq.translate(COMP)[::-1]


def trailing_match(a: str, b: str) -> int:
    max_len = min(len(a), len(b))
    best = 0
    for length in range(4, max_len + 1):
        if a[-length:] == b[:length]:
            best = length
    return best


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.readline()
        handle.seek(0)
        if sample.startswith("pathogen\t"):
            return list(csv.DictReader(handle, delimiter="\t"))
        rows = []
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            rows.append(
                {
                    "pathogen": parts[0],
                    "region_id": parts[1],
                    "forward_primer": parts[2],
                    "reverse_primer": parts[3],
                }
            )
        return rows


rows = load_rows(Path(sys.argv[1]))
max_score = float(sys.argv[3])
max_dg = float(sys.argv[4])
lines = ["pathogen_A\tprimer_A\tpathogen_B\tprimer_B\tscore\tdg"]

primers: list[tuple[str, str, str]] = []
for row in rows:
    primers.append((row["pathogen"], f"{row['region_id']}_F", row["forward_primer"]))
    primers.append((row["pathogen"], f"{row['region_id']}_R", row["reverse_primer"]))

for idx, (pathogen_a, name_a, seq_a) in enumerate(primers):
    for pathogen_b, name_b, seq_b in primers[idx + 1 :]:
        if pathogen_a == pathogen_b:
            continue
        overlap = max(trailing_match(seq_a, revcomp(seq_b)), trailing_match(seq_b, revcomp(seq_a)))
        if overlap < 4:
            continue
        score = overlap * 2
        dg = float(overlap)
        if score >= max_score or dg >= max_dg:
            lines.append(f"{pathogen_a}\t{name_a}\t{pathogen_b}\t{name_b}\t{score}\t{dg:.1f}")

Path(sys.argv[2]).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
