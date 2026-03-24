from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / (
    "plugins/primer/multiplex_primer_panel/workflow/my_code/7_final_report.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("final_report", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_final_report_writes_expected_columns(tmp_path):
    module = load_module()
    input_file = tmp_path / "current_pool.tsv"
    panel_file = tmp_path / "multiplex_panel.txt"
    order_file = tmp_path / "synthesis_order.txt"

    input_file.write_text(
        "\t".join(
            [
                "pathogen",
                "region_id",
                "forward_primer",
                "reverse_primer",
                "tm_f",
                "tm_r",
                "gc_f",
                "gc_r",
                "amplicon_seq",
                "amplicon_length",
                "conservation_score",
                "specificity_score",
                "target_sequence",
                "pool_penalty",
            ]
        )
        + "\n"
        + "\t".join(
            [
                "Virus_A",
                "region_1@1",
                "AAA",
                "TTT",
                "60.1",
                "60.2",
                "45.0",
                "46.0",
                "ACGT",
                "150",
                "8",
                "-1",
                "G" * 500,
                "3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    old_argv = sys.argv
    sys.argv = ["7_final_report.py", "--input", str(input_file), "--panel", str(panel_file), "--order", str(order_file)]
    try:
        module.main()
    finally:
        sys.argv = old_argv

    with panel_file.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))

    assert rows[0] == [
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
        "pool_status",
    ]
    assert rows[1][11] == "-1"
    assert rows[1][13] == "pool_1"
    assert rows[1][14] == "3"
