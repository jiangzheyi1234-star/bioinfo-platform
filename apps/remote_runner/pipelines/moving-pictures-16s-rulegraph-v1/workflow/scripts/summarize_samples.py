from collections import defaultdict
import sys
from pathlib import Path

sys.path.insert(0, str(Path(getattr(snakemake, "scriptdir", Path(__file__).resolve().parent))))  # type: ignore[name-defined]
from common import read_tsv, write_tsv


metadata = {row["sample_id"]: row for row in read_tsv(Path(snakemake.input.metadata))}  # type: ignore[name-defined]
demux_counts = {
    row["sample_id"]: int(row["matched_reads"])
    for row in read_tsv(Path(snakemake.input.demux_counts))  # type: ignore[name-defined]
    if not row["sample_id"].startswith("__")
}
qc_rows = read_tsv(Path(snakemake.input.filter_qc))  # type: ignore[name-defined]
passed_counts = {
    row["metric"].split(":", 1)[1]: int(row["value"])
    for row in qc_rows
    if row["metric"].startswith("passed_reads:")
}

feature_counts: dict[str, int] = defaultdict(int)
with Path(snakemake.input.feature_table).open("r", encoding="utf-8", errors="replace") as handle:  # type: ignore[name-defined]
    header = handle.readline().rstrip("\n").split("\t")
    sample_columns = header[2:]
    for line in handle:
        values = line.rstrip("\n").split("\t")
        for sample_id, raw in zip(sample_columns, values[2:]):
            if int(raw or 0) > 0:
                feature_counts[sample_id] += 1

summary = []
for sample_id in sorted(metadata):
    row = metadata[sample_id]
    summary.append(
        {
            "sample_id": sample_id,
            "barcode": row.get("barcode", ""),
            "body_site": row.get("body_site", ""),
            "subject": row.get("subject", ""),
            "matched_reads": demux_counts.get(sample_id, 0),
            "passed_reads": passed_counts.get(sample_id, 0),
            "unique_features": feature_counts.get(sample_id, 0),
        }
    )

total_pairs = next((int(row["matched_reads"]) for row in read_tsv(Path(snakemake.input.demux_counts)) if row["sample_id"] == "__total_pairs__"), 0)  # type: ignore[name-defined]
unmatched = next((int(row["matched_reads"]) for row in read_tsv(Path(snakemake.input.demux_counts)) if row["sample_id"] == "__unmatched__"), 0)  # type: ignore[name-defined]
qc_map = {row["metric"]: int(row["value"]) for row in qc_rows if row["value"].isdigit()}
qc_summary = [
    {"metric": "total_pairs", "value": total_pairs},
    {"metric": "matched_reads", "value": sum(demux_counts.values())},
    {"metric": "passed_reads", "value": sum(passed_counts.values())},
    {"metric": "unmatched_barcodes", "value": unmatched},
    {"metric": "filtered_too_short", "value": qc_map.get("filtered_too_short", 0)},
    {"metric": "filtered_low_quality", "value": qc_map.get("filtered_low_quality", 0)},
    {"metric": "samples_with_reads", "value": sum(1 for item in summary if int(item["matched_reads"]) > 0)},
    {"metric": "features", "value": sum(1 for _ in Path(snakemake.input.feature_table).open("r", encoding="utf-8", errors="replace")) - 1},  # type: ignore[name-defined]
]

write_tsv(Path(snakemake.output.summary), ["sample_id", "barcode", "body_site", "subject", "matched_reads", "passed_reads", "unique_features"], summary)  # type: ignore[name-defined]
write_tsv(Path(snakemake.output.qc_summary), ["metric", "value"], qc_summary)  # type: ignore[name-defined]
