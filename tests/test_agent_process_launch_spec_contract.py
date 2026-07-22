from __future__ import annotations

import hashlib
import hmac
import inspect
import json
from subprocess import list2cmdline
from types import MappingProxyType

import pytest
from pydantic import ValidationError

from core.contracts.agent_process_launch_spec import (
    AGENT_PROCESS_GATE_PROTOCOL_VERSION,
    AGENT_PROCESS_LAUNCH_COMMAND_CONTRACT_VERSION,
    AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION,
    AgentProcessLaunchCommandV1,
    AgentProcessLaunchServerBindingsV1,
    AgentProcessLaunchSpecV1,
    AgentProcessSessionPolicyV1,
    agent_process_launch_spec_hash,
    build_agent_process_launch_command_v1,
    build_agent_process_launch_server_bindings_v1,
    build_agent_process_launch_spec_v1,
)


_HASH_KEY = bytes(range(32))
_WRONG_HASH_KEY = bytes(range(1, 33))


def _canonical_hash(domain: str, payload: object, *, hash_key: bytes) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hmac.new(
        hash_key,
        domain.encode("utf-8") + b"\x00" + canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _stdio() -> dict[str, object]:
    return {
        "stdinMode": "null",
        "stdoutMode": "pipe",
        "stderrMode": "pipe",
        "textEncoding": "utf-8",
        "textErrors": "strict",
    }


def _session(platform: str = "linux") -> dict[str, object]:
    if platform == "windows":
        return {
            "platform": "windows",
            "launchMechanism": "windows_suspended_process",
            "containment": "windows_job_object_kill_on_close",
            "gateRelease": "resume_primary_thread",
            "closeFds": True,
        }
    return {
        "platform": "linux",
        "launchMechanism": "posix_gate_helper",
        "containment": "posix_new_session_process_group",
        "gateRelease": "write_inherited_pipe_frame",
        "closeFds": True,
    }


def _platform_values(platform: str) -> tuple[str, str, str, str]:
    if platform == "windows":
        return (
            r"E:\h2ometa\runs\run-1",
            r"E:\h2ometa\runner\agent_gate.py",
            r"E:\h2ometa\runtime\Scripts\snakemake.exe",
            r"E:\h2ometa\runtime\Scripts",
        )
    return (
        "/srv/h2ometa/runs/run-1",
        "/opt/h2ometa/runner/agent_gate.py",
        "/opt/h2ometa/runtime/bin/snakemake",
        "/opt/h2ometa/runtime/bin",
    )


def _build_command(
    *,
    platform: str = "linux",
    process_kind: object = "dry_run",
    process_ordinal: object = 1,
    child_env: object | None = None,
    resolved_cwd: str | None = None,
    helper_path: str | None = None,
    runtime_path: str | None = None,
    argv: object | None = None,
):
    cwd, default_helper, default_runtime, path_value = _platform_values(platform)
    executable = runtime_path or default_runtime
    return build_agent_process_launch_command_v1(
        process_kind=process_kind,  # type: ignore[arg-type]
        process_ordinal=process_ordinal,  # type: ignore[arg-type]
        argv=(
            argv
            if argv is not None
            else [executable, "--directory", resolved_cwd or cwd, " value "]
        ),  # type: ignore[arg-type]
        resolved_cwd=resolved_cwd or cwd,
        child_env=(
            child_env
            if child_env is not None
            else [("ZETA", "last"), ("PATH", path_value), ("EMPTY", "")]
        ),  # type: ignore[arg-type]
        stdio=_stdio(),
        session=_session(platform),
        helper={
            "helperId": "h2ometa.agent-process-gate",
            "helperVersion": "1.0.0",
            "gateProtocolVersion": AGENT_PROCESS_GATE_PROTOCOL_VERSION,
            "resolvedPath": helper_path or default_helper,
            "sha256": "a" * 64,
        },
        runtime_executable={
            "resolvedPath": executable,
            "sha256": "b" * 64,
        },
    )


def _build_bindings(**overrides: object) -> AgentProcessLaunchServerBindingsV1:
    values: dict[str, object] = {
        "runtime_lock_hash": "c" * 64,
        "runtime_proof_hash": "d" * 64,
        "workspace_proof_id": "awsp_" + "e" * 24,
        "workspace_proof_hash": "f" * 64,
        "tool_assets_hash": "0" * 64,
    }
    values.update(overrides)
    return build_agent_process_launch_server_bindings_v1(**values)  # type: ignore[arg-type]


def _build_spec(
    platform: str = "linux",
    *,
    hash_key: bytes = _HASH_KEY,
) -> AgentProcessLaunchSpecV1:
    return build_agent_process_launch_spec_v1(
        command=_build_command(platform=platform),
        server_bindings=_build_bindings(),
        hash_key=hash_key,
    )


def test_launch_spec_has_exact_canonical_json_and_server_derived_hash() -> None:
    source_env = [("ZETA", "last"), ("PATH", "/runtime/bin"), ("EMPTY", "")]
    source_snapshot = list(source_env)
    command = _build_command(child_env=source_env)
    bindings = _build_bindings()
    spec = build_agent_process_launch_spec_v1(
        command=command,
        server_bindings=bindings,
        hash_key=_HASH_KEY,
    )
    runtime = spec.runtime_payload()

    assert source_env == source_snapshot
    assert [entry["name"] for entry in command.runtime_payload()["childEnv"]] == [
        "EMPTY",
        "PATH",
        "ZETA",
    ]
    assert command.runtime_payload()["childEnv"][0]["value"] == ""
    semantics = {
        "contractVersion": AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION,
        "command": command.runtime_payload(),
        "serverBindings": bindings.runtime_payload(),
    }
    expected_hash = _canonical_hash(
        AGENT_PROCESS_LAUNCH_SPEC_CONTRACT_VERSION,
        semantics,
        hash_key=_HASH_KEY,
    )
    assert spec.launchSpecHash == expected_hash
    assert agent_process_launch_spec_hash(spec, hash_key=_HASH_KEY) == expected_hash
    assert runtime == {**semantics, "launchSpecHash": expected_hash}
    assert json.loads(json.dumps(runtime)) == runtime
    assert (
        AgentProcessLaunchSpecV1.model_validate(
            runtime,
            context={"hash_key": _HASH_KEY},
        )
        == spec
    )

    with pytest.raises(ValidationError, match="frozen_instance"):
        command.processOrdinal = 2  # type: ignore[misc]


def test_launch_spec_hash_key_and_validation_context_fail_closed() -> None:
    command = _build_command()
    bindings = _build_bindings()

    with pytest.raises(TypeError, match="hash_key"):
        build_agent_process_launch_spec_v1(  # type: ignore[call-arg]
            command=command,
            server_bindings=bindings,
        )
    spec = build_agent_process_launch_spec_v1(
        command=command,
        server_bindings=bindings,
        hash_key=_HASH_KEY,
    )
    with pytest.raises(TypeError, match="hash_key"):
        agent_process_launch_spec_hash(spec)  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="HASH_CONTEXT_REQUIRED"):
        AgentProcessLaunchSpecV1.model_validate(spec.runtime_payload())
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        AgentProcessLaunchSpecV1.model_validate(
            spec.runtime_payload(),
            context={"hash_key": _WRONG_HASH_KEY},
        )
    assert (
        agent_process_launch_spec_hash(
            spec,
            hash_key=_WRONG_HASH_KEY,
        )
        != spec.launchSpecHash
    )


@pytest.mark.parametrize(
    "hash_key",
    [b"", b"a" * 31, b"a" * 33, bytearray(b"a" * 32), "a" * 32],
)
def test_launch_spec_requires_exact_in_memory_32_byte_hash_key(
    hash_key: object,
) -> None:
    with pytest.raises(ValueError, match="HASH_KEY_INVALID"):
        build_agent_process_launch_spec_v1(
            command=_build_command(),
            server_bindings=_build_bindings(),
            hash_key=hash_key,  # type: ignore[arg-type]
        )


def test_secret_environment_is_hmac_hashable_and_hidden_from_repr_and_errors() -> None:
    secret = "sk-production-secret-value-0123456789"
    command = _build_command(child_env=[("DATABASE_PASSWORD", secret)])
    spec = build_agent_process_launch_spec_v1(
        command=command,
        server_bindings=_build_bindings(),
        hash_key=_HASH_KEY,
    )

    assert len(spec.launchSpecHash) == 64
    assert secret not in repr(command)
    assert secret not in repr(command.childEnv[0])
    assert secret not in repr(spec)

    invalid = command.runtime_payload()
    invalid["childEnv"][0]["value"] = secret + "\x00"
    with pytest.raises(ValidationError) as error:
        AgentProcessLaunchCommandV1.model_validate(invalid)
    assert secret not in str(error.value)


def test_command_is_public_semantics_and_cannot_carry_server_bindings() -> None:
    parameters = inspect.signature(build_agent_process_launch_spec_v1).parameters
    assert set(parameters) == {"command", "server_bindings", "hash_key"}
    assert "launch_spec_hash" not in parameters

    command_payload = _build_command().runtime_payload()
    command_payload["workspaceProofId"] = "awsp_" + "a" * 24
    command_payload["runtimeLockHash"] = "a" * 64
    command_payload["launchSpecHash"] = "a" * 64
    with pytest.raises(ValidationError, match="extra_forbidden"):
        build_agent_process_launch_spec_v1(
            command=command_payload,
            server_bindings=_build_bindings(),
            hash_key=_HASH_KEY,
        )

    with pytest.raises(TypeError, match="launch_spec_hash"):
        build_agent_process_launch_spec_v1(
            command=_build_command(),
            server_bindings=_build_bindings(),
            hash_key=_HASH_KEY,
            launch_spec_hash="a" * 64,  # type: ignore[call-arg]
        )


def test_spec_builder_revalidates_prebuilt_frozen_models() -> None:
    forged_command = _build_command().model_copy(update={"processOrdinal": 0})
    with pytest.raises(ValidationError):
        build_agent_process_launch_spec_v1(
            command=forged_command,
            server_bindings=_build_bindings(),
            hash_key=_HASH_KEY,
        )

    forged_bindings = _build_bindings().model_copy(update={"runtimeLockHash": "C" * 64})
    with pytest.raises(ValidationError):
        build_agent_process_launch_spec_v1(
            command=_build_command(),
            server_bindings=forged_bindings,
            hash_key=_HASH_KEY,
        )


def test_models_reject_stale_or_malformed_hashes() -> None:
    runtime = _build_spec().runtime_payload()
    runtime["launchSpecHash"] = "1" * 64
    with pytest.raises(ValidationError, match="LAUNCH_SPEC_HASH_MISMATCH"):
        AgentProcessLaunchSpecV1.model_validate(
            runtime,
            context={"hash_key": _HASH_KEY},
        )

    runtime["launchSpecHash"] = "A" * 64
    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        AgentProcessLaunchSpecV1.model_validate(
            runtime,
            context={"hash_key": _HASH_KEY},
        )


def test_hash_requires_every_top_level_semantic_field() -> None:
    runtime = _build_spec().runtime_payload()
    runtime.pop("command")
    with pytest.raises(ValueError, match="HASH_FIELD_MISSING: command"):
        agent_process_launch_spec_hash(runtime, hash_key=_HASH_KEY)


def test_hash_rejects_non_interoperable_numbers_before_canonicalization() -> None:
    runtime = _build_spec().runtime_payload()
    runtime.pop("launchSpecHash")
    command = runtime["command"]
    assert isinstance(command, dict)
    command["processOrdinal"] = (1 << 53) + 1

    with pytest.raises(ValueError, match="JSON_INTEGER_OUT_OF_SAFE_RANGE"):
        agent_process_launch_spec_hash(runtime, hash_key=_HASH_KEY)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("command", "processKind"), "run"),
        (("command", "processOrdinal"), 2),
        (("command", "argv"), ["/different"]),
        (("command", "resolvedCwd"), "/different"),
        (("command", "childEnv"), [{"name": "PATH", "value": "/different"}]),
        (("command", "stdio", "textErrors"), "replace"),
        (("command", "session", "gateRelease"), "different"),
        (("command", "helper", "sha256"), "1" * 64),
        (("command", "runtimeExecutable", "sha256"), "2" * 64),
        (("serverBindings", "runtimeLockHash"), "3" * 64),
        (("serverBindings", "runtimeProofHash"), "4" * 64),
        (("serverBindings", "workspaceProofId"), "awsp_" + "5" * 24),
        (("serverBindings", "workspaceProofHash"), "6" * 64),
        (("serverBindings", "toolAssetsHash"), "7" * 64),
    ],
)
def test_hash_is_sensitive_to_every_command_and_server_identity(
    path: tuple[str, ...],
    replacement: object,
) -> None:
    original = _build_spec().runtime_payload()
    original.pop("launchSpecHash")
    changed = json.loads(json.dumps(original))
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    assert agent_process_launch_spec_hash(
        changed,
        hash_key=_HASH_KEY,
    ) != agent_process_launch_spec_hash(
        original,
        hash_key=_HASH_KEY,
    )


@pytest.mark.parametrize(
    ("process_kind", "process_ordinal"),
    [
        ("execute", 1),
        ("dry_run", 0),
        ("dry_run", True),
        ("dry_run", "1"),
    ],
)
def test_command_rejects_invalid_kind_or_ordinal(
    process_kind: object,
    process_ordinal: object,
) -> None:
    with pytest.raises(ValidationError):
        _build_command(
            process_kind=process_kind,
            process_ordinal=process_ordinal,
        )


@pytest.mark.parametrize("argument", ["", " \t", "nul\x00tail"])
def test_command_rejects_empty_or_nul_arguments(argument: str) -> None:
    runtime_path = _platform_values("linux")[2]
    with pytest.raises(ValidationError, match="LAUNCH_ARGUMENT_INVALID"):
        _build_command(argv=[runtime_path, argument])


def test_command_rejects_non_sequence_or_non_string_argv() -> None:
    with pytest.raises(ValueError, match="LAUNCH_ARGUMENTS_INVALID"):
        _build_command(argv="/opt/h2ometa/runtime/bin/snakemake")
    with pytest.raises(ValidationError):
        _build_command(argv=[_platform_values("linux")[2], 3])


def test_windows_command_line_enforces_utf16_createprocess_limit() -> None:
    runtime_path = _platform_values("windows")[2]
    exact_argument = "x" * (32_767 - len(runtime_path) - 2)
    exact_command = _build_command(
        platform="windows",
        argv=[runtime_path, exact_argument],
    )
    assert len(list2cmdline(list(exact_command.argv)) + "\x00") == 32_767

    with pytest.raises(ValidationError, match="WINDOWS_COMMAND_LINE_TOO_LARGE"):
        _build_command(
            platform="windows",
            argv=[runtime_path, exact_argument + "x"],
        )


def test_windows_environment_block_enforces_utf16_createprocess_limit() -> None:
    exact_command = _build_command(
        platform="windows",
        child_env=[("BIG", "x" * 32_761)],
    )
    exact_entry = exact_command.childEnv[0]
    assert len(f"{exact_entry.name}={exact_entry.value}\x00\x00") == 32_767

    with pytest.raises(
        ValidationError,
        match="WINDOWS_ENVIRONMENT_BLOCK_TOO_LARGE",
    ):
        _build_command(
            platform="windows",
            child_env=[("BIG", "x" * 32_762)],
        )


def test_argv_and_environment_share_cross_platform_utf8_byte_cap() -> None:
    runtime_path = _platform_values("linux")[2]
    with pytest.raises(ValidationError, match="LAUNCH_PAYLOAD_TOO_LARGE"):
        _build_command(argv=[runtime_path, *("e" * 32_767 for _ in range(33))])

    with pytest.raises(ValidationError, match="LAUNCH_PAYLOAD_TOO_LARGE"):
        _build_command(child_env=[("BIG", "x" * 1_048_576)])


def test_environment_is_canonical_without_mutating_input_mapping() -> None:
    first_source = MappingProxyType({"ZETA": "last", "EMPTY": "", "PATH": "/bin"})
    second_source = {"PATH": "/bin", "ZETA": "last", "EMPTY": ""}
    first = _build_command(child_env=first_source)
    second = _build_command(child_env=second_source)

    assert first == second
    assert (
        build_agent_process_launch_spec_v1(
            command=first,
            server_bindings=_build_bindings(),
            hash_key=_HASH_KEY,
        ).launchSpecHash
        == build_agent_process_launch_spec_v1(
            command=second,
            server_bindings=_build_bindings(),
            hash_key=_HASH_KEY,
        ).launchSpecHash
    )


@pytest.mark.parametrize(
    ("platform", "child_env"),
    [
        ("linux", [("PATH", "/bin"), ("PATH", "/usr/bin")]),
        ("windows", [("Path", r"C:\bin"), ("PATH", r"C:\other")]),
    ],
)
def test_environment_rejects_platform_specific_duplicates(
    platform: str,
    child_env: list[tuple[str, str]],
) -> None:
    with pytest.raises(ValueError, match="ENVIRONMENT_DUPLICATE"):
        _build_command(platform=platform, child_env=child_env)


def test_linux_environment_names_remain_case_sensitive() -> None:
    command = _build_command(child_env=[("Path", "/one"), ("PATH", "/two")])
    assert [entry.name for entry in command.childEnv] == ["PATH", "Path"]


@pytest.mark.parametrize(
    "name",
    [
        "",
        " leading",
        "trailing ",
        "BAD=NAME",
        "NUL\x00NAME",
        "h2ometa_agent_GaTe_fd",
        "H2OMETA_AGENT_LAUNCH_HANDLE",
    ],
)
def test_environment_rejects_invalid_or_reserved_names(name: str) -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT_NAME_INVALID"):
        _build_command(child_env=[(name, "value")])


def test_environment_rejects_nul_value_but_preserves_empty_value() -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT_VALUE_INVALID"):
        _build_command(child_env=[("PATH", "bad\x00value")])
    command = _build_command(child_env=[("EMPTY", "")])
    assert command.childEnv[0].value == ""


def test_environment_rejects_empty_or_noncanonical_read_model() -> None:
    payload = _build_command().runtime_payload()
    payload["childEnv"] = []
    with pytest.raises(ValidationError, match="too_short"):
        AgentProcessLaunchCommandV1.model_validate(payload)

    payload = _build_command().runtime_payload()
    payload["childEnv"] = list(reversed(payload["childEnv"]))
    with pytest.raises(ValidationError, match="ENVIRONMENT_ORDER_INVALID"):
        AgentProcessLaunchCommandV1.model_validate(payload)


@pytest.mark.parametrize(
    "resolved_cwd",
    [
        "relative/run",
        "/srv/h2ometa/../run",
        "/srv//h2ometa/run",
        "/srv/h2ometa/run/",
        "//srv/h2ometa/run",
        "/srv/h2ometa/nul\x00run",
        " /srv/h2ometa/run",
    ],
)
def test_linux_paths_must_be_absolute_resolved_and_lexically_canonical(
    resolved_cwd: str,
) -> None:
    with pytest.raises((ValidationError, ValueError), match="LAUNCH_CWD_INVALID"):
        _build_command(resolved_cwd=resolved_cwd)


@pytest.mark.parametrize(
    "resolved_cwd",
    [
        r"relative\run",
        r"E:relative\run",
        "E:/h2ometa/runs/run-1",
        r"E:\h2ometa\..\run-1",
        "E:\\h2ometa\\runs\\run-1\\",
    ],
)
def test_windows_paths_must_be_absolute_resolved_and_lexically_canonical(
    resolved_cwd: str,
) -> None:
    with pytest.raises((ValidationError, ValueError), match="LAUNCH_CWD_INVALID"):
        _build_command(platform="windows", resolved_cwd=resolved_cwd)


def test_helper_and_runtime_paths_share_session_platform_rules() -> None:
    with pytest.raises(ValidationError, match="LAUNCH_HELPER_PATH_INVALID"):
        _build_command(helper_path="relative/helper.py")
    with pytest.raises(
        ValidationError,
        match="LAUNCH_RUNTIME_EXECUTABLE_PATH_INVALID",
    ):
        _build_command(runtime_path="relative/snakemake", argv=["relative/snakemake"])


def test_argv_zero_must_equal_proven_runtime_executable() -> None:
    with pytest.raises(ValidationError, match="EXECUTABLE_ARGV_MISMATCH"):
        _build_command(argv=["/opt/other/snakemake"])


@pytest.mark.parametrize(
    ("platform", "field", "replacement"),
    [
        ("linux", "launchMechanism", "windows_suspended_process"),
        ("linux", "containment", "windows_job_object_kill_on_close"),
        ("linux", "gateRelease", "resume_primary_thread"),
        ("windows", "launchMechanism", "posix_gate_helper"),
        ("windows", "containment", "posix_new_session_process_group"),
        ("windows", "gateRelease", "write_inherited_pipe_frame"),
    ],
)
def test_session_policy_rejects_cross_platform_combinations(
    platform: str,
    field: str,
    replacement: str,
) -> None:
    payload = _session(platform)
    payload[field] = replacement
    with pytest.raises(ValidationError, match="SESSION_POLICY_MISMATCH"):
        AgentProcessSessionPolicyV1.model_validate(payload)


def test_session_and_stdio_are_explicit_not_implicit_defaults() -> None:
    session = _session()
    session["closeFds"] = False
    with pytest.raises(ValidationError):
        AgentProcessSessionPolicyV1.model_validate(session)

    stdio = _stdio()
    stdio.pop("textEncoding")
    with pytest.raises(ValidationError, match="Field required"):
        build_agent_process_launch_command_v1(
            process_kind="dry_run",
            process_ordinal=1,
            argv=[_platform_values("linux")[2]],
            resolved_cwd=_platform_values("linux")[0],
            child_env={"PATH": "/bin"},
            stdio=stdio,
            session=_session(),
            helper=_build_command().helper.runtime_payload(),
            runtime_executable=_build_command().runtimeExecutable.runtime_payload(),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"runtime_lock_hash": "C" * 64},
        {"runtime_proof_hash": "sha256:" + "d" * 64},
        {"workspace_proof_id": "awsp_" + "E" * 24},
        {"workspace_proof_hash": "f" * 63},
        {"tool_assets_hash": "g" * 64},
    ],
)
def test_server_bindings_require_exact_lowercase_content_identities(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _build_bindings(**overrides)


def test_contract_versions_and_extra_fields_are_exact() -> None:
    command = _build_command().runtime_payload()
    command["contractVersion"] = "agent-process-launch-command.v2"
    with pytest.raises(ValidationError):
        AgentProcessLaunchCommandV1.model_validate(command)

    bindings = _build_bindings().runtime_payload()
    bindings["runId"] = "run-1"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        AgentProcessLaunchServerBindingsV1.model_validate(bindings)

    assert _build_command().contractVersion == (
        AGENT_PROCESS_LAUNCH_COMMAND_CONTRACT_VERSION
    )
