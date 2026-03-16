from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path("E:/代码/bio_ui/plugins/primer/multiplex_primer_panel/workflow/primer_scripts/3_select.py")


def load_module():
    spec = importlib.util.spec_from_file_location("select_conservation", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_self_taxid_uses_smallest_taxid_on_tie():
    module = load_module()
    assert module.parse_self_taxid([222, 111, 222, 111]) == 111


def test_parse_self_taxid_returns_none_when_missing():
    module = load_module()
    assert module.parse_self_taxid([]) is None


def test_score_regions_filters_cross_reactive_hits():
    module = load_module()
    hits = [
        module.BlastHit("region_a", (111,)),
        module.BlastHit("region_a", (111,)),
        module.BlastHit("region_a", (222,)),
        module.BlastHit("region_b", (111,)),
        module.BlastHit("region_b", (111,)),
    ]
    rows = module.score_regions(
        pathogen="Virus_A",
        hits=hits,
        sequences={"region_a": "A" * 500, "region_b": "C" * 500},
        self_taxid=111,
        all_self_taxids={111, 222},
    )
    assert [row.region_id for row in rows] == ["region_b"]
    assert rows[0].conservation_score == 2
    assert rows[0].specificity_score == "1.000"


def test_score_regions_uses_taxid_unknown_fallback():
    module = load_module()
    hits = [
        module.BlastHit("region_a", ()),
        module.BlastHit("region_a", ()),
        module.BlastHit("region_b", ()),
    ]
    rows = module.score_regions(
        pathogen="Virus_A",
        hits=hits,
        sequences={"region_a": "A" * 500, "region_b": "C" * 500},
        self_taxid=None,
        all_self_taxids=set(),
    )
    assert [row.region_id for row in rows] == ["region_a", "region_b"]
    assert rows[0].conservation_score == 2
    assert rows[0].specificity_score == "-1"
