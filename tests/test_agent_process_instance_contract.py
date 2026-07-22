from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from core.contracts.agent_process_instance import (
    AGENT_LOGICAL_ACTIVITY_ID_DOMAIN,
    AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION,
    AgentProcessLaunchIntentV1,
    agent_logical_activity_id,
    agent_process_instance_id,
    agent_process_launch_intent_hash,
    agent_process_ordinal,
    build_agent_process_launch_intent_v1,
)


def _canonical_hash(domain: str, payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(
        domain.encode("utf-8") + b"\x00" + canonical.encode("utf-8")
    ).hexdigest()


def _intent_semantics() -> dict[str, object]:
    return {
        "contractVersion": AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION,
        "runId": "run-agent-1",
        "authorizationId": "authorization-agent-1",
        "attemptId": "attempt-agent-1",
        "leaseGeneration": 3,
        "processOrdinal": 1,
        "processKind": "dry_run",
        "workspaceProofId": "awsp_" + "a" * 24,
        "toolAssetsHash": "b" * 64,
        "launchSpecHash": "c" * 64,
        "gateTokenHash": "d" * 64,
        "spawnIntentEventId": "event-spawn-intent-1",
        "spawnIntentEventHash": "e" * 64,
        "preparedAt": "2026-07-22T10:11:13Z",
    }


def test_process_launch_intent_has_exact_activity_hash_id_and_full_json() -> None:
    source = MappingProxyType(_intent_semantics())
    first = build_agent_process_launch_intent_v1(source)
    second = build_agent_process_launch_intent_v1(source)
    runtime = first.runtime_payload()

    expected_activity_hash = _canonical_hash(
        AGENT_LOGICAL_ACTIVITY_ID_DOMAIN,
        {"runId": "run-agent-1", "processKind": "dry_run"},
    )
    expected_activity_id = f"agact_{expected_activity_hash[:24]}"
    expected_intent_semantics = {
        "contractVersion": AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION,
        "runId": "run-agent-1",
        "authorizationId": "authorization-agent-1",
        "attemptId": "attempt-agent-1",
        "leaseGeneration": 3,
        "logicalActivityId": expected_activity_id,
        "processOrdinal": 1,
        "processKind": "dry_run",
        "workspaceProofId": "awsp_" + "a" * 24,
        "toolAssetsHash": "b" * 64,
        "launchSpecHash": "c" * 64,
        "gateTokenHash": "d" * 64,
        "spawnIntentEventId": "event-spawn-intent-1",
        "spawnIntentEventHash": "e" * 64,
        "preparedAt": "2026-07-22T10:11:13Z",
    }
    expected_hash = _canonical_hash(
        AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION,
        expected_intent_semantics,
    )

    assert first == second
    assert first.logicalActivityId == expected_activity_id
    assert agent_logical_activity_id("run-agent-1", "dry_run") == expected_activity_id
    assert first.launchIntentHash == expected_hash
    assert first.processInstanceId == f"agpi_{expected_hash[:24]}"
    assert agent_process_launch_intent_hash(first) == expected_hash
    assert agent_process_launch_intent_hash(expected_intent_semantics) == expected_hash
    assert agent_process_instance_id(expected_hash) == first.processInstanceId
    assert runtime == {
        "processInstanceId": f"agpi_{expected_hash[:24]}",
        **expected_intent_semantics,
        "launchIntentHash": expected_hash,
    }
    assert json.loads(json.dumps(runtime)) == runtime


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("contractVersion", "agent-process-launch-intent.v2"),
        ("runId", "run-agent-2"),
        ("authorizationId", "authorization-agent-2"),
        ("attemptId", "attempt-agent-2"),
        ("leaseGeneration", 4),
        ("logicalActivityId", "agact_" + "f" * 24),
        ("processOrdinal", 2),
        ("processKind", "run"),
        ("workspaceProofId", "awsp_" + "f" * 24),
        ("toolAssetsHash", "e" * 64),
        ("launchSpecHash", "f" * 64),
        ("gateTokenHash", "0" * 64),
        ("spawnIntentEventId", "event-spawn-intent-2"),
        ("spawnIntentEventHash", "f" * 64),
        ("preparedAt", "2026-07-22T10:11:14Z"),
    ],
)
def test_launch_intent_hash_is_sensitive_to_every_semantic_field(
    field: str,
    replacement: object,
) -> None:
    original = build_agent_process_launch_intent_v1(
        _intent_semantics()
    ).runtime_payload()
    original.pop("processInstanceId")
    original.pop("launchIntentHash")
    changed = dict(original)
    changed[field] = replacement

    assert agent_process_launch_intent_hash(changed) != (
        agent_process_launch_intent_hash(original)
    )


def test_builder_and_model_reject_stale_derived_values() -> None:
    runtime = build_agent_process_launch_intent_v1(
        _intent_semantics()
    ).runtime_payload()

    stale_activity = dict(runtime)
    stale_activity["runId"] = "run-agent-2"
    with pytest.raises(ValueError, match="LOGICAL_ACTIVITY_ID_MISMATCH"):
        build_agent_process_launch_intent_v1(stale_activity)
    with pytest.raises(ValidationError, match="LOGICAL_ACTIVITY_ID_MISMATCH"):
        AgentProcessLaunchIntentV1.model_validate(stale_activity)

    stale_hash = dict(runtime)
    stale_hash["spawnIntentEventHash"] = "f" * 64
    with pytest.raises(ValueError, match="LAUNCH_INTENT_HASH_MISMATCH"):
        build_agent_process_launch_intent_v1(stale_hash)
    with pytest.raises(ValidationError, match="LAUNCH_INTENT_HASH_MISMATCH"):
        AgentProcessLaunchIntentV1.model_validate(stale_hash)

    stale_id = _intent_semantics()
    stale_id["processInstanceId"] = "agpi_" + "f" * 24
    with pytest.raises(ValueError, match="PROCESS_INSTANCE_ID_MISMATCH"):
        build_agent_process_launch_intent_v1(stale_id)


def test_builder_requires_a_real_mapping() -> None:
    with pytest.raises(ValueError, match="PROCESS_LAUNCH_INTENT_PAYLOAD_INVALID"):
        build_agent_process_launch_intent_v1([tuple(_intent_semantics().items())])


def test_hash_requires_every_exact_semantic_field() -> None:
    intent = build_agent_process_launch_intent_v1(
        _intent_semantics()
    ).runtime_payload()
    intent.pop("preparedAt")
    with pytest.raises(ValueError, match="HASH_FIELD_MISSING: preparedAt"):
        agent_process_launch_intent_hash(intent)

    missing_event_hash = build_agent_process_launch_intent_v1(
        _intent_semantics()
    ).runtime_payload()
    missing_event_hash.pop("spawnIntentEventHash")
    with pytest.raises(ValueError, match="HASH_FIELD_MISSING: spawnIntentEventHash"):
        agent_process_launch_intent_hash(missing_event_hash)

    missing_source_event_hash = _intent_semantics()
    missing_source_event_hash.pop("spawnIntentEventHash")
    with pytest.raises(ValueError, match="HASH_FIELD_MISSING: spawnIntentEventHash"):
        build_agent_process_launch_intent_v1(missing_source_event_hash)


def test_contract_rejects_extra_fields() -> None:
    intent = _intent_semantics()
    intent["command"] = ["snakemake"]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        build_agent_process_launch_intent_v1(intent)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("contractVersion", "agent-process-launch-intent.v2"),
        ("workspaceProofId", "awsp_" + "A" * 24),
        ("workspaceProofId", "awsp_" + "a" * 23),
        ("toolAssetsHash", "sha256:" + "b" * 64),
        ("launchSpecHash", "C" * 64),
        ("gateTokenHash", "d" * 63),
        ("spawnIntentEventHash", "E" * 64),
        ("spawnIntentEventHash", "sha256:" + "e" * 64),
        ("spawnIntentEventHash", "e" * 63),
        ("leaseGeneration", 0),
        ("leaseGeneration", "3"),
        ("processKind", "execute"),
        ("processOrdinal", 0),
        ("processOrdinal", True),
    ],
)
def test_launch_intent_rejects_invalid_formats_and_coercions(
    field: str,
    replacement: object,
) -> None:
    payload = _intent_semantics()
    payload[field] = replacement
    with pytest.raises((ValidationError, ValueError)):
        build_agent_process_launch_intent_v1(payload)


@pytest.mark.parametrize(
    ("process_kind", "process_ordinal"),
    [("dry_run", 2), ("run", 1)],
)
def test_process_kind_has_one_forced_ordinal(
    process_kind: str,
    process_ordinal: int,
) -> None:
    payload = _intent_semantics()
    payload["processKind"] = process_kind
    payload["processOrdinal"] = process_ordinal

    with pytest.raises(ValidationError, match="ORDINAL_MISMATCH"):
        build_agent_process_launch_intent_v1(payload)

    assert agent_process_ordinal("dry_run") == 1
    assert agent_process_ordinal("run") == 2


@pytest.mark.parametrize(
    "field",
    ["runId", "authorizationId", "attemptId", "spawnIntentEventId", "preparedAt"],
)
@pytest.mark.parametrize("invalid", ["", " \t", " leading", "trailing ", "nul\x00text"])
def test_launch_intent_rejects_blank_trimmed_or_nul_source_text(
    field: str,
    invalid: str,
) -> None:
    payload = _intent_semantics()
    payload[field] = invalid
    with pytest.raises(
        (ValidationError, ValueError),
        match="(TEXT_INVALID|RUN_ID_INVALID)",
    ):
        build_agent_process_launch_intent_v1(payload)


@pytest.mark.parametrize(
    "value",
    ["", "A" * 64, "sha256:" + "a" * 64, "a" * 63, "g" * 64],
)
def test_process_instance_id_rejects_noncanonical_hashes(value: str) -> None:
    with pytest.raises(ValueError, match="PROCESS_LAUNCH_INTENT_HASH_INVALID"):
        agent_process_instance_id(value)


def test_logical_activity_is_retry_stable_kind_specific_and_strict() -> None:
    dry_run = agent_logical_activity_id("run-agent-1", "dry_run")
    run = agent_logical_activity_id("run-agent-1", "run")

    assert re.fullmatch(r"agact_[0-9a-f]{24}", dry_run)
    assert dry_run == agent_logical_activity_id("run-agent-1", "dry_run")
    assert dry_run != run
    assert dry_run != agent_logical_activity_id("run-agent-2", "dry_run")
    with pytest.raises(ValueError, match="RUN_ID_INVALID"):
        agent_logical_activity_id(" run-agent-1", "dry_run")
    with pytest.raises(ValueError, match="RUN_ID_INVALID"):
        agent_logical_activity_id("run-agent-1\x00tail", "dry_run")
    with pytest.raises(ValueError, match="PROCESS_KIND_INVALID"):
        agent_logical_activity_id("run-agent-1", "dry-run")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("processInstanceId", "agpi_" + "A" * 24),
        ("logicalActivityId", "agact_" + "A" * 24),
        ("launchIntentHash", "A" * 64),
    ],
)
def test_model_rejects_malformed_caller_supplied_derived_fields(
    field: str,
    replacement: str,
) -> None:
    intent = build_agent_process_launch_intent_v1(
        _intent_semantics()
    ).runtime_payload()
    intent[field] = replacement
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        AgentProcessLaunchIntentV1.model_validate(intent)
