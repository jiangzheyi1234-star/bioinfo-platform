from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-diff", type=int, default=10)
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    lines = ["pathogen_a\tpathogen_b\tamplicon_diff_bp\tstatus"]
    for idx, row_a in enumerate(rows):
        len_a = int(row_a.get("amplicon_length") or 0)
        for row_b in rows[idx + 1 :]:
            len_b = int(row_b.get("amplicon_length") or 0)
            diff = abs(len_a - len_b)
            status = "pass" if diff >= args.min_diff else "conflict"
            lines.append(f"{row_a['pathogen']}\t{row_b['pathogen']}\t{diff}\t{status}")

    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
