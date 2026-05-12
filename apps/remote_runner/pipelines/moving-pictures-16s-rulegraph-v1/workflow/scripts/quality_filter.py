from collections import Counter
import sys
from pathlib import Path

sys.path.insert(0, str(Path(getattr(snakemake, "scriptdir", Path(__file__).resolve().parent))))  # type: ignore[name-defined]
from common import mean_quality, write_tsv


params = dict(snakemake.config.get("params") or {})  # type: ignore[name-defined]
min_mean_quality = int(params.get("min_mean_quality", 20))
min_length = int(params.get("min_length", 120))

passed: Counter[str] = Counter()
too_short = 0
low_quality = 0
total = 0

output_path = Path(snakemake.output.reads)  # type: ignore[name-defined]
output_path.parent.mkdir(parents=True, exist_ok=True)
with Path(snakemake.input.reads).open("r", encoding="utf-8", errors="replace") as source, output_path.open("w", encoding="utf-8", newline="") as target:  # type: ignore[name-defined]
    target.write("sample_id\tsequence\n")
    next(source, None)
    for line in source:
        total += 1
        sample_id, sequence, quality = line.rstrip("\n").split("\t", 2)
        if len(sequence) < min_length:
            too_short += 1
            continue
        if mean_quality(quality) < min_mean_quality:
            low_quality += 1
            continue
        passed[sample_id] += 1
        target.write(f"{sample_id}\t{sequence}\n")

rows = [{"metric": "demultiplexed_reads", "value": total}]
rows.extend({"metric": f"passed_reads:{sample_id}", "value": passed[sample_id]} for sample_id in sorted(passed))
rows.extend(
    [
        {"metric": "passed_reads", "value": sum(passed.values())},
        {"metric": "filtered_too_short", "value": too_short},
        {"metric": "filtered_low_quality", "value": low_quality},
        {"metric": "min_mean_quality", "value": min_mean_quality},
        {"metric": "min_length", "value": min_length},
    ]
)
write_tsv(Path(snakemake.output.qc), ["metric", "value"], rows)  # type: ignore[name-defined]
