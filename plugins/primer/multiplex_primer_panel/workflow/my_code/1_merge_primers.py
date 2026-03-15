from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


HEADER = [
    "pathogen",
    "region_id",
    "forward_primer",
    "reverse_primer",
    "tm_f",
    "tm_r",
    "gc_f",
    "gc_r",
    "position",
    "amplicon_seq",
    "amplicon_length",
    "candidate_rank",
]


def parse_candidate(parts: list[str]) -> dict[str, str] | None:
    if len(parts) >= 10:
        position = parts[8]
        amplicon_seq = parts[9]
        payload = {
            "pathogen": parts[0],
            "region_id": parts[1],
            "forward_primer": parts[2],
            "reverse_primer": parts[3],
            "tm_f": parts[4],
            "tm_r": parts[5],
            "gc_f": parts[6],
            "gc_r": parts[7],
            "position": position,
            "amplicon_seq": amplicon_seq,
        }
    elif len(parts) >= 6:
        position = parts[4]
        amplicon_seq = parts[5]
        payload = {
            "pathogen": parts[0],
            "region_id": parts[1],
            "forward_primer": parts[2],
            "reverse_primer": parts[3],
            "tm_f": "",
            "tm_r": "",
            "gc_f": "",
            "gc_r": "",
            "position": position,
            "amplicon_seq": amplicon_seq,
        }
    else:
        return None

    payload["amplicon_length"] = str(len(amplicon_seq))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fasta", required=True)
    args = parser.parse_args()

    src = Path(args.input)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for raw in src.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        candidate = parse_candidate(line.split("\t"))
        if candidate is None:
            continue
        grouped[candidate["pathogen"]].append(candidate)

    rows: list[dict[str, str]] = []
    fasta_lines: list[str] = []
    for pathogen in sorted(grouped):
        for rank, candidate in enumerate(grouped[pathogen], start=1):
            candidate["candidate_rank"] = str(rank)
            rows.append(candidate)
            primer_prefix = f"{pathogen}|{candidate['region_id']}|{rank}"
            fasta_lines.extend(
                [
                    f">{primer_prefix}|F",
                    candidate["forward_primer"],
                    f">{primer_prefix}|R",
                    candidate["reverse_primer"],
                ]
            )

    with Path(args.output).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    fasta_text = "\n".join(fasta_lines)
    Path(args.fasta).write_text(f"{fasta_text}\n" if fasta_text else "", encoding="utf-8")


if __name__ == "__main__":
    main()
