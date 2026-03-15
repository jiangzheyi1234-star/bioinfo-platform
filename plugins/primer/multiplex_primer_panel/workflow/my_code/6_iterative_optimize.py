from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--max-iterations", type=int, default=50)
    args = parser.parse_args()

    source = Path(args.input)
    rows = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    picked = []
    seen = set()
    for row in rows:
        pathogen = row.split("\t", 1)[0]
        if pathogen in seen:
            continue
        seen.add(pathogen)
        picked.append(row)

    Path(args.output).write_text("\n".join(picked) + ("\n" if picked else ""), encoding="utf-8")
    Path(args.log).write_text(
        f"iterations\t1\nselected\t{len(picked)}\nmax_iterations\t{args.max_iterations}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
