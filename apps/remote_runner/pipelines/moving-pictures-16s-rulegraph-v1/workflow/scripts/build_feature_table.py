import hashlib
from collections import Counter, defaultdict
from pathlib import Path


feature_counts: dict[str, Counter[str]] = defaultdict(Counter)
feature_sequences: dict[str, str] = {}
sample_ids: set[str] = set()

with Path(snakemake.input.reads).open("r", encoding="utf-8", errors="replace") as handle:  # type: ignore[name-defined]
    next(handle, None)
    for line in handle:
        sample_id, sequence = line.rstrip("\n").split("\t", 1)
        sample_ids.add(sample_id)
        feature_id = "feat_" + hashlib.sha1(sequence.encode("ascii", errors="ignore")).hexdigest()[:12]
        feature_sequences[feature_id] = sequence
        feature_counts[feature_id][sample_id] += 1

ordered_samples = sorted(sample_ids)
output_path = Path(snakemake.output.feature_table)  # type: ignore[name-defined]
output_path.parent.mkdir(parents=True, exist_ok=True)
with output_path.open("w", encoding="utf-8", newline="") as handle:
    handle.write("\t".join(["feature_id", "sequence", *ordered_samples]) + "\n")
    for feature_id in sorted(feature_counts):
        counts = feature_counts[feature_id]
        values = [feature_id, feature_sequences[feature_id], *[str(counts[sample_id]) for sample_id in ordered_samples]]
        handle.write("\t".join(values) + "\n")
