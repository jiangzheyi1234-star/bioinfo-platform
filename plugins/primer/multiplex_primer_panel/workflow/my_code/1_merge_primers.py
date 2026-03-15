from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fasta", required=True)
    args = parser.parse_args()

    src = Path(args.input)
    rows = []
    for line in src.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        rows.append(parts)

    out = Path(args.output)
    out.write_text(
        "\n".join(
            "\t".join(
                [
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                    parts[4] if len(parts) > 4 else "",
                    parts[5] if len(parts) > 5 else "",
                    parts[6] if len(parts) > 6 else "",
                    parts[7] if len(parts) > 7 else "",
                    parts[8] if len(parts) > 8 else "",
                    parts[9] if len(parts) > 9 else "",
                ]
            )
            for parts in rows
        ),
        encoding="utf-8",
    )

    fasta_lines = []
    for idx, parts in enumerate(rows, start=1):
        fasta_lines.append(f">F_{idx}_{parts[0]}")
        fasta_lines.append(parts[2])
        fasta_lines.append(f">R_{idx}_{parts[0]}")
        fasta_lines.append(parts[3])
    Path(args.fasta).write_text("\n".join(fasta_lines) + ("\n" if fasta_lines else ""), encoding="utf-8")


if __name__ == "__main__":
    main()
