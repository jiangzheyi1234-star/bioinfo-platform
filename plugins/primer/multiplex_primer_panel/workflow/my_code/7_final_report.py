from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--order", required=True)
    args = parser.parse_args()

    panel_rows = []
    order_rows = ["primer_name\tsequence\tscale\tpurification\tTm\tnotes"]
    for line in Path(args.input).read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        pathogen = parts[0]
        region_id = parts[1]
        forward = parts[2]
        reverse = parts[3]
        amplicon_length = parts[4] if len(parts) > 4 else ""
        panel_rows.append("\t".join([pathogen, region_id, forward, reverse, amplicon_length, "pass"]))
        order_rows.append(f"{pathogen}_F\t{forward}\t25nm\tPAGE\t\tpanel")
        order_rows.append(f"{pathogen}_R\t{reverse}\t25nm\tPAGE\t\tpanel")

    Path(args.panel).write_text("\n".join(panel_rows) + ("\n" if panel_rows else ""), encoding="utf-8")
    Path(args.order).write_text("\n".join(order_rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
