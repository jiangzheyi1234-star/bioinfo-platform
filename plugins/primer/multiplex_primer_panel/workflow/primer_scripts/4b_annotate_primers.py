from __future__ import annotations

import csv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_region_metadata(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return {(row["pathogen"], row["region_id"]): row for row in reader}


def main() -> None:
    metadata = load_region_metadata(PROJECT_ROOT / "region_metadata.tsv")
    primer_file = PROJECT_ROOT / "my_result" / "primer_result.txt"
    if not primer_file.exists():
        raise SystemExit(f"primer result not found: {primer_file}")

    lines: list[str] = []
    for raw in primer_file.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        if len(parts) < 2:
            lines.append(raw)
            continue
        row = metadata.get((parts[0], parts[1].split("@", 1)[0]), {})
        parts.extend([row.get("conservation_score", ""), row.get("specificity_score", ""), row.get("target_sequence", "")])
        lines.append("\t".join(parts))

    primer_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


if __name__ == "__main__":
    main()
