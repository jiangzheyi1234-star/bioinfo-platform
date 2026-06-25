import gzip
import hashlib
import html
import json
from pathlib import Path


def _source_fields(input_item: dict) -> tuple[str, str]:
    source_type = str(input_item.get("sourceType") or "").strip()
    if not source_type:
        if input_item.get("uploadId"):
            source_type = "upload"
        elif input_item.get("artifactBlobId") or input_item.get("artifactId"):
            source_type = "artifact"
    if source_type not in {"upload", "artifact"}:
        raise ValueError("INPUT_SOURCE_TYPE_REQUIRED")
    source_id = str(
        input_item.get("sourceId")
        or input_item.get("uploadId")
        or input_item.get("artifactId")
        or input_item.get("artifactBlobId")
        or ""
    ).strip()
    if not source_id:
        raise ValueError("INPUT_SOURCE_ID_REQUIRED")
    return source_type, source_id


def _file_summary(input_item: dict) -> dict:
    path = Path(str(input_item["path"]))
    source_type, source_id = _source_fields(input_item)
    digest = hashlib.sha256()
    line_count = 0
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "rt" if path.suffix == ".gz" else "r"
    with opener(path, mode, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line_count += 1
            digest.update(line.encode("utf-8", errors="replace"))
    return {
        "source_type": source_type,
        "source_id": source_id,
        "artifact_id": str(input_item.get("artifactId") or ""),
        "artifact_blob_id": str(input_item.get("artifactBlobId") or ""),
        "source_materialization_id": str(input_item.get("sourceMaterializationId") or ""),
        "upstream_run_id": str(input_item.get("upstreamRunId") or ""),
        "filename": str(input_item["filename"]),
        "role": str(input_item.get("role") or "input"),
        "bytes": int(input_item["sizeBytes"]),
        "sha256": str(input_item["sha256"]),
        "read_sha256": digest.hexdigest(),
        "line_count": line_count,
        "gzip": str(path.suffix == ".gz").lower(),
    }


run_id = snakemake.config["run_id"]  # type: ignore[name-defined]
inputs = list(snakemake.config.get("inputs") or [])  # type: ignore[name-defined]
summaries = [_file_summary(item) for item in inputs]

summary_path = Path(snakemake.output.summary)  # type: ignore[name-defined]
report_path = Path(snakemake.output.report)  # type: ignore[name-defined]
raw_log_path = Path(snakemake.output.raw_log)  # type: ignore[name-defined]
for path in (summary_path, report_path, raw_log_path):
    path.parent.mkdir(parents=True, exist_ok=True)

columns = ["source_type", "source_id", "filename", "role", "bytes", "sha256", "line_count", "gzip"]
summary_path.write_text(
    "\t".join(columns)
    + "\n"
    + "\n".join("\t".join(str(row[column]) for column in columns) for row in summaries)
    + "\n",
    encoding="utf-8",
)

rows = "\n".join(
    "<tr>"
    + "".join(f"<td>{html.escape(str(row[column]))}</td>" for column in columns)
    + "</tr>"
    for row in summaries
)
report_path.write_text(
    "<!doctype html><html><head><meta charset=\"utf-8\"><title>File Summary</title>"
    "<style>body{font-family:sans-serif;margin:24px}table{border-collapse:collapse}"
    "td,th{border:1px solid #ddd;padding:6px 8px}th{background:#f5f5f5}</style>"
    f"</head><body><h1>Run {html.escape(str(run_id))}</h1><table><thead><tr>"
    + "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    + f"</tr></thead><tbody>{rows}</tbody></table></body></html>",
    encoding="utf-8",
)
raw_log_path.write_text(json.dumps({"run_id": run_id, "files": summaries}, indent=2), encoding="utf-8")
