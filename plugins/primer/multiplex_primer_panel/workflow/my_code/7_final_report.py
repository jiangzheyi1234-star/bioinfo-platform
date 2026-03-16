from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--order", required=True)
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    panel_header = [
        "pathogen",
        "region_id",
        "forward_primer",
        "reverse_primer",
        "Tm_F",
        "Tm_R",
        "GC_F",
        "GC_R",
        "amplicon_length",
        "target_sequence",
        "conservation_score",
        "specificity_score",
        "amplicon_seq",
        "pool_id",
        "pool_dimer_score",
    ]
    order_header = ["primer_name", "sequence", "scale", "purification", "Tm", "notes"]

    with Path(args.panel).open("w", encoding="utf-8", newline="") as panel_handle:
        writer = csv.writer(panel_handle, delimiter="\t")
        writer.writerow(panel_header)
        for row in rows:
            writer.writerow(
                [
                    row.get("pathogen", ""),
                    row.get("region_id", ""),
                    row.get("forward_primer", ""),
                    row.get("reverse_primer", ""),
                    row.get("tm_f", ""),
                    row.get("tm_r", ""),
                    row.get("gc_f", ""),
                    row.get("gc_r", ""),
                    row.get("amplicon_length", ""),
                    row.get("target_sequence", ""),
                    row.get("conservation_score", ""),
                    row.get("specificity_score", ""),
                    row.get("amplicon_seq", ""),
                    "pool_1",
                    row.get("pool_penalty", "0"),
                ]
            )

    with Path(args.order).open("w", encoding="utf-8", newline="") as order_handle:
        writer = csv.writer(order_handle, delimiter="\t")
        writer.writerow(order_header)
        for row in rows:
            pathogen = row.get("pathogen", "")
            region_id = row.get("region_id", "")
            writer.writerow(
                [
                    f"{pathogen}_{region_id}_F",
                    row.get("forward_primer", ""),
                    "25nm",
                    "PAGE",
                    row.get("tm_f", ""),
                    "multiplex_panel",
                ]
            )
            writer.writerow(
                [
                    f"{pathogen}_{region_id}_R",
                    row.get("reverse_primer", ""),
                    "25nm",
                    "PAGE",
                    row.get("tm_r", ""),
                    "multiplex_panel",
                ]
            )


if __name__ == "__main__":
    main()
