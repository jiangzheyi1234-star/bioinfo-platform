from __future__ import annotations

import hashlib
import json

import pytest

from core.contracts.agent_process_lifecycle import (
    AGENT_PROCESS_INCARNATION_HASH_DOMAIN,
    SYNTHETIC_PROCESS_INCARNATION_SCHEMA,
    WINDOWS_PROCESS_INCARNATION_SCHEMA,
    agent_process_incarnation_hash,
    build_synthetic_process_incarnation,
    build_windows_process_incarnation,
    require_agent_process_incarnation,
)
from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_synthetic_incarnation_is_exact_and_content_addressed() -> None:
    incarnation = build_synthetic_process_incarnation(
        pid=4242,
        nonce=_digest("synthetic-incarnation"),
    )

    assert incarnation == {
        "evidenceProfile": "synthetic-test-pid-nonce-v1",
        "nonce": _digest("synthetic-incarnation"),
        "pid": 4242,
        "schemaVersion": SYNTHETIC_PROCESS_INCARNATION_SCHEMA,
    }
    assert agent_process_incarnation_hash(
        incarnation
    ) == agent_process_incarnation_hash(dict(reversed(tuple(incarnation.items()))))
    assert len(agent_process_incarnation_hash(incarnation)) == 64
    assert AGENT_PROCESS_INCARNATION_HASH_DOMAIN == "agent-process-incarnation.v1"


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {
            "evidenceProfile": "synthetic-test-pid-nonce-v1",
            "nonce": "f" * 64,
            "pid": True,
            "schemaVersion": SYNTHETIC_PROCESS_INCARNATION_SCHEMA,
        },
        {
            "evidenceProfile": "synthetic-test-pid-nonce-v1",
            "extra": "forged",
            "nonce": "f" * 64,
            "pid": 1,
            "schemaVersion": SYNTHETIC_PROCESS_INCARNATION_SCHEMA,
        },
    ],
)
def test_incarnation_rejects_unknown_or_nonexact_payloads(payload: object) -> None:
    with pytest.raises(ValueError, match="AGENT_PROCESS_INCARNATION"):
        require_agent_process_incarnation(payload)


def test_linux_incarnation_reuses_strict_procfs_contract() -> None:
    linux = build_linux_process_incarnation(
        boot_id="12345678-1234-1234-1234-123456789abc",
        pid=77,
        proc_start_ticks=901,
    )

    assert require_agent_process_incarnation(linux) == linux
    assert len(agent_process_incarnation_hash(linux)) == 64


def test_windows_incarnation_binds_pid_and_creation_filetime() -> None:
    windows_from_integer = build_windows_process_incarnation(
        pid=8080,
        creation_time_filetime=133_800_000_000_000_000,
    )
    windows_from_decimal = build_windows_process_incarnation(
        pid=8080,
        creation_time_filetime="133800000000000000",
    )

    assert (
        windows_from_integer
        == windows_from_decimal
        == {
            "creationTimeFiletime": "133800000000000000",
            "evidenceProfile": "windows-process-pid-creation-filetime-v1",
            "pid": 8080,
            "schemaVersion": WINDOWS_PROCESS_INCARNATION_SCHEMA,
        }
    )
    assert agent_process_incarnation_hash(windows_from_integer) == (
        "8d84231dd41350f7da582b6ba7137d20a1f6216278961108eefaca0ccc1baec9"
    )
    round_tripped = json.loads(json.dumps(windows_from_integer))
    assert require_agent_process_incarnation(round_tripped) == windows_from_integer


@pytest.mark.parametrize(
    "creation_time_filetime",
    [
        0,
        -1,
        True,
        1 << 64,
        "0",
        "-1",
        "+1",
        "01",
        " 1",
        "1 ",
        str(1 << 64),
    ],
)
def test_windows_incarnation_rejects_noncanonical_or_out_of_range_filetime(
    creation_time_filetime: object,
) -> None:
    with pytest.raises(
        ValueError,
        match="AGENT_PROCESS_INCARNATION_CREATION_TIME_INVALID",
    ):
        build_windows_process_incarnation(
            pid=8080,
            creation_time_filetime=creation_time_filetime,
        )


def test_windows_incarnation_require_accepts_only_persistent_decimal_form() -> None:
    payload = build_windows_process_incarnation(
        pid=8080,
        creation_time_filetime=133_800_000_000_000_000,
    )
    payload["creationTimeFiletime"] = 133_800_000_000_000_000

    with pytest.raises(
        ValueError,
        match="AGENT_PROCESS_INCARNATION_CREATION_TIME_INVALID",
    ):
        require_agent_process_incarnation(payload)
