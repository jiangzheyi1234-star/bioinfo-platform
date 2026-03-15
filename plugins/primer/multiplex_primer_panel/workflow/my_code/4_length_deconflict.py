from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-diff", type=int, default=10)
    args = parser.parse_args()

    Path(args.output).write_text(
        "pathogen_a\tpathogen_b\tamplicon_diff_bp\tstatus\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
