"""Reusable parsers for ToolBridge result views."""

from __future__ import annotations


def parse_primer_result_text(content: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in content.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 6:
            continue
        if parts[0].lower() == "pathogen":
            continue
        if len(parts) >= 10:
            position = parts[8]
            amplicon = parts[9]
        else:
            position = parts[4]
            amplicon = parts[5]
        rows.append(
            {
                "pathogen": parts[0],
                "region_id": parts[1],
                "forward_primer": parts[2],
                "reverse_primer": parts[3],
                "position": position,
                "amplicon": amplicon,
            }
        )
    return rows


def parse_multiplex_result_text(content: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in content.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue
        if parts[0].lower() == "pathogen":
            continue
        if len(parts) <= 10:
            rows.append(
                {
                    "pathogen": parts[0],
                    "region_id": parts[1],
                    "forward_primer": parts[2],
                    "reverse_primer": parts[3],
                    "tm_f": parts[4] if len(parts) > 4 else "",
                    "tm_r": parts[5] if len(parts) > 5 else "",
                    "gc_f": parts[6] if len(parts) > 6 else "",
                    "gc_r": parts[7] if len(parts) > 7 else "",
                    "amplicon_length": parts[8] if len(parts) > 8 else "",
                    "target_sequence": "",
                    "conservation_score": "",
                    "specificity_score": "",
                    "amplicon_seq": "",
                    "pool_id": "",
                    "pool_dimer_score": parts[9] if len(parts) > 9 else (parts[5] if len(parts) > 5 else ""),
                    "pool_score": parts[9] if len(parts) > 9 else (parts[5] if len(parts) > 5 else ""),
                }
            )
            continue
        rows.append(
            {
                "pathogen": parts[0],
                "region_id": parts[1],
                "forward_primer": parts[2],
                "reverse_primer": parts[3],
                "tm_f": parts[4] if len(parts) > 4 else "",
                "tm_r": parts[5] if len(parts) > 5 else "",
                "gc_f": parts[6] if len(parts) > 6 else "",
                "gc_r": parts[7] if len(parts) > 7 else "",
                "amplicon_length": parts[8] if len(parts) > 8 else (parts[4] if len(parts) > 4 else ""),
                "target_sequence": parts[9] if len(parts) > 9 else "",
                "conservation_score": parts[10] if len(parts) > 10 else "",
                "specificity_score": parts[11] if len(parts) > 11 else "",
                "amplicon_seq": parts[12] if len(parts) > 12 else "",
                "pool_id": parts[13] if len(parts) > 13 else "",
                "pool_dimer_score": parts[14] if len(parts) > 14 else (parts[9] if len(parts) > 9 else ""),
                "pool_score": parts[14] if len(parts) > 14 else (parts[9] if len(parts) > 9 else (parts[5] if len(parts) > 5 else "")),
                "pool_status": parts[15] if len(parts) > 15 else "",
            }
        )
    return rows


def build_multiplex_columns(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Hide multiplex columns that are empty across all rows."""
    base_columns = [
        {"key": "pathogen", "label": "Pathogen"},
        {"key": "region_id", "label": "Region ID"},
        {"key": "forward_primer", "label": "Forward Primer"},
        {"key": "reverse_primer", "label": "Reverse Primer"},
        {"key": "amplicon_length", "label": "Amplicon Length"},
    ]
    optional_columns = [
        {"key": "target_sequence", "label": "Target Sequence"},
        {"key": "conservation_score", "label": "Conservation Score"},
        {"key": "specificity_score", "label": "Specificity Score"},
        {"key": "pool_dimer_score", "label": "Pool Dimer Score"},
        {"key": "pool_status", "label": "Pool Status"},
    ]

    if not rows:
        return base_columns + [{"key": "pool_dimer_score", "label": "Pool Dimer Score"}]

    visible_optional: list[dict[str, str]] = []
    for col in optional_columns:
        key = col["key"]
        if any(str(row.get(key, "")).strip() for row in rows):
            visible_optional.append(col)
    return base_columns + visible_optional

