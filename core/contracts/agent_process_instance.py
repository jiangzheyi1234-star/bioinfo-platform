"""Immutable process launch intents for Agent execution."""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .agent_contract_hash import agent_contract_hash, exact_hash_payload
from .agent_session import AgentSessionModel


AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION = "agent-process-launch-intent.v1"
AGENT_LOGICAL_ACTIVITY_ID_DOMAIN = "agent-logical-activity.v1"

AgentProcessKind = Literal["dry_run", "run"]

_HEX_SHA256 = r"^[0-9a-f]{64}$"
_WORKSPACE_PROOF_ID = r"^awsp_[0-9a-f]{24}$"
_LOGICAL_ACTIVITY_ID = r"^agact_[0-9a-f]{24}$"
_PROCESS_INSTANCE_ID = r"^agpi_[0-9a-f]{24}$"

_PROCESS_LAUNCH_INTENT_HASH_FIELDS = (
    "contractVersion",
    "runId",
    "authorizationId",
    "attemptId",
    "leaseGeneration",
    "logicalActivityId",
    "processOrdinal",
    "processKind",
    "workspaceProofId",
    "toolAssetsHash",
    "launchSpecHash",
    "gateTokenHash",
    "spawnIntentEventId",
    "spawnIntentEventHash",
    "preparedAt",
)


class AgentProcessLaunchIntentV1(AgentSessionModel):
    """Immutable intent for exactly one governed operating-system process."""

    processInstanceId: str = Field(pattern=_PROCESS_INSTANCE_ID)
    contractVersion: Literal["agent-process-launch-intent.v1"]
    runId: str = Field(min_length=1, max_length=500)
    authorizationId: str = Field(min_length=1, max_length=500)
    attemptId: str = Field(min_length=1, max_length=500)
    leaseGeneration: int = Field(ge=1)
    logicalActivityId: str = Field(pattern=_LOGICAL_ACTIVITY_ID)
    processOrdinal: int = Field(ge=1)
    processKind: AgentProcessKind
    workspaceProofId: str = Field(pattern=_WORKSPACE_PROOF_ID)
    toolAssetsHash: str = Field(pattern=_HEX_SHA256)
    launchSpecHash: str = Field(pattern=_HEX_SHA256)
    gateTokenHash: str = Field(pattern=_HEX_SHA256)
    spawnIntentEventId: str = Field(min_length=1, max_length=500)
    spawnIntentEventHash: str = Field(pattern=_HEX_SHA256)
    preparedAt: str = Field(min_length=1, max_length=100)
    launchIntentHash: str = Field(pattern=_HEX_SHA256)

    @field_validator(
        "runId",
        "authorizationId",
        "attemptId",
        "spawnIntentEventId",
        "preparedAt",
        mode="before",
    )
    @classmethod
    def validate_source_text(cls, value: object) -> str:
        return _require_text(value, "AGENT_PROCESS_LAUNCH_INTENT_TEXT_INVALID")

    @model_validator(mode="after")
    def validate_content_addressed_intent(self) -> "AgentProcessLaunchIntentV1":
        expected_ordinal = agent_process_ordinal(self.processKind)
        if self.processOrdinal != expected_ordinal:
            raise ValueError("AGENT_PROCESS_LAUNCH_INTENT_ORDINAL_MISMATCH")

        expected_activity_id = agent_logical_activity_id(
            self.runId,
            self.processKind,
        )
        if not hmac.compare_digest(expected_activity_id, self.logicalActivityId):
            raise ValueError("AGENT_PROCESS_LOGICAL_ACTIVITY_ID_MISMATCH")

        expected_hash = agent_process_launch_intent_hash(self.runtime_payload())
        if not hmac.compare_digest(expected_hash, self.launchIntentHash):
            raise ValueError("AGENT_PROCESS_LAUNCH_INTENT_HASH_MISMATCH")
        expected_id = agent_process_instance_id(expected_hash)
        if not hmac.compare_digest(expected_id, self.processInstanceId):
            raise ValueError("AGENT_PROCESS_INSTANCE_ID_MISMATCH")
        return self

    def runtime_payload(self) -> dict[str, JsonValue]:
        """Return the complete immutable intent as JSON-safe public data."""

        return self.model_dump(by_alias=True, exclude_none=False, mode="json")


def agent_process_ordinal(process_kind: AgentProcessKind | str) -> int:
    """Return the one canonical process position for the generated run."""

    normalized = _require_process_kind(process_kind)
    return 1 if normalized == "dry_run" else 2


def agent_logical_activity_id(
    run_id: str,
    process_kind: AgentProcessKind | str,
) -> str:
    """Derive a retry-stable logical activity from run identity and kind."""

    digest = agent_contract_hash(
        AGENT_LOGICAL_ACTIVITY_ID_DOMAIN,
        {
            "runId": _require_text(run_id, "AGENT_PROCESS_RUN_ID_INVALID"),
            "processKind": _require_process_kind(process_kind),
        },
    )
    return f"agact_{digest[:24]}"


def agent_process_launch_intent_hash(
    intent: AgentProcessLaunchIntentV1 | Mapping[str, object],
) -> str:
    """Hash every launch semantic except its digest and public instance ID."""

    payload = (
        intent.runtime_payload()
        if isinstance(intent, AgentProcessLaunchIntentV1)
        else intent
    )
    return agent_contract_hash(
        AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION,
        exact_hash_payload(
            payload,
            _PROCESS_LAUNCH_INTENT_HASH_FIELDS,
            code="AGENT_PROCESS_LAUNCH_INTENT_HASH_FIELD_MISSING",
        ),
    )


def agent_process_instance_id(launch_intent_hash: str) -> str:
    """Derive a public process instance identifier from its intent digest."""

    _require_sha256(
        launch_intent_hash,
        "AGENT_PROCESS_LAUNCH_INTENT_HASH_INVALID",
    )
    return f"agpi_{launch_intent_hash[:24]}"


def build_agent_process_launch_intent_v1(
    payload: Mapping[str, object],
) -> AgentProcessLaunchIntentV1:
    """Build one launch intent and reject stale caller-authored derivations."""

    normalized = _copy_mapping(
        payload,
        "AGENT_PROCESS_LAUNCH_INTENT_PAYLOAD_INVALID",
    )
    normalized.setdefault(
        "contractVersion",
        AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION,
    )
    expected_activity_id = agent_logical_activity_id(
        _require_text(normalized.get("runId"), "AGENT_PROCESS_RUN_ID_INVALID"),
        _require_process_kind(normalized.get("processKind")),
    )
    _bind_or_set_derived(
        normalized,
        "logicalActivityId",
        expected_activity_id,
        "AGENT_PROCESS_LOGICAL_ACTIVITY_ID_MISMATCH",
    )

    expected_hash = agent_process_launch_intent_hash(normalized)
    _bind_or_set_derived(
        normalized,
        "launchIntentHash",
        expected_hash,
        "AGENT_PROCESS_LAUNCH_INTENT_HASH_MISMATCH",
    )
    _bind_or_set_derived(
        normalized,
        "processInstanceId",
        agent_process_instance_id(expected_hash),
        "AGENT_PROCESS_INSTANCE_ID_MISMATCH",
    )
    return AgentProcessLaunchIntentV1.model_validate(normalized)


def _require_text(value: object, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ValueError(code)
    return value


def _require_process_kind(value: object) -> AgentProcessKind:
    if value == "dry_run":
        return "dry_run"
    if value == "run":
        return "run"
    raise ValueError("AGENT_PROCESS_KIND_INVALID")


def _require_sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or re.fullmatch(_HEX_SHA256, value) is None:
        raise ValueError(code)
    return value


def _copy_mapping(payload: object, code: str) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError(code)
    return dict(payload)


def _bind_or_set_derived(
    payload: dict[str, object],
    field: str,
    expected: str,
    code: str,
) -> None:
    if field in payload and payload[field] != expected:
        raise ValueError(code)
    payload[field] = expected


__all__ = [
    "AGENT_LOGICAL_ACTIVITY_ID_DOMAIN",
    "AGENT_PROCESS_LAUNCH_INTENT_CONTRACT_VERSION",
    "AgentProcessKind",
    "AgentProcessLaunchIntentV1",
    "agent_logical_activity_id",
    "agent_process_instance_id",
    "agent_process_launch_intent_hash",
    "agent_process_ordinal",
    "build_agent_process_launch_intent_v1",
]
