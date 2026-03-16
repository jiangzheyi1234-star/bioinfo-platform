from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


MIN_IDENTITY = 100.0
MIN_LENGTH = 500
TOP_K = 6


@dataclass
class BlastHit:
    region_id: str
    staxids: tuple[int, ...]


@dataclass
class RegionRecord:
    pathogen: str
    region_id: str
    conservation_score: int
    specificity_score: str
    target_sequence: str


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_pathogens(name_file: Path) -> list[str]:
    return [line.strip() for line in name_file.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_staxids(raw: str) -> tuple[int, ...]:
    text = (raw or "").strip()
    if not text or text.upper() == "N/A":
        return ()
    values: list[int] = []
    for chunk in text.replace(";", ",").split(","):
        part = chunk.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return tuple(values)


def parse_self_taxid(all_staxids: list[int]) -> int | None:
    if not all_staxids:
        return None
    counts = Counter(all_staxids)
    max_count = max(counts.values())
    tied = [taxid for taxid, count in counts.items() if count == max_count]
    return min(tied)


def read_split_sequences(split_file: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    header = ""
    seq_parts: list[str] = []
    for line in split_file.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        if line.startswith(">"):
            if header:
                records[header] = "".join(seq_parts)
            header = line[1:].strip()
            seq_parts = []
        else:
            seq_parts.append(line.strip())
    if header:
        records[header] = "".join(seq_parts)
    return records


def read_filtered_hits(pathogen: str, project_root: Path) -> list[BlastHit]:
    blast_dir = project_root / "blast"
    filt_dir = project_root / "blast_filt"
    filt_dir.mkdir(exist_ok=True)
    blast_file = blast_dir / f"{pathogen}.txt"
    filt_file = filt_dir / f"{pathogen}.txt"

    hits: list[BlastHit] = []
    out_lines: list[str] = []
    if not blast_file.exists():
        filt_file.write_text("", encoding="utf-8")
        return hits

    for raw in blast_file.read_text(encoding="utf-8").splitlines():
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 14:
            continue
        try:
            pident = float(parts[2])
            length = int(float(parts[3]))
        except ValueError:
            continue
        if pident != MIN_IDENTITY or length < MIN_LENGTH:
            continue
        out_lines.append(raw)
        hits.append(BlastHit(region_id=parts[0], staxids=parse_staxids(parts[13])))

    filt_file.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return hits


def collect_self_taxids(pathogens: list[str], hits_by_pathogen: dict[str, list[BlastHit]]) -> dict[str, int | None]:
    resolved: dict[str, int | None] = {}
    for pathogen in pathogens:
        all_staxids = [taxid for hit in hits_by_pathogen.get(pathogen, []) for taxid in hit.staxids]
        resolved[pathogen] = parse_self_taxid(all_staxids)
    return resolved


def score_regions(
    pathogen: str,
    hits: list[BlastHit],
    sequences: dict[str, str],
    self_taxid: int | None,
    all_self_taxids: set[int],
) -> list[RegionRecord]:
    grouped: dict[str, list[BlastHit]] = defaultdict(list)
    for hit in hits:
        grouped[hit.region_id].append(hit)

    rows: list[RegionRecord] = []
    for region_id, region_hits in grouped.items():
        total_hits = len(region_hits)
        if total_hits == 0:
            continue

        if self_taxid is None:
            conservation_score = total_hits
            specificity_score = "-1"
        else:
            same_taxid_hits = sum(1 for hit in region_hits if self_taxid in hit.staxids)
            non_self_hits = sum(1 for hit in region_hits if any(taxid != self_taxid for taxid in hit.staxids))
            cross_reactive = any(
                any(taxid in all_self_taxids and taxid != self_taxid for taxid in hit.staxids)
                for hit in region_hits
            )
            conservation_score = same_taxid_hits
            specificity_value = 1.0 - (non_self_hits / total_hits)
            specificity_score = f"{specificity_value:.3f}"
            if specificity_value < 0.9 or cross_reactive:
                continue

        rows.append(
            RegionRecord(
                pathogen=pathogen,
                region_id=region_id,
                conservation_score=conservation_score,
                specificity_score=specificity_score,
                target_sequence=sequences.get(region_id, ""),
            )
        )

    rows.sort(
        key=lambda row: (
            -row.conservation_score,
            -(float(row.specificity_score) if row.specificity_score != "-1" else -1.0),
            row.region_id,
        )
    )
    return rows[:TOP_K]


def write_conserved_fasta(pathogen: str, rows: list[RegionRecord], output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    lines: list[str] = []
    for row in rows:
        lines.extend([f">{row.region_id}", row.target_sequence])
    (output_dir / f"{pathogen}.fasta").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_region_metadata(rows: list[RegionRecord], output_file: Path) -> None:
    with output_file.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["pathogen", "region_id", "conservation_score", "specificity_score", "target_sequence"])
        for row in rows:
            writer.writerow(
                [
                    row.pathogen,
                    row.region_id,
                    row.conservation_score,
                    row.specificity_score,
                    row.target_sequence,
                ]
            )


def main() -> None:
    pathogens = load_pathogens(PROJECT_ROOT / "name.txt")
    hits_by_pathogen = {pathogen: read_filtered_hits(pathogen, PROJECT_ROOT) for pathogen in pathogens}
    self_taxids = collect_self_taxids(pathogens, hits_by_pathogen)
    known_self_taxids = {taxid for taxid in self_taxids.values() if taxid is not None}

    all_rows: list[RegionRecord] = []
    conserved_dir = PROJECT_ROOT / "conserved_seq"
    conserved_dir.mkdir(exist_ok=True)

    for pathogen in pathogens:
        split_file = PROJECT_ROOT / "splits" / f"{pathogen}.fasta"
        sequences = read_split_sequences(split_file) if split_file.exists() else {}
        rows = score_regions(
            pathogen=pathogen,
            hits=hits_by_pathogen.get(pathogen, []),
            sequences=sequences,
            self_taxid=self_taxids.get(pathogen),
            all_self_taxids=known_self_taxids,
        )
        write_conserved_fasta(pathogen, rows, conserved_dir)
        all_rows.extend(rows)

    write_region_metadata(all_rows, PROJECT_ROOT / "region_metadata.tsv")


if __name__ == "__main__":
    main()
