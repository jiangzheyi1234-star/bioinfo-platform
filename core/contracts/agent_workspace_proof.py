"""Immutable, path-safe workspace proof contract for Agent worker boundaries."""

from __future__ import annotations

import hmac
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from .agent_contract_hash import agent_contract_hash, exact_hash_payload
from .agent_session import AgentSessionModel


AGENT_WORKSPACE_PROOF_CONTRACT_VERSION = "agent-workspace-proof.v1"
AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN = "agent-workspace-manifest.v1"

_HEX_SHA256 = r"^[0-9a-f]{64}$"
_WORKSPACE_PROOF_ID = r"^awsp_[0-9a-f]{24}$"
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_MAX_MANIFEST_ENTRIES = 250_000
_MAX_RELATIVE_PATH_BYTES = 4095
_MAX_PATH_COMPONENT_BYTES = 255
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_PROOF_HASH_FIELDS = (
    "contractVersion",
    "runId",
    "authorizationId",
    "attemptId",
    "leaseGeneration",
    "sourceAttemptId",
    "processBoundary",
    "processOrdinal",
    "workflowRevisionId",
    "workflowRevisionContentHash",
    "workflowRevisionManifestHash",
    "runSpecHash",
    "inputSnapshotHash",
    "toolAssetsHash",
    "runtimeLockHash",
    "runtimeProofHash",
    "immutableManifest",
    "immutableManifestHash",
    "snakemakeManifest",
    "snakemakeManifestHash",
    "previousProofHash",
    "eventId",
    "createdAt",
)


class AgentWorkspaceManifestEntryV1(AgentSessionModel):
    """One regular file observed below the governed workspace root."""

    relativePath: str = Field(min_length=1, max_length=_MAX_RELATIVE_PATH_BYTES)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=_HEX_SHA256)

    @field_validator("relativePath")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _require_portable_relative_path(value)


class AgentWorkspaceProofV1(AgentSessionModel):
    """Content-addressed proof of files rechecked at one process boundary."""

    workspaceProofId: str = Field(pattern=_WORKSPACE_PROOF_ID)
    contractVersion: Literal["agent-workspace-proof.v1"]
    runId: str = Field(min_length=1, max_length=500)
    authorizationId: str = Field(min_length=1, max_length=500)
    attemptId: str = Field(min_length=1, max_length=500)
    leaseGeneration: int = Field(ge=1)
    sourceAttemptId: str = Field(default="", max_length=500)
    processBoundary: Literal["pre_dry_run", "pre_run", "terminal"]
    processOrdinal: int = Field(ge=1)
    workflowRevisionId: str = Field(min_length=1, max_length=500)
    workflowRevisionContentHash: str = Field(pattern=_HEX_SHA256)
    workflowRevisionManifestHash: str = Field(pattern=_HEX_SHA256)
    runSpecHash: str = Field(pattern=_HEX_SHA256)
    inputSnapshotHash: str = Field(pattern=_HEX_SHA256)
    toolAssetsHash: str = Field(pattern=_HEX_SHA256)
    runtimeLockHash: str = Field(pattern=_HEX_SHA256)
    runtimeProofHash: str = Field(pattern=_HEX_SHA256)
    immutableManifest: list[AgentWorkspaceManifestEntryV1] = Field(
        min_length=1,
        max_length=_MAX_MANIFEST_ENTRIES,
    )
    immutableManifestHash: str = Field(pattern=_HEX_SHA256)
    snakemakeManifest: list[AgentWorkspaceManifestEntryV1] = Field(
        default_factory=list,
        max_length=_MAX_MANIFEST_ENTRIES,
    )
    snakemakeManifestHash: str = Field(pattern=_HEX_SHA256)
    previousProofHash: str | None = Field(default=None, pattern=_HEX_SHA256)
    eventId: str = Field(min_length=1, max_length=500)
    createdAt: str = Field(min_length=1, max_length=100)
    proofHash: str = Field(pattern=_HEX_SHA256)

    @field_validator("sourceAttemptId", mode="before")
    @classmethod
    def normalize_source_attempt_id(cls, value: object) -> object:
        return "" if value is None else value

    @field_validator(
        "runId",
        "authorizationId",
        "attemptId",
        "workflowRevisionId",
        "eventId",
        "createdAt",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _require_text(value, "AGENT_WORKSPACE_PROOF_TEXT_INVALID")

    @field_validator("sourceAttemptId")
    @classmethod
    def validate_optional_text(cls, value: str) -> str:
        if value == "":
            return value
        return _require_text(value, "AGENT_WORKSPACE_PROOF_SOURCE_ATTEMPT_ID_INVALID")

    @field_validator("immutableManifest")
    @classmethod
    def validate_immutable_manifest(
        cls,
        value: list[AgentWorkspaceManifestEntryV1],
    ) -> list[AgentWorkspaceManifestEntryV1]:
        _require_canonical_manifest_order(
            value, code="AGENT_WORKSPACE_IMMUTABLE_MANIFEST"
        )
        return value

    @field_validator("snakemakeManifest")
    @classmethod
    def validate_snakemake_manifest(
        cls,
        value: list[AgentWorkspaceManifestEntryV1],
    ) -> list[AgentWorkspaceManifestEntryV1]:
        _require_canonical_manifest_order(
            value, code="AGENT_WORKSPACE_SNAKEMAKE_MANIFEST"
        )
        return value

    @model_validator(mode="after")
    def validate_content_addressed_proof(self) -> "AgentWorkspaceProofV1":
        immutable_hash = agent_workspace_manifest_hash(self.immutableManifest)
        if not hmac.compare_digest(immutable_hash, self.immutableManifestHash):
            raise ValueError("AGENT_WORKSPACE_IMMUTABLE_MANIFEST_HASH_MISMATCH")
        snakemake_hash = agent_workspace_manifest_hash(self.snakemakeManifest)
        if not hmac.compare_digest(snakemake_hash, self.snakemakeManifestHash):
            raise ValueError("AGENT_WORKSPACE_SNAKEMAKE_MANIFEST_HASH_MISMATCH")
        payload = self.runtime_payload()
        expected_hash = agent_workspace_proof_hash(payload)
        if not hmac.compare_digest(expected_hash, self.proofHash):
            raise ValueError("AGENT_WORKSPACE_PROOF_HASH_MISMATCH")
        expected_id = agent_workspace_proof_id(expected_hash)
        if not hmac.compare_digest(expected_id, self.workspaceProofId):
            raise ValueError("AGENT_WORKSPACE_PROOF_ID_MISMATCH")
        return self

    def runtime_payload(self) -> dict[str, JsonValue]:
        """Keep nullable chain state explicit and the source attempt canonical."""

        return self.model_dump(by_alias=True, exclude_none=False, mode="json")


def agent_workspace_manifest_hash(
    entries: Sequence[AgentWorkspaceManifestEntryV1 | Mapping[str, object]],
) -> str:
    """Hash an exact, canonically ordered relative-file manifest."""

    normalized = _normalize_manifest_entries(entries)
    return agent_contract_hash(
        AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN,
        {"entries": normalized},
    )


def agent_workspace_proof_hash(
    proof: AgentWorkspaceProofV1 | Mapping[str, object],
) -> str:
    """Hash all proof semantics except its derived digest and identifier."""

    payload = (
        proof.runtime_payload() if isinstance(proof, AgentWorkspaceProofV1) else proof
    )
    semantic_payload = exact_hash_payload(
        payload,
        _PROOF_HASH_FIELDS,
        code="AGENT_WORKSPACE_PROOF_HASH_FIELD_MISSING",
    )
    if semantic_payload["sourceAttemptId"] is None:
        semantic_payload["sourceAttemptId"] = ""
    return agent_contract_hash(
        AGENT_WORKSPACE_PROOF_CONTRACT_VERSION,
        semantic_payload,
    )


def agent_workspace_proof_id(proof_hash: str) -> str:
    """Derive the stable public identifier from one validated proof digest."""

    if not isinstance(proof_hash, str) or re.fullmatch(_HEX_SHA256, proof_hash) is None:
        raise ValueError("AGENT_WORKSPACE_PROOF_HASH_INVALID")
    return f"awsp_{proof_hash[:24]}"


def build_agent_workspace_proof_v1(
    payload: Mapping[str, object],
) -> AgentWorkspaceProofV1:
    """Build a proof while refusing stale caller-supplied derived values."""

    normalized = dict(payload)
    normalized.setdefault("contractVersion", AGENT_WORKSPACE_PROOF_CONTRACT_VERSION)
    if normalized.get("sourceAttemptId") is None:
        normalized["sourceAttemptId"] = ""
    normalized.setdefault("previousProofHash", None)

    immutable_entries = _normalize_manifest_entries(
        _require_manifest_sequence(normalized.get("immutableManifest"))
    )
    snakemake_entries = _normalize_manifest_entries(
        _require_manifest_sequence(normalized.get("snakemakeManifest", []))
    )
    normalized["immutableManifest"] = immutable_entries
    normalized["snakemakeManifest"] = snakemake_entries
    _bind_or_set_derived(
        normalized,
        "immutableManifestHash",
        agent_workspace_manifest_hash(immutable_entries),
        "AGENT_WORKSPACE_IMMUTABLE_MANIFEST_HASH_MISMATCH",
    )
    _bind_or_set_derived(
        normalized,
        "snakemakeManifestHash",
        agent_workspace_manifest_hash(snakemake_entries),
        "AGENT_WORKSPACE_SNAKEMAKE_MANIFEST_HASH_MISMATCH",
    )

    expected_hash = agent_workspace_proof_hash(normalized)
    _bind_or_set_derived(
        normalized,
        "proofHash",
        expected_hash,
        "AGENT_WORKSPACE_PROOF_HASH_MISMATCH",
    )
    _bind_or_set_derived(
        normalized,
        "workspaceProofId",
        agent_workspace_proof_id(expected_hash),
        "AGENT_WORKSPACE_PROOF_ID_MISMATCH",
    )
    return AgentWorkspaceProofV1.model_validate(normalized)


def _normalize_manifest_entries(
    entries: Sequence[AgentWorkspaceManifestEntryV1 | Mapping[str, object]],
) -> list[dict[str, JsonValue]]:
    if isinstance(entries, (str, bytes, bytearray)):
        raise ValueError("AGENT_WORKSPACE_MANIFEST_ENTRIES_INVALID")
    normalized = [
        entry
        if isinstance(entry, AgentWorkspaceManifestEntryV1)
        else AgentWorkspaceManifestEntryV1.model_validate(entry)
        for entry in entries
    ]
    if len(normalized) > _MAX_MANIFEST_ENTRIES:
        raise ValueError("AGENT_WORKSPACE_MANIFEST_ENTRIES_INVALID")
    _require_canonical_manifest_order(normalized, code="AGENT_WORKSPACE_MANIFEST")
    return [entry.runtime_payload() for entry in normalized]


def _require_manifest_sequence(value: object) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("AGENT_WORKSPACE_MANIFEST_ENTRIES_INVALID")
    return value  # type: ignore[return-value]


def _require_canonical_manifest_order(
    entries: Sequence[AgentWorkspaceManifestEntryV1],
    *,
    code: str,
) -> None:
    paths = [entry.relativePath for entry in entries]
    if len(paths) != len(set(paths)):
        raise ValueError(f"{code}_DUPLICATE_PATH")
    windows_aliases = [_windows_path_alias_key(path) for path in paths]
    if len(windows_aliases) != len(set(windows_aliases)):
        raise ValueError(f"{code}_WINDOWS_ALIAS_PATH")
    # Paths are ASCII-only, so Python's exact string order is the portable
    # bytewise canonical order. Alias rejection is a separate invariant and
    # does not make canonical ordering platform-dependent.
    if paths != sorted(paths):
        raise ValueError(f"{code}_ORDER_INVALID")


def _require_portable_relative_path(value: str) -> str:
    if (
        value != value.strip(" ")
        or value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or "\x00" in value
        or _WINDOWS_DRIVE_PREFIX.match(value) is not None
    ):
        raise ValueError("AGENT_WORKSPACE_MANIFEST_RELATIVE_PATH_INVALID")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ValueError("AGENT_WORKSPACE_MANIFEST_RELATIVE_PATH_INVALID") from None
    components = value.split("/")
    if (
        not encoded
        or len(encoded) > _MAX_RELATIVE_PATH_BYTES
        or any(
            not component
            or component in {".", ".."}
            or component != component.strip(" ")
            or component.endswith((".", " "))
            or ":" in component
            or _is_windows_reserved_device_component(component)
            or len(component.encode("ascii")) > _MAX_PATH_COMPONENT_BYTES
            or any(
                ord(character) < 0x20 or ord(character) > 0x7E
                for character in component
            )
            for component in components
        )
    ):
        raise ValueError("AGENT_WORKSPACE_MANIFEST_RELATIVE_PATH_INVALID")
    return value


def _is_windows_reserved_device_component(component: str) -> bool:
    """Reject DOS device aliases even when a component has an extension."""

    device_prefix = component.split(".", 1)[0].casefold()
    return device_prefix in _WINDOWS_RESERVED_DEVICE_NAMES


def _windows_path_alias_key(value: str) -> tuple[str, ...]:
    """Return the case-insensitive component identity used by Windows paths."""

    return tuple(component.casefold() for component in value.split("/"))


def _require_text(value: str, code: str) -> str:
    if value != value.strip() or "\x00" in value:
        raise ValueError(code)
    return value


def _bind_or_set_derived(
    payload: dict[str, object],
    field: str,
    expected: str,
    code: str,
) -> None:
    observed = payload.get(field)
    if observed is not None and observed != expected:
        raise ValueError(code)
    payload[field] = expected


__all__ = [
    "AGENT_WORKSPACE_MANIFEST_HASH_DOMAIN",
    "AGENT_WORKSPACE_PROOF_CONTRACT_VERSION",
    "AgentWorkspaceManifestEntryV1",
    "AgentWorkspaceProofV1",
    "agent_workspace_manifest_hash",
    "agent_workspace_proof_hash",
    "agent_workspace_proof_id",
    "build_agent_workspace_proof_v1",
]
