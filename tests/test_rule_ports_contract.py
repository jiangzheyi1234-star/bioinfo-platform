from __future__ import annotations

import json
from pathlib import Path

from core.contracts.rule_ports import (
    generic_compatibility_fields,
    matched_advisory_compatibility_fields,
    matched_compatibility_fields,
    mismatched_compatibility_field,
    port_compatibility_decision,
    port_compatibility_score,
    port_spec_from_rule_item,
    ports_compatible,
)


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_PORT_CASES = ROOT / "tests" / "fixtures" / "semantic_port_cases.json"


def test_port_compatibility_matches_golden_cases() -> None:
    cases = json.loads(SEMANTIC_PORT_CASES.read_text(encoding="utf-8"))

    for case in cases:
        decision = port_compatibility_decision(case["input"], case["output"])
        assert _public_decision(decision) == case["expected"], case["name"]


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


def test_port_compatibility_normalizes_edam_uri_and_curie_ids() -> None:
    input_spec = {
        "type": "file",
        "format": "EDAM:format_2572",
        "data": "http://edamontology.org/data_0863",
        "operation": "EDAM:operation_0004",
    }
    output_spec = {
        "type": "file",
        "format": "http://edamontology.org/format_2572",
        "data": "data_0863",
        "operation": "operation_0004",
    }

    decision = port_compatibility_decision(input_spec, output_spec)

    assert decision["compatible"] is True
    assert decision["score"] == 12
    assert decision["matchedFields"] == ["type", "data", "format"]
    assert decision["advisoryFields"] == ["operation"]


def test_port_compatibility_rejects_common_name_aliases_as_semantics() -> None:
    input_spec = {"type": "file", "data": "sequence_reads", "format": "fastq"}
    output_spec = {
        "type": "file",
        "data": "http://edamontology.org/data_2044",
        "format": "EDAM:format_1930",
    }

    decision = port_compatibility_decision(input_spec, output_spec)

    assert decision["compatible"] is False
    assert decision["score"] is None
    assert decision["matchedFields"] == ["type"]
    assert decision["mismatchedField"] == "data"
    assert decision["genericFields"] == []


def test_generic_edam_roots_are_not_automatic_compatibility_evidence() -> None:
    input_spec = {"type": "file", "data": "data_2044", "format": "format_1930"}
    output_spec = {"type": "file", "data": "data_0006", "format": "format_1915"}

    decision = port_compatibility_decision(input_spec, output_spec)

    assert decision["compatible"] is False
    assert decision["score"] is None
    assert decision["matchedFields"] == ["type"]
    assert decision["genericFields"] == ["data", "format"]
    assert "data:generic-root-unsupported" in decision["hardChecks"]
    assert "format:generic-root-unsupported" in decision["hardChecks"]
    assert generic_compatibility_fields(input_spec, output_spec) == ["data", "format"]


def test_operation_is_advisory_and_resource_conflict_is_hard_blocker() -> None:
    assert port_compatibility_score({"operation": "trim"}, {"operation": "qc"}) == 0
    assert matched_advisory_compatibility_fields({"operation": "trim"}, {"operation": "trim"}) == []
    assert matched_advisory_compatibility_fields(
        {"operation": "EDAM:operation_0335"},
        {"operation": "operation_0335"},
    ) == ["operation"]
    assert port_compatibility_score({"resource": "db_a"}, {"resource": "db_b"}) is None
    assert mismatched_compatibility_field({"resource": "db_a"}, {"resource": "db_b"}) == "resource"


def test_port_compatibility_score_keeps_one_sided_evidence_manual() -> None:
    assert port_compatibility_score({"type": "file", "format": "format_2572"}, {"type": "file"}) == 5
    assert port_compatibility_score({"format": "format_2572"}, {}) == 1
    assert port_compatibility_score({}, {}) == 0


def test_port_spec_from_rule_item_uses_canonical_fields_only() -> None:
    assert port_spec_from_rule_item(
        {
            "name": "reads",
            "type": "file",
            "edamFormat": "format_2572",
            "edamData": "data_2044",
        }
    ) == {"type": "file"}


def _public_decision(decision: dict) -> dict:
    return {
        "compatible": decision["compatible"],
        "score": decision["score"],
        "matchedFields": decision["matchedFields"],
        "genericFields": decision["genericFields"],
        "advisoryFields": decision["advisoryFields"],
        "mismatchedField": decision["mismatchedField"],
        "hardChecks": decision["hardChecks"],
        "advisoryChecks": decision["advisoryChecks"],
    }
