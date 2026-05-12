from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(getattr(snakemake, "scriptdir", Path(__file__).resolve().parent))))  # type: ignore[name-defined]
from common import identify_inputs, iter_fastq, read_tsv, write_tsv


inputs = list(snakemake.config.get("inputs") or [])  # type: ignore[name-defined]
_metadata_path, barcodes_path, sequences_path = identify_inputs(inputs)
barcode_to_sample = {row["barcode"].upper(): row["sample_id"] for row in read_tsv(Path(snakemake.input.barcode_map))}  # type: ignore[name-defined]

counts: Counter[str] = Counter()
unmatched = 0
total = 0
reads_path = Path(snakemake.output.reads)  # type: ignore[name-defined]
reads_path.parent.mkdir(parents=True, exist_ok=True)
with reads_path.open("w", encoding="utf-8", newline="") as handle:
    handle.write("sample_id\tsequence\tquality\n")
    for barcode_record, sequence_record in zip(iter_fastq(barcodes_path), iter_fastq(sequences_path)):
        total += 1
        sample_id = barcode_to_sample.get(barcode_record[1])
        if not sample_id:
            unmatched += 1
            continue
        counts[sample_id] += 1
        handle.write(f"{sample_id}\t{sequence_record[1]}\t{sequence_record[3]}\n")

rows = [{"sample_id": sample_id, "matched_reads": counts[sample_id]} for sample_id in sorted(counts)]
rows.append({"sample_id": "__unmatched__", "matched_reads": unmatched})
rows.append({"sample_id": "__total_pairs__", "matched_reads": total})
write_tsv(Path(snakemake.output.counts), ["sample_id", "matched_reads"], rows)  # type: ignore[name-defined]
