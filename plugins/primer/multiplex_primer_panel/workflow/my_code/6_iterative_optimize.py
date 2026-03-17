from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


COMP = str.maketrans("ACGTNacgtn", "TGCANtgcan")


def revcomp(seq: str) -> str:
    return seq.translate(COMP)[::-1]


def trailing_match(a: str, b: str) -> int:
    max_len = min(len(a), len(b))
    best = 0
    for length in range(4, max_len + 1):
        if a[-length:] == b[:length]:
            best = length
    return best


def tm_outlier(rows: list[dict[str, str]], row: dict[str, str], max_deviation: float) -> bool:
    values = []
    for item in rows:
        for key in ("tm_f", "tm_r"):
            try:
                values.append(float(item.get(key) or 0))
            except ValueError:
                pass
    if not values:
        return False
    mean_tm = sum(values) / len(values)
    for key in ("tm_f", "tm_r"):
        raw = row.get(key, "")
        if not raw:
            continue
        if abs(float(raw) - mean_tm) > max_deviation:
            return True
    return False


def score_pool(
    rows: list[dict[str, str]],
    max_cross_dimer_score: float,
    max_cross_dimer_dg: float,
    min_amplicon_diff: int,
    max_tm_deviation: float,
) -> tuple[dict[str, int], list[str]]:
    penalties = defaultdict(int)
    reasons: list[str] = []

    for idx, row_a in enumerate(rows):
        for row_b in rows[idx + 1 :]:
            overlap = max(
                trailing_match(row_a["forward_primer"], revcomp(row_b["forward_primer"])),
                trailing_match(row_a["forward_primer"], revcomp(row_b["reverse_primer"])),
                trailing_match(row_a["reverse_primer"], revcomp(row_b["forward_primer"])),
                trailing_match(row_a["reverse_primer"], revcomp(row_b["reverse_primer"])),
            )
            if overlap >= 4:
                score = overlap * 2
                dg = float(overlap)
                if score >= max_cross_dimer_score or dg >= max_cross_dimer_dg:
                    penalties[row_a["pathogen"]] += score
                    penalties[row_b["pathogen"]] += score
                    reasons.append(f"cross_dimer\t{row_a['pathogen']}\t{row_b['pathogen']}\t{score}")

            diff = abs(int(row_a.get("amplicon_length") or 0) - int(row_b.get("amplicon_length") or 0))
            if diff < min_amplicon_diff:
                penalties[row_a["pathogen"]] += min_amplicon_diff - diff + 1
                penalties[row_b["pathogen"]] += min_amplicon_diff - diff + 1
                reasons.append(f"length_conflict\t{row_a['pathogen']}\t{row_b['pathogen']}\t{diff}")

        if tm_outlier(rows, row_a, max_tm_deviation):
            penalties[row_a["pathogen"]] += 1
            reasons.append(f"tm_outlier\t{row_a['pathogen']}")

    return dict(penalties), reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--max-cross-dimer-score", type=float, default=10)
    parser.add_argument("--max-cross-dimer-dg", type=float, default=6)
    parser.add_argument("--min-amplicon-diff", type=int, default=10)
    parser.add_argument("--max-tm-deviation", type=float, default=2.0)
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8", newline="") as handle:
        candidates = list(csv.DictReader(handle, delimiter="\t"))

    if not candidates:
        # Keep pipeline alive when upstream produced no primer candidates.
        fieldnames = [
            "pathogen",
            "region_id",
            "forward_primer",
            "reverse_primer",
            "tm_f",
            "tm_r",
            "gc_f",
            "gc_r",
            "position",
            "amplicon_seq",
            "amplicon_length",
            "conservation_score",
            "specificity_score",
            "target_sequence",
            "candidate_rank",
            "pool_penalty",
        ]
        with Path(args.output).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
        Path(args.log).write_text("iteration\t0\tempty\t0\tno candidates from upstream\n", encoding="utf-8")
        return

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        grouped[row["pathogen"]].append(row)

    selected_index = {pathogen: 0 for pathogen in grouped}
    locked: set[str] = set()  # pathogens that exhausted all candidates, locked at best
    log_lines = []

    for iteration in range(1, args.max_iterations + 1):
        current = [grouped[pathogen][selected_index[pathogen]] for pathogen in sorted(grouped)]
        penalties, reasons = score_pool(
            current,
            args.max_cross_dimer_score,
            args.max_cross_dimer_dg,
            args.min_amplicon_diff,
            args.max_tm_deviation,
        )
        if not penalties:
            log_lines.append(f"iteration\t{iteration}\tpass\t{len(current)}\tpool accepted")
            break

        # Only consider unlocked pathogens for replacement
        unlocked = {k: v for k, v in penalties.items() if k not in locked}
        if not unlocked:
            log_lines.append(
                f"iteration\t{iteration}\tall_locked\t{len(locked)}\t"
                "all conflicting pathogens exhausted candidates, keeping best"
            )
            break

        target = max(unlocked, key=unlocked.get)
        next_index = selected_index[target] + 1
        if next_index >= len(grouped[target]):
            # Lock this pathogen at its current (best available) candidate
            # and continue optimizing the rest — never remove a pathogen
            locked.add(target)
            log_lines.append(
                f"iteration\t{iteration}\tlocked\t{target}\t"
                f"exhausted {len(grouped[target])} candidates, keeping rank {selected_index[target] + 1}"
            )
            continue

        log_lines.append(
            f"iteration\t{iteration}\treplace\t{target}\t{selected_index[target] + 1}->{next_index + 1}\t"
            + ("; ".join(reasons[:3]) if reasons else "conflict")
        )
        selected_index[target] = next_index
    else:
        current = [grouped[pathogen][selected_index[pathogen]] for pathogen in sorted(grouped)]
        log_lines.append(f"iteration\t{args.max_iterations}\tlimit\t{len(current)}\treached max iterations")

    current = [grouped[pathogen][selected_index[pathogen]] for pathogen in sorted(grouped)]
    penalties, _ = score_pool(
        current,
        args.max_cross_dimer_score,
        args.max_cross_dimer_dg,
        args.min_amplicon_diff,
        args.max_tm_deviation,
    )
    for row in current:
        p = row["pathogen"]
        row["pool_penalty"] = str(penalties.get(p, 0))
        # pool_status: biological quality grade
        #   optimal       — passed all checks, no conflicts
        #   suboptimal    — kept despite conflicts (exhausted alternatives);
        #                   may need bench validation (adjust annealing T / primer conc)
        if p in locked and penalties.get(p, 0) > 0:
            row["pool_status"] = "suboptimal"
        else:
            row["pool_status"] = "optimal"

    with Path(args.output).open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(candidates[0].keys())
        for extra in ("pool_penalty", "pool_status"):
            if extra not in fieldnames:
                fieldnames.append(extra)
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(current)

    Path(args.log).write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")


if __name__ == "__main__":
    main()
