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


def load_tier_map(names_path: Path) -> dict[str, int]:
    """Load tier info from region_metadata.tsv (sibling of name.txt)."""
    metadata_path = names_path.parent / "region_metadata.tsv"
    tier_map: dict[str, int] = {}
    if not metadata_path.exists():
        return tier_map
    with metadata_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            pathogen = row.get("pathogen", "")
            tier_str = row.get("tier", "")
            if pathogen and tier_str:
                try:
                    tier = int(tier_str)
                except ValueError:
                    continue
                # Keep the minimum (best) tier for each pathogen
                if pathogen not in tier_map or tier < tier_map[pathogen]:
                    tier_map[pathogen] = tier
    return tier_map


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--names", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    names_path = Path(args.names)
    pathogens = load_names(names_path)
    rows = load_panel_rows(Path(args.panel))
    tier_map = load_tier_map(names_path)

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row.get("pathogen", ""), []).append(row)

    output_rows: list[list[str]] = []
    missing: list[str] = []
    for pathogen in pathogens:
        matched = grouped.get(pathogen, [])
        tier = tier_map.get(pathogen, "")

        if not matched:
            output_rows.append([pathogen, "missing", "not present in multiplex_panel", str(tier) if tier else ""])
            missing.append(pathogen)
            continue

        # Check if marked as no_candidate
        if any(row.get("pool_id", "") == "no_candidate" for row in matched):
            output_rows.append([pathogen, "no_candidate", "no primer candidates generated", str(tier) if tier else ""])
            missing.append(pathogen)
            continue

        if any(row.get("specificity_score", "") == "-1" for row in matched):
            output_rows.append([pathogen, "pass_no_taxid", "taxid not available in core_nt; specificity unverified", str(tier) if tier else ""])
        else:
            output_rows.append([pathogen, "pass", "ok", str(tier) if tier else ""])

    with Path(args.output).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["pathogen", "status", "reason", "tier"])
        writer.writerows(output_rows)

    if missing:
        print(f"WARNING: missing results for {len(missing)} pathogens: {', '.join(missing)}")


if __name__ == "__main__":
    main()
