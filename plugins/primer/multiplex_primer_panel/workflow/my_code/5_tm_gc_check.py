from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-deviation", type=float, default=2.0)
    args = parser.parse_args()

    Path(args.output).write_text(
        "pathogen\tforward_tm\treverse_tm\tstatus\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
