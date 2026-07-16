from __future__ import annotations

from pathlib import Path

import pytest

from apps.remote_runner.process_incarnation import (
    capture_linux_process_incarnation,
)
from core.contracts.linux_process_incarnation import (
    LINUX_PROCESS_INCARNATION_EVIDENCE_PROFILE,
    LINUX_PROCESS_INCARNATION_SCHEMA,
    build_linux_process_incarnation,
    parse_proc_stat_start_ticks,
    require_linux_process_incarnation,
)


BOOT_ID = "abcdefab-cdef-abcd-efab-cdefabcdefab"


def _proc_stat(*, pid: int, comm: str, start_ticks: int) -> str:
    fields_three_through_twenty_two = ["S", *("0" for _ in range(18)), str(start_ticks)]
    return f"{pid} ({comm}) {' '.join(fields_three_through_twenty_two)}\n"


def test_build_linux_process_incarnation_returns_exact_payload() -> None:
    payload = build_linux_process_incarnation(
        boot_id=BOOT_ID,
        pid=123,
        proc_start_ticks=777,
    )

    assert payload == {
        "bootId": BOOT_ID,
        "evidenceProfile": LINUX_PROCESS_INCARNATION_EVIDENCE_PROFILE,
        "pid": 123,
        "procStartTicks": 777,
        "schemaVersion": LINUX_PROCESS_INCARNATION_SCHEMA,
    }
    assert require_linux_process_incarnation(payload) == payload


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("bootId", "not-a-boot-id", "bootId"),
        ("bootId", BOOT_ID.upper(), "bootId"),
        ("pid", True, "pid"),
        ("pid", 0, "pid"),
        ("procStartTicks", True, "procStartTicks"),
        ("procStartTicks", -1, "procStartTicks"),
        ("schemaVersion", "old", "schemaVersion"),
        ("evidenceProfile", "old", "evidenceProfile"),
    ],
)
def test_require_linux_process_incarnation_rejects_invalid_fields(
    field: str,
    replacement: object,
    message: str,
) -> None:
    payload = build_linux_process_incarnation(
        boot_id=BOOT_ID,
        pid=123,
        proc_start_ticks=777,
    )
    payload[field] = replacement

    with pytest.raises(ValueError, match=message):
        require_linux_process_incarnation(payload)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_require_linux_process_incarnation_rejects_non_exact_shape(
    mutation: str,
) -> None:
    payload = build_linux_process_incarnation(
        boot_id=BOOT_ID,
        pid=123,
        proc_start_ticks=777,
    )
    if mutation == "missing":
        payload.pop("procStartTicks")
    else:
        payload["liveness"] = True

    with pytest.raises(ValueError, match="fields must match exactly"):
        require_linux_process_incarnation(payload)


def test_parse_proc_stat_start_ticks_handles_spaces_and_right_parens_in_comm() -> None:
    raw = _proc_stat(pid=123, comm="worker )\n name", start_ticks=987654)

    assert parse_proc_stat_start_ticks(raw, expected_pid=123) == 987654


@pytest.mark.parametrize(
    ("raw", "expected_pid", "message"),
    [
        (_proc_stat(pid=124, comm="runner", start_ticks=777), 123, "pid mismatch"),
        ("123 runner) S " + "0 " * 18 + "777", 123, "invalid proc stat"),
        ("123 (runner) S 0 0", 123, "invalid proc stat"),
        (_proc_stat(pid=123, comm="runner", start_ticks=0), 123, "start ticks"),
    ],
)
def test_parse_proc_stat_start_ticks_rejects_invalid_observations(
    raw: str,
    expected_pid: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_proc_stat_start_ticks(raw, expected_pid=expected_pid)


def test_capture_linux_process_incarnation_reads_exact_procfs_files(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    proc_pid = proc_root / "123"
    proc_pid.mkdir(parents=True)
    (proc_pid / "stat").write_text(
        _proc_stat(pid=123, comm="remote runner )", start_ticks=777),
        encoding="utf-8",
    )
    boot_id_path = tmp_path / "boot_id"
    boot_id_path.write_text(f"{BOOT_ID}\n", encoding="utf-8")

    assert capture_linux_process_incarnation(
        pid=123,
        proc_root=proc_root,
        boot_id_path=boot_id_path,
    ) == build_linux_process_incarnation(
        boot_id=BOOT_ID,
        pid=123,
        proc_start_ticks=777,
    )


def test_capture_linux_process_incarnation_fails_closed_when_proc_is_missing(
    tmp_path: Path,
) -> None:
    boot_id_path = tmp_path / "boot_id"
    boot_id_path.write_text(f"{BOOT_ID}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="procfs process incarnation is unavailable"):
        capture_linux_process_incarnation(
            pid=123,
            proc_root=tmp_path / "proc",
            boot_id_path=boot_id_path,
        )
