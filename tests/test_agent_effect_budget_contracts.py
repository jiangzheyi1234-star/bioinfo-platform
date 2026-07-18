from __future__ import annotations

import copy
import re
from typing import Any

import pytest
from pydantic import ValidationError

from core.contracts.agent_contract_hash import (
    agent_contract_canonical_json,
    agent_contract_hash,
)
from core.contracts.agent_effect_budget import (
    AgentSessionEffectBudgetGrantRequest,
    AgentSessionEffectBudgetRead,
    AgentSessionEffectBudgetReceipt,
    agent_effect_budget_command_hash,
    agent_effect_budget_hash,
    agent_effect_budget_receipt_hash,
)


def _grant_payload() -> dict[str, Any]:
    return {
        "expectedStateVersion": 1,
        "maxRunSubmissions": 1,
        "confirmation": "enable-one-run",
        "requestId": "req_effect_budget_1",
        "idempotencyKey": "idem_effect_budget_1",
    }


def _receipt_payload() -> dict[str, Any]:
    request = AgentSessionEffectBudgetGrantRequest.model_validate(_grant_payload())
    payload: dict[str, Any] = {
        "contractVersion": "agent-session-effect-budget.v1",
        "sessionId": "ags_effect_budget_1",
        "maxRunSubmissions": 1,
        "actor": "runner-user",
        "requestId": request.requestId,
        "idempotencyKey": request.idempotencyKey,
        "commandHash": agent_effect_budget_command_hash(
            "ags_effect_budget_1",
            "runner-user",
            request,
        ),
        "createdAt": "2026-07-18T12:00:00Z",
    }
    payload["receiptHash"] = agent_effect_budget_receipt_hash(payload)
    return payload


def test_effect_budget_contracts_have_exact_runtime_payloads_and_hashes() -> None:
    request = AgentSessionEffectBudgetGrantRequest.model_validate(_grant_payload())
    receipt = AgentSessionEffectBudgetReceipt.model_validate(_receipt_payload())

    assert request.runtime_payload() == _grant_payload()
    assert receipt.runtime_payload() == _receipt_payload()
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.commandHash)
    assert re.fullmatch(r"[0-9a-f]{64}", receipt.receiptHash)
    assert re.fullmatch(r"[0-9a-f]{64}", agent_effect_budget_hash(receipt))

    absent = AgentSessionEffectBudgetRead.model_validate(
        {
            "contractVersion": "agent-session-effect-budget-read.v1",
            "sessionId": receipt.sessionId,
            "state": "absent",
        }
    )
    present = AgentSessionEffectBudgetRead.model_validate(
        {
            "contractVersion": "agent-session-effect-budget-read.v1",
            "sessionId": receipt.sessionId,
            "state": "present",
            "budget": receipt.runtime_payload(),
        }
    )
    assert absent.runtime_payload() == {
        "contractVersion": "agent-session-effect-budget-read.v1",
        "sessionId": receipt.sessionId,
        "state": "absent",
    }
    assert present.runtime_payload()["budget"] == receipt.runtime_payload()


@pytest.mark.parametrize(
    "field",
    [
        "actor",
        "serverId",
        "reason",
        "runSpec",
        "runId",
        "graph",
        "upload",
        "execution",
        "toolParameters",
        "file",
    ],
)
def test_effect_budget_grant_rejects_every_non_contract_field(field: str) -> None:
    payload = _grant_payload()
    payload[field] = {"unexpected": True}

    with pytest.raises(ValidationError) as exc_info:
        AgentSessionEffectBudgetGrantRequest.model_validate(payload)

    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == (field,)
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expectedStateVersion", "1"),
        ("expectedStateVersion", True),
        ("expectedStateVersion", 2),
        ("maxRunSubmissions", "1"),
        ("maxRunSubmissions", True),
        ("maxRunSubmissions", 0),
        ("confirmation", "enable-two-runs"),
    ],
)
def test_effect_budget_grant_rejects_coercion_and_nonfixed_values(
    field: str,
    value: object,
) -> None:
    payload = _grant_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        AgentSessionEffectBudgetGrantRequest.model_validate(payload)


def test_effect_budget_contract_rejects_secret_like_values_and_unsafe_integers() -> None:
    secret = _grant_payload()
    secret["requestId"] = "sk-abcdefghijklmnopqrstuvwxyz"
    with pytest.raises(ValidationError, match="AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN"):
        AgentSessionEffectBudgetGrantRequest.model_validate(secret)

    with pytest.raises(ValueError, match="AGENT_SESSION_SECRET_LIKE_VALUE_FORBIDDEN"):
        agent_effect_budget_command_hash(
            "ags_effect_budget_1",
            "sk-abcdefghijklmnopqrstuvwxyz",
            _grant_payload(),
        )

    with pytest.raises(ValueError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        agent_contract_hash(
            "agent-contract-test.v1",
            {"unsafe": 9_007_199_254_740_993},
        )


def test_agent_contract_hash_is_domain_separated_and_preserves_all_json_values() -> None:
    exact = {
        "false": False,
        "emptyText": "",
        "emptyList": [],
        "emptyObject": {},
        "null": None,
    }
    assert agent_contract_canonical_json({"z": False, "a": None}) == '{"a":null,"z":false}'
    assert agent_contract_hash("agent-domain-a.v1", exact) != agent_contract_hash(
        "agent-domain-b.v1",
        exact,
    )
    assert agent_contract_hash("agent-domain-a.v1", {"value": False}) != agent_contract_hash(
        "agent-domain-a.v1",
        {},
    )
    assert agent_contract_hash("agent-domain-a.v1", {"value": ""}) != agent_contract_hash(
        "agent-domain-a.v1",
        {},
    )
    assert agent_contract_hash("agent-domain-a.v1", {"value": []}) != agent_contract_hash(
        "agent-domain-a.v1",
        {},
    )
    assert agent_contract_hash("agent-domain-a.v1", {"value": {}}) != agent_contract_hash(
        "agent-domain-a.v1",
        {},
    )
    assert agent_contract_hash("agent-domain-a.v1", {"value": None}) != agent_contract_hash(
        "agent-domain-a.v1",
        {},
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("sessionId", "ags_effect_budget_2"),
        ("actor", "other-runner-user"),
        ("requestId", "req_effect_budget_2"),
        ("idempotencyKey", "idem_effect_budget_2"),
        ("commandHash", "b" * 64),
        ("createdAt", "2026-07-18T12:00:01Z"),
    ],
)
def test_effect_budget_receipt_rejects_single_field_tampering(
    field: str,
    replacement: object,
) -> None:
    payload = copy.deepcopy(_receipt_payload())
    payload[field] = replacement

    with pytest.raises(ValidationError, match="AGENT_EFFECT_BUDGET_RECEIPT_HASH_MISMATCH"):
        AgentSessionEffectBudgetReceipt.model_validate(payload)


def test_effect_budget_receipt_and_read_reject_malformed_or_inconsistent_payloads() -> None:
    malformed_hash = _receipt_payload()
    malformed_hash["receiptHash"] = "sha256:" + "a" * 64
    with pytest.raises(ValidationError):
        AgentSessionEffectBudgetReceipt.model_validate(malformed_hash)

    receipt = _receipt_payload()
    with pytest.raises(ValidationError, match="ABSENT_HAS_BUDGET"):
        AgentSessionEffectBudgetRead.model_validate(
            {
                "contractVersion": "agent-session-effect-budget-read.v1",
                "sessionId": receipt["sessionId"],
                "state": "absent",
                "budget": receipt,
            }
        )
    with pytest.raises(ValidationError, match="PRESENT_REQUIRES_BUDGET"):
        AgentSessionEffectBudgetRead.model_validate(
            {
                "contractVersion": "agent-session-effect-budget-read.v1",
                "sessionId": receipt["sessionId"],
                "state": "present",
            }
        )
    with pytest.raises(ValidationError, match="SESSION_ID_MISMATCH"):
        AgentSessionEffectBudgetRead.model_validate(
            {
                "contractVersion": "agent-session-effect-budget-read.v1",
                "sessionId": "ags_effect_budget_other",
                "state": "present",
                "budget": receipt,
            }
        )
    with pytest.raises(ValidationError) as extra:
        AgentSessionEffectBudgetRead.model_validate(
            {
                "contractVersion": "agent-session-effect-budget-read.v1",
                "sessionId": receipt["sessionId"],
                "state": "absent",
                "error": None,
            }
        )
    assert extra.value.errors()[0]["type"] == "extra_forbidden"
