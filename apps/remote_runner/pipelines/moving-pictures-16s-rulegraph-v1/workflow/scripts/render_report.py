import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(getattr(snakemake, "scriptdir", Path(__file__).resolve().parent))))  # type: ignore[name-defined]
from common import read_tsv


run_id = snakemake.config["run_id"]  # type: ignore[name-defined]
summary = read_tsv(Path(snakemake.input.summary))  # type: ignore[name-defined]
qc_rows = read_tsv(Path(snakemake.input.qc_summary))  # type: ignore[name-defined]
validation = json.loads(Path(snakemake.input.validation).read_text(encoding="utf-8"))  # type: ignore[name-defined]

top_samples = sorted(summary, key=lambda row: int(row["passed_reads"]), reverse=True)[:8]
sample_rows = "".join(
    "<tr>"
    f"<td>{html.escape(row['sample_id'])}</td>"
    f"<td>{html.escape(row['body_site'])}</td>"
    f"<td>{html.escape(row['matched_reads'])}</td>"
    f"<td>{html.escape(row['passed_reads'])}</td>"
    f"<td>{html.escape(row['unique_features'])}</td>"
    "</tr>"
    for row in top_samples
)
qc_cards = "".join(
    f"<div class='metric'><span>{html.escape(row['metric'])}</span><strong>{html.escape(row['value'])}</strong></div>"
    for row in qc_rows
)
Path(snakemake.output.report).write_text(  # type: ignore[name-defined]
    "<!doctype html><html><head><meta charset='utf-8'><title>Moving Pictures 16S Rulegraph</title>"
    "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:32px;color:#0f172a}"
    ".metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}"
    ".metric{border:1px solid #e2e8f0;border-radius:14px;padding:14px;background:#f8fafc}.metric span{display:block;color:#64748b;font-size:12px}.metric strong{font-size:22px}"
    "table{border-collapse:collapse;width:100%;margin-top:14px}td,th{border-bottom:1px solid #e2e8f0;padding:9px;text-align:left}th{color:#64748b;font-size:12px}</style>"
    f"</head><body><h1>Moving Pictures 16S Rulegraph</h1><p>Run {html.escape(str(run_id))}</p><div class='metrics'>{qc_cards}</div>"
    "<h2>Top samples</h2><table><thead><tr><th>sample</th><th>body site</th><th>matched</th><th>passed</th><th>features</th></tr></thead>"
    f"<tbody>{sample_rows}</tbody></table></body></html>",
    encoding="utf-8",
)
Path(snakemake.output.raw_log).write_text(  # type: ignore[name-defined]
    json.dumps({"run_id": run_id, "validation": validation, "qc": qc_rows}, indent=2),
    encoding="utf-8",
)
