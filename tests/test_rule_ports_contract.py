from __future__ import annotations

from core.contracts.rule_ports import (
    matched_compatibility_fields,
    mismatched_compatibility_field,
    port_compatibility_score,
    port_spec_from_rule_item,
    ports_compatible,
)


def test_port_compatibility_score_rewards_shared_semantics() -> None:
    input_spec = {"type": "file", "format": "format_2572", "data": "data_2044"}
    output_spec = {"type": "file", "format": "format_2572", "data": "data_2044"}

    assert port_compatibility_score(input_spec, output_spec) == 12
    assert ports_compatible(input_spec, output_spec)
    assert matched_compatibility_fields(input_spec, output_spec) == ["type", "data", "format"]
    assert mismatched_compatibility_field(input_spec, output_spec) == ""


def test_port_compatibility_score_blocks_conflicting_fields() -> None:
    input_spec = {"type": "file", "format": "format_2572"}
    output_spec = {"type": "file", "format": "format_1930"}

    assert port_compatibility_score(input_spec, output_spec) is None
    assert not ports_compatible(input_spec, output_spec)
    assert mismatched_compatibility_field(input_spec, output_spec) == "format"


def test_port_compatibility_score_keeps_one_sided_evidence_manual() -> None:
    assert port_compatibility_score({"type": "file", "format": "format_2572"}, {"type": "file"}) == 5
    assert port_compatibility_score({"format": "format_2572"}, {}) == 1
    assert port_compatibility_score({}, {}) == 0


def test_port_spec_from_rule_item_accepts_edam_aliases() -> None:
    assert port_spec_from_rule_item(
        {
            "name": "reads",
            "type": "file",
            "edamFormat": "format_2572",
            "edamData": "data_2044",
        }
    ) == {"type": "file", "data": "data_2044", "format": "format_2572"}

