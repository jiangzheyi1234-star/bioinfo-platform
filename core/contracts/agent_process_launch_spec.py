"""Canonical, keyed operating-system process launch specs.

The public command intentionally contains no authorization or workspace proof
fields.  Those identities are attached from trusted server state immediately
before the final launch-spec hash is derived.  Command objects are memory-only:
the complete child environment can be sensitive, so persistence and events must
retain the derived digest rather than the raw command payload.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath, PureWindowsPath
from subprocess import list2cmdline
from typing import Literal

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .agent_process_instance import AgentProcessKind, agent_process_ordinal
from .agent_session import AgentSessionModel
from .workflow_design import assert_json_interoperable_numbers


AGENT_PROCESS_LAUNCH_COMMAND_CONTRACT_VERSION = "agent-process-launch-command.v1"
AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION = "agent-process-launch-spec.v1"
AGENT_PROCESS_GATE_PROTOCOL_VERSION = "agent-process-gate.v1"

AgentProcessPlatform = Literal["linux", "windows"]

_HEX_SHA256 = r"^[0-9a-f]{64}$"
_WORKSPACE_PROOF_ID = r"^awsp_[0-9a-f]{24}$"
_MAX_ARGUMENTS = 4_096
_MAX_ARGUMENT_LENGTH = 32_767
_MAX_ENVIRONMENT_ENTRIES = 8_192
_MAX_ENVIRONMENT_NAME_LENGTH = 32_767
_MAX_ENVIRONMENT_VALUE_LENGTH = 1_048_576
_MAX_PATH_LENGTH = 32_767
_MAX_LAUNCH_PAYLOAD_UTF8_BYTES = 1_048_576
_MAX_WINDOWS_COMMAND_LINE_CHARACTERS = 32_767
_MAX_WINDOWS_ENVIRONMENT_BLOCK_CHARACTERS = 32_767
_LAUNCH_SPEC_HASH_KEY_BYTES = 32
_RESERVED_ENVIRONMENT_PREFIXES = (
    "h2ometa_agent_gate_",
    "h2ometa_agent_launch_",
)
_LAUNCH_SPEC_HASH_FIELDS = (
    "contractVersion",
    "command",
    "serverBindings",
)


class _FrozenAgentModel(AgentSessionModel):
    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)


class AgentProcessEnvironmentVariableV1(_FrozenAgentModel):
    """One exact child-environment entry; empty values remain meaningful."""

    name: str = Field(min_length=1, max_length=_MAX_ENVIRONMENT_NAME_LENGTH)
    value: str = Field(max_length=_MAX_ENVIRONMENT_VALUE_LENGTH, repr=False)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: object) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\x00" in value
            or "=" in value
            or any(
                value.casefold().startswith(prefix)
                for prefix in _RESERVED_ENVIRONMENT_PREFIXES
            )
        ):
            raise ValueError("AGENT_PROCESS_LAUNCH_ENVIRONMENT_NAME_INVALID")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> str:
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("AGENT_PROCESS_LAUNCH_ENVIRONMENT_VALUE_INVALID")
        return value


class AgentProcessStdioPolicyV1(_FrozenAgentModel):
    """The sole supported, deterministic target stdio contract."""

    stdinMode: Literal["null"]
    stdoutMode: Literal["pipe"]
    stderrMode: Literal["pipe"]
    textEncoding: Literal["utf-8"]
    textErrors: Literal["strict"]


class AgentProcessSessionPolicyV1(_FrozenAgentModel):
    """Platform-specific containment and one-time gate-release semantics."""

    platform: AgentProcessPlatform
    launchMechanism: Literal["posix_gate_helper", "windows_suspended_process"]
    containment: Literal[
        "posix_new_session_process_group",
        "windows_job_object_kill_on_close",
    ]
    gateRelease: Literal["write_inherited_pipe_frame", "resume_primary_thread"]
    closeFds: Literal[True]

    @model_validator(mode="after")
    def validate_platform_policy(self) -> "AgentProcessSessionPolicyV1":
        expected = (
            (
                "posix_gate_helper",
                "posix_new_session_process_group",
                "write_inherited_pipe_frame",
            )
            if self.platform == "linux"
            else (
                "windows_suspended_process",
                "windows_job_object_kill_on_close",
                "resume_primary_thread",
            )
        )
        observed = (self.launchMechanism, self.containment, self.gateRelease)
        if observed != expected:
            raise ValueError("AGENT_PROCESS_LAUNCH_SESSION_POLICY_MISMATCH")
        return self


class AgentProcessHelperIdentityV1(_FrozenAgentModel):
    """Content identity of the trusted gate/suspended-process helper."""

    helperId: str = Field(min_length=1, max_length=200)
    helperVersion: str = Field(min_length=1, max_length=200)
    gateProtocolVersion: Literal["agent-process-gate.v1"]
    resolvedPath: str = Field(
        min_length=1,
        max_length=_MAX_PATH_LENGTH,
        repr=False,
    )
    sha256: str = Field(pattern=_HEX_SHA256)

    @field_validator("helperId", "helperVersion", "resolvedPath")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _require_trimmed_text(value, "AGENT_PROCESS_LAUNCH_HELPER_TEXT_INVALID")


class AgentProcessRuntimeExecutableIdentityV1(_FrozenAgentModel):
    """Exact executable selected from the validated workflow runtime."""

    resolvedPath: str = Field(
        min_length=1,
        max_length=_MAX_PATH_LENGTH,
        repr=False,
    )
    sha256: str = Field(pattern=_HEX_SHA256)

    @field_validator("resolvedPath")
    @classmethod
    def validate_path_text(cls, value: str) -> str:
        return _require_trimmed_text(
            value,
            "AGENT_PROCESS_LAUNCH_RUNTIME_EXECUTABLE_PATH_INVALID",
        )


class AgentProcessLaunchCommandV1(_FrozenAgentModel):
    """Public, immutable command semantics with no server authority fields."""

    contractVersion: Literal["agent-process-launch-command.v1"]
    processKind: AgentProcessKind
    processOrdinal: int = Field(ge=1)
    argv: tuple[str, ...] = Field(
        min_length=1,
        max_length=_MAX_ARGUMENTS,
        repr=False,
    )
    resolvedCwd: str = Field(
        min_length=1,
        max_length=_MAX_PATH_LENGTH,
        repr=False,
    )
    childEnv: tuple[AgentProcessEnvironmentVariableV1, ...] = Field(
        min_length=1,
        max_length=_MAX_ENVIRONMENT_ENTRIES,
        repr=False,
    )
    stdio: AgentProcessStdioPolicyV1
    session: AgentProcessSessionPolicyV1
    helper: AgentProcessHelperIdentityV1
    runtimeExecutable: AgentProcessRuntimeExecutableIdentityV1

    @field_validator("argv", "childEnv", mode="before")
    @classmethod
    def restore_json_arrays_as_tuples(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if (
                not argument
                or not argument.strip()
                or "\x00" in argument
                or len(argument) > _MAX_ARGUMENT_LENGTH
            ):
                raise ValueError("AGENT_PROCESS_LAUNCH_ARGUMENT_INVALID")
        return value

    @field_validator("resolvedCwd")
    @classmethod
    def validate_cwd_text(cls, value: str) -> str:
        return _require_trimmed_text(value, "AGENT_PROCESS_LAUNCH_CWD_INVALID")

    @model_validator(mode="after")
    def validate_cross_field_semantics(self) -> "AgentProcessLaunchCommandV1":
        if self.processOrdinal != agent_process_ordinal(self.processKind):
            raise ValueError("AGENT_PROCESS_LAUNCH_ORDINAL_MISMATCH")
        platform = self.session.platform
        _require_resolved_absolute_path(
            self.resolvedCwd,
            platform=platform,
            code="AGENT_PROCESS_LAUNCH_CWD_INVALID",
        )
        _require_resolved_absolute_path(
            self.helper.resolvedPath,
            platform=platform,
            code="AGENT_PROCESS_LAUNCH_HELPER_PATH_INVALID",
        )
        _require_resolved_absolute_path(
            self.runtimeExecutable.resolvedPath,
            platform=platform,
            code="AGENT_PROCESS_LAUNCH_RUNTIME_EXECUTABLE_PATH_INVALID",
        )
        if self.argv[0] != self.runtimeExecutable.resolvedPath:
            raise ValueError("AGENT_PROCESS_LAUNCH_EXECUTABLE_ARGV_MISMATCH")
        _require_canonical_environment(self.childEnv, platform=platform)
        _require_launch_payload_size(
            argv=self.argv,
            child_env=self.childEnv,
            platform=platform,
        )
        return self

    def runtime_payload(self) -> dict[str, JsonValue]:
        """Return canonical JSON arrays while retaining immutable tuples in memory."""

        return self.model_dump(by_alias=True, exclude_none=False, mode="json")


class AgentProcessLaunchServerBindingsV1(_FrozenAgentModel):
    """Trusted identities attached inside the launch-preparation transaction."""

    runtimeLockHash: str = Field(pattern=_HEX_SHA256)
    runtimeProofHash: str = Field(pattern=_HEX_SHA256)
    workspaceProofId: str = Field(pattern=_WORKSPACE_PROOF_ID)
    workspaceProofHash: str = Field(pattern=_HEX_SHA256)
    toolAssetsHash: str = Field(pattern=_HEX_SHA256)


class AgentProcessLaunchSpecV1(_FrozenAgentModel):
    """Final server-bound command whose hash is persisted in the launch intent."""

    contractVersion: Literal["agent-process-launch-spec.v1"]
    command: AgentProcessLaunchCommandV1
    serverBindings: AgentProcessLaunchServerBindingsV1
    launchSpecHash: str = Field(pattern=_HEX_SHA256)

    @model_validator(mode="after")
    def validate_content_address(
        self,
        info: ValidationInfo,
    ) -> "AgentProcessLaunchSpecV1":
        hash_key = _require_launch_spec_hash_key_from_context(info.context)
        expected = agent_process_launch_spec_hash(self, hash_key=hash_key)
        if not hmac.compare_digest(expected, self.launchSpecHash):
            raise ValueError("AGENT_PROCESS_LAUNCH_SPEC_HASH_MISMATCH")
        return self

    def runtime_payload(self) -> dict[str, JsonValue]:
        return self.model_dump(by_alias=True, exclude_none=False, mode="json")


def build_agent_process_launch_command_v1(
    *,
    process_kind: AgentProcessKind,
    process_ordinal: int,
    argv: Sequence[str],
    resolved_cwd: str,
    child_env: Mapping[str, str] | Sequence[tuple[str, str]],
    stdio: AgentProcessStdioPolicyV1 | Mapping[str, object],
    session: AgentProcessSessionPolicyV1 | Mapping[str, object],
    helper: AgentProcessHelperIdentityV1 | Mapping[str, object],
    runtime_executable: AgentProcessRuntimeExecutableIdentityV1 | Mapping[str, object],
) -> AgentProcessLaunchCommandV1:
    """Build a canonical command without accepting hashes or server evidence."""

    normalized_session = _validate_session(session)
    normalized_argv = _normalize_argv(argv)
    normalized_env = _normalize_child_environment(
        child_env,
        platform=normalized_session.platform,
    )
    return AgentProcessLaunchCommandV1.model_validate(
        {
            "contractVersion": AGENT_PROCESS_LAUNCH_COMMAND_CONTRACT_VERSION,
            "processKind": process_kind,
            "processOrdinal": process_ordinal,
            "argv": normalized_argv,
            "resolvedCwd": resolved_cwd,
            "childEnv": normalized_env,
            "stdio": _model_payload(stdio, AgentProcessStdioPolicyV1),
            "session": normalized_session.runtime_payload(),
            "helper": _model_payload(helper, AgentProcessHelperIdentityV1),
            "runtimeExecutable": _model_payload(
                runtime_executable,
                AgentProcessRuntimeExecutableIdentityV1,
            ),
        }
    )


def build_agent_process_launch_server_bindings_v1(
    *,
    runtime_lock_hash: str,
    runtime_proof_hash: str,
    workspace_proof_id: str,
    workspace_proof_hash: str,
    tool_assets_hash: str,
) -> AgentProcessLaunchServerBindingsV1:
    """Build only trusted bindings; API command payloads cannot contain these."""

    return AgentProcessLaunchServerBindingsV1.model_validate(
        {
            "runtimeLockHash": runtime_lock_hash,
            "runtimeProofHash": runtime_proof_hash,
            "workspaceProofId": workspace_proof_id,
            "workspaceProofHash": workspace_proof_hash,
            "toolAssetsHash": tool_assets_hash,
        }
    )


def build_agent_process_launch_spec_v1(
    *,
    command: AgentProcessLaunchCommandV1 | Mapping[str, object],
    server_bindings: AgentProcessLaunchServerBindingsV1 | Mapping[str, object],
    hash_key: bytes,
) -> AgentProcessLaunchSpecV1:
    """Attach trusted identities and derive the sole accepted launch-spec hash."""

    normalized_hash_key = _require_launch_spec_hash_key(hash_key)
    normalized_command = _validate_command(command)
    normalized_bindings = _validate_bindings(server_bindings)
    payload: dict[str, object] = {
        "contractVersion": AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION,
        "command": normalized_command.runtime_payload(),
        "serverBindings": normalized_bindings.runtime_payload(),
    }
    payload["launchSpecHash"] = agent_process_launch_spec_hash(
        payload,
        hash_key=normalized_hash_key,
    )
    return AgentProcessLaunchSpecV1.model_validate(
        payload,
        context={"hash_key": normalized_hash_key},
    )


def agent_process_launch_spec_hash(
    spec: AgentProcessLaunchSpecV1 | Mapping[str, object],
    *,
    hash_key: bytes,
) -> str:
    """HMAC every command and binding without applying public secret scanners."""

    normalized_hash_key = _require_launch_spec_hash_key(hash_key)
    payload = (
        spec.runtime_payload() if isinstance(spec, AgentProcessLaunchSpecV1) else spec
    )
    missing = [field for field in _LAUNCH_SPEC_HASH_FIELDS if field not in payload]
    if missing:
        raise ValueError(
            "AGENT_PROCESS_LAUNCH_SPEC_HASH_FIELD_MISSING: " + ",".join(missing)
        )
    semantics = {field: payload[field] for field in _LAUNCH_SPEC_HASH_FIELDS}
    assert_json_interoperable_numbers(
        semantics,
        path="agent.processLaunchSpecHash",
    )
    canonical = json.dumps(
        semantics,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    message = (
        AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION.encode("utf-8")
        + b"\x00"
        + canonical.encode("utf-8")
    )
    return hmac.new(normalized_hash_key, message, hashlib.sha256).hexdigest()


def _validate_command(
    value: AgentProcessLaunchCommandV1 | Mapping[str, object],
) -> AgentProcessLaunchCommandV1:
    payload = (
        value.runtime_payload()
        if isinstance(value, AgentProcessLaunchCommandV1)
        else value
    )
    return AgentProcessLaunchCommandV1.model_validate(payload)


def _validate_session(
    value: AgentProcessSessionPolicyV1 | Mapping[str, object],
) -> AgentProcessSessionPolicyV1:
    payload = (
        value.runtime_payload()
        if isinstance(value, AgentProcessSessionPolicyV1)
        else value
    )
    return AgentProcessSessionPolicyV1.model_validate(payload)


def _validate_bindings(
    value: AgentProcessLaunchServerBindingsV1 | Mapping[str, object],
) -> AgentProcessLaunchServerBindingsV1:
    payload = (
        value.runtime_payload()
        if isinstance(value, AgentProcessLaunchServerBindingsV1)
        else value
    )
    return AgentProcessLaunchServerBindingsV1.model_validate(payload)


def _model_payload[ModelT: AgentSessionModel](
    value: ModelT | Mapping[str, object],
    model_type: type[ModelT],
) -> dict[str, JsonValue]:
    payload = value.runtime_payload() if isinstance(value, model_type) else value
    normalized = model_type.model_validate(payload)
    return normalized.runtime_payload()


def _normalize_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes, bytearray)) or not isinstance(argv, Sequence):
        raise ValueError("AGENT_PROCESS_LAUNCH_ARGUMENTS_INVALID")
    return tuple(argv)


def _normalize_child_environment(
    child_env: Mapping[str, str] | Sequence[tuple[str, str]],
    *,
    platform: AgentProcessPlatform,
) -> tuple[dict[str, str], ...]:
    if isinstance(child_env, Mapping):
        raw_entries: Sequence[tuple[object, object]] = list(child_env.items())
    elif isinstance(child_env, Sequence) and not isinstance(
        child_env, (str, bytes, bytearray)
    ):
        raw_entries = child_env  # type: ignore[assignment]
    else:
        raise ValueError("AGENT_PROCESS_LAUNCH_ENVIRONMENT_INVALID")

    normalized: list[AgentProcessEnvironmentVariableV1] = []
    for entry in raw_entries:
        if (
            not isinstance(entry, Sequence)
            or isinstance(entry, (str, bytes, bytearray))
            or len(entry) != 2
        ):
            raise ValueError("AGENT_PROCESS_LAUNCH_ENVIRONMENT_ENTRY_INVALID")
        normalized.append(
            AgentProcessEnvironmentVariableV1.model_validate(
                {"name": entry[0], "value": entry[1]}
            )
        )

    _require_distinct_environment(normalized, platform=platform)
    normalized.sort(key=lambda item: _environment_sort_key(item.name, platform))
    return tuple(item.runtime_payload() for item in normalized)  # type: ignore[return-value]


def _require_canonical_environment(
    entries: Sequence[AgentProcessEnvironmentVariableV1],
    *,
    platform: AgentProcessPlatform,
) -> None:
    _require_distinct_environment(entries, platform=platform)
    names = [entry.name for entry in entries]
    expected = sorted(names, key=lambda name: _environment_sort_key(name, platform))
    if names != expected:
        raise ValueError("AGENT_PROCESS_LAUNCH_ENVIRONMENT_ORDER_INVALID")


def _require_distinct_environment(
    entries: Sequence[AgentProcessEnvironmentVariableV1],
    *,
    platform: AgentProcessPlatform,
) -> None:
    aliases = [
        entry.name.casefold() if platform == "windows" else entry.name
        for entry in entries
    ]
    if len(aliases) != len(set(aliases)):
        raise ValueError("AGENT_PROCESS_LAUNCH_ENVIRONMENT_DUPLICATE")


def _require_launch_payload_size(
    *,
    argv: Sequence[str],
    child_env: Sequence[AgentProcessEnvironmentVariableV1],
    platform: AgentProcessPlatform,
) -> None:
    argv_bytes = sum(len(argument.encode("utf-8")) + 1 for argument in argv)
    environment_bytes = sum(
        len(entry.name.encode("utf-8")) + 1 + len(entry.value.encode("utf-8")) + 1
        for entry in child_env
    )
    if argv_bytes + environment_bytes > _MAX_LAUNCH_PAYLOAD_UTF8_BYTES:
        raise ValueError("AGENT_PROCESS_LAUNCH_PAYLOAD_TOO_LARGE")

    if platform != "windows":
        return
    command_line = list2cmdline(list(argv)) + "\x00"
    if _windows_utf16_code_units(command_line) > _MAX_WINDOWS_COMMAND_LINE_CHARACTERS:
        raise ValueError("AGENT_PROCESS_LAUNCH_WINDOWS_COMMAND_LINE_TOO_LARGE")
    environment_block = (
        "".join(f"{entry.name}={entry.value}\x00" for entry in child_env) + "\x00"
    )
    if (
        _windows_utf16_code_units(environment_block)
        > _MAX_WINDOWS_ENVIRONMENT_BLOCK_CHARACTERS
    ):
        raise ValueError("AGENT_PROCESS_LAUNCH_WINDOWS_ENVIRONMENT_BLOCK_TOO_LARGE")


def _windows_utf16_code_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _environment_sort_key(name: str, platform: AgentProcessPlatform) -> tuple[str, str]:
    return (name.casefold(), name) if platform == "windows" else (name, name)


def _require_resolved_absolute_path(
    value: str,
    *,
    platform: AgentProcessPlatform,
    code: str,
) -> None:
    if platform == "windows":
        if "/" in value:
            raise ValueError(code)
        path = PureWindowsPath(value)
    else:
        if value.startswith("//"):
            raise ValueError(code)
        path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or any(part in {".", ".."} for part in path.parts)
        or str(path) != value
    ):
        raise ValueError(code)


def _require_trimmed_text(value: str, code: str) -> str:
    if not value or not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError(code)
    return value


def _require_launch_spec_hash_key(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != _LAUNCH_SPEC_HASH_KEY_BYTES:
        raise ValueError("AGENT_PROCESS_LAUNCH_SPEC_HASH_KEY_INVALID")
    return value


def _require_launch_spec_hash_key_from_context(context: object) -> bytes:
    if not isinstance(context, Mapping) or "hash_key" not in context:
        raise ValueError("AGENT_PROCESS_LAUNCH_SPEC_HASH_CONTEXT_REQUIRED")
    return _require_launch_spec_hash_key(context["hash_key"])


__all__ = [
    "AGENT_PROCESS_GATE_PROTOCOL_VERSION",
    "AGENT_PROCESS_LAUNCH_COMMAND_CONTRACT_VERSION",
    "AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION",
    "AgentProcessEnvironmentVariableV1",
    "AgentProcessHelperIdentityV1",
    "AgentProcessLaunchCommandV1",
    "AgentProcessLaunchServerBindingsV1",
    "AgentProcessLaunchSpecV1",
    "AgentProcessPlatform",
    "AgentProcessRuntimeExecutableIdentityV1",
    "AgentProcessSessionPolicyV1",
    "AgentProcessStdioPolicyV1",
    "agent_process_launch_spec_hash",
    "build_agent_process_launch_command_v1",
    "build_agent_process_launch_server_bindings_v1",
    "build_agent_process_launch_spec_v1",
]
