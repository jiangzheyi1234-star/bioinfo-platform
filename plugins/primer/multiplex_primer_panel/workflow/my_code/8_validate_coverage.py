from __future__ import annotations

import argparse
import csv
from pathlib import Path


def load_names(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_panel_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--names", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pathogens = load_names(Path(args.names))
    rows = load_panel_rows(Path(args.panel))
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("pathogen", ""), []).append(row)

    output_rows: list[list[str]] = []
    missing: list[str] = []
    for pathogen in pathogens:
        matched = grouped.get(pathogen, [])
        if not matched:
            output_rows.append([pathogen, "missing", "not present in multiplex_panel"])
            missing.append(pathogen)
            continue
        if any(row.get("specificity_score", "") == "-1" for row in matched):
            output_rows.append([pathogen, "pass_no_taxid", "taxid not available in core_nt; specificity unverified"])
        else:
            output_rows.append([pathogen, "pass", "ok"])

    with Path(args.output).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["pathogen", "status", "reason"])
        writer.writerows(output_rows)

    if missing:
        print(f"WARNING: missing results for {len(missing)} pathogens: {', '.join(missing)}")


if __name__ == "__main__":
    main()
