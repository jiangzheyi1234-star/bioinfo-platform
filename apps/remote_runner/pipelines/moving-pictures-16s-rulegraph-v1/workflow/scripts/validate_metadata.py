import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(getattr(snakemake, "scriptdir", Path(__file__).resolve().parent))))  # type: ignore[name-defined]
from common import identify_inputs, write_tsv


inputs = list(snakemake.config.get("inputs") or [])  # type: ignore[name-defined]
metadata_path, barcodes_path, sequences_path = identify_inputs(inputs)

rows: list[dict[str, object]] = []
barcode_rows: list[dict[str, object]] = []
with metadata_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
    reader = csv.DictReader(handle, delimiter="\t")
    if not reader.fieldnames:
        raise ValueError("Sample metadata is empty.")
    sample_column = next(
        (name for name in reader.fieldnames if name.lower() in {"sampleid", "sample-id", "#sampleid", "id"}),
        reader.fieldnames[0],
    )
    barcode_column = next((name for name in reader.fieldnames if name.lower() == "barcode-sequence"), "")
    if not barcode_column:
        raise ValueError("Sample metadata must include barcode-sequence.")
    for row in reader:
        sample_id = str(row.get(sample_column) or "").strip()
        barcode = str(row.get(barcode_column) or "").strip().upper()
        if not sample_id or sample_id.startswith("#q2:") or not barcode:
            continue
        body_site = str(row.get("body-site") or row.get("body_site") or "")
        subject = str(row.get("subject") or "")
        rows.append({"sample_id": sample_id, "barcode": barcode, "body_site": body_site, "subject": subject})
        barcode_rows.append({"barcode": barcode, "sample_id": sample_id})

if not rows:
    raise ValueError("Sample metadata did not contain usable sample rows.")

write_tsv(Path(snakemake.output.metadata), ["sample_id", "barcode", "body_site", "subject"], rows)  # type: ignore[name-defined]
write_tsv(Path(snakemake.output.barcode_map), ["barcode", "sample_id"], barcode_rows)  # type: ignore[name-defined]
Path(snakemake.output.validation).write_text(  # type: ignore[name-defined]
    json.dumps(
        {
            "samples": len(rows),
            "barcodes": len(barcode_rows),
            "metadata": str(metadata_path),
            "barcodes_fastq": str(barcodes_path),
            "sequences_fastq": str(sequences_path),
        },
        indent=2,
    ),
    encoding="utf-8",
)
