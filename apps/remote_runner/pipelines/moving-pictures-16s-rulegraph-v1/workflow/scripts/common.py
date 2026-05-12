import csv
import gzip
from pathlib import Path


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def identify_inputs(items: list[dict]) -> tuple[Path, Path, Path]:
    by_name = {str(item.get("filename") or "").lower(): Path(str(item["path"])) for item in items}
    metadata = next((path for name, path in by_name.items() if "metadata" in name and name.endswith(".tsv")), None)
    barcodes = next((path for name, path in by_name.items() if "barcode" in name and "fastq" in name), None)
    sequences = next((path for name, path in by_name.items() if "sequence" in name and "fastq" in name), None)
    if metadata is None or barcodes is None or sequences is None:
        names = ", ".join(sorted(by_name))
        raise ValueError(f"Expected sample metadata, barcodes FASTQ, and sequences FASTQ. Received: {names}")
    return metadata, barcodes, sequences


def iter_fastq(path: Path):
    with open_text(path) as handle:
        while True:
            header = handle.readline()
            if not header:
                return
            seq = handle.readline()
            plus = handle.readline()
            qual = handle.readline()
            if not qual:
                raise ValueError(f"FASTQ file ended mid-record: {path.name}")
            yield header.strip(), seq.strip().upper(), plus.strip(), qual.strip()


def mean_quality(qual: str) -> float:
    if not qual:
        return 0.0
    return sum(ord(char) - 33 for char in qual) / len(qual)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
