from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _as_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-deviation", type=float, default=2.0)
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    tm_values = []
    for row in rows:
        for key in ("tm_f", "tm_r"):
            value = _as_float(row.get(key, ""))
            if value is not None:
                tm_values.append(value)
    mean_tm = sum(tm_values) / len(tm_values) if tm_values else 0.0

    lines = ["pathogen\tforward_tm\treverse_tm\tstatus"]
    for row in rows:
        tm_f = _as_float(row.get("tm_f", "")) or 0.0
        tm_r = _as_float(row.get("tm_r", "")) or 0.0
        status = "pass"
        if tm_values and (
            abs(tm_f - mean_tm) > args.max_deviation or abs(tm_r - mean_tm) > args.max_deviation
        ):
            status = "outlier"
        lines.append(f"{row['pathogen']}\t{tm_f:.2f}\t{tm_r:.2f}\t{status}")

    Path(args.output).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
