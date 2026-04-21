from __future__ import annotations

import json
from pathlib import Path


cfg = snakemake.config  # type: ignore[name-defined]
report_path = Path(snakemake.output.report)  # type: ignore[name-defined]
summary_path = Path(snakemake.output.summary)  # type: ignore[name-defined]
raw_log_path = Path(snakemake.output.raw_log)  # type: ignore[name-defined]

report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(
    f"<section><h1>{cfg['run_id']}</h1><p>Snakemake execution completed.</p></section>",
    encoding="utf-8",
)
summary_path.write_text(
    "sample\tabundance\ttaxonomy\nsample_alpha\t0.42\tBacteroides\n",
    encoding="utf-8",
)
raw_log_path.write_text(
    json.dumps(
        {
            "run_id": cfg["run_id"],
            "pipeline_id": cfg["pipeline_id"],
            "project_id": cfg["project_id"],
            "inputs": cfg.get("inputs", []),
        },
        indent=2,
    ),
    encoding="utf-8",
)

