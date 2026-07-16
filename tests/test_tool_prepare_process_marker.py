from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import apps.remote_runner.tool_prepare_process_marker as process_marker_module
from apps.remote_runner.tool_prepare_process_marker import (
    LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE,
    SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE,
    TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED,
    TOOL_PREPARE_PROCESS_MARKER_INVALID,
    ToolPrepareProcessMarker,
    ToolPrepareProcessMarkerError,
    UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE,
    validate_persisted_tool_prepare_process_marker,
)


BOOT_ID = "12345678-1234-5678-9abc-123456789abc"
INVOCATION_ID = "a" * 32


def test_linux_systemd_process_marker_captures_exact_process_incarnation(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4321)

    marker = ToolPrepareProcessMarker.capture(
        process_instance_id="process-systemd-1",
        process_pid=4321,
        hostname="runner-1",
        platform_name="linux",
        proc_root=proc_root,
        boot_id_path=boot_id_path,
        environment={
            "INVOCATION_ID": INVOCATION_ID,
        },
    )

    assert marker.identity_evidence_profile == SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE
    assert marker.boot_id == BOOT_ID
    assert marker.proc_start_ticks == 777
    assert marker.systemd_invocation_id == INVOCATION_ID
    assert marker.systemd_unit == "h2ometa-remote.service"
    assert marker.cgroup_path == "/user.slice/h2ometa-remote.service"
    assert ToolPrepareProcessMarker.from_json(marker.canonical_json()) == marker
    assert marker.fingerprint().startswith("sha256:")
    assert len(marker.fingerprint()) == 71


def test_linux_marker_without_managed_systemd_context_is_identity_only(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4322)

    marker = ToolPrepareProcessMarker.capture(
        process_instance_id="process-procfs-1",
        process_pid=4322,
        hostname="runner-2",
        platform_name="linux",
        proc_root=proc_root,
        boot_id_path=boot_id_path,
        environment={},
    )

    assert marker.identity_evidence_profile == LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE
    assert marker.cgroup_path == "/user.slice/h2ometa-remote.service"
    assert marker.systemd_invocation_id == ""
    assert marker.systemd_unit == ""


def test_systemd_identity_requires_exact_unit_cgroup_membership(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4326)
    proc_root.joinpath("4326", "cgroup").write_text(
        "0::/user.slice/other-runner.service\n",
        encoding="utf-8",
    )

    marker = ToolPrepareProcessMarker.capture(
        process_instance_id="process-wrong-cgroup-1",
        process_pid=4326,
        hostname="runner-6",
        platform_name="linux",
        proc_root=proc_root,
        boot_id_path=boot_id_path,
        environment={
            "INVOCATION_ID": INVOCATION_ID,
        },
    )

    assert marker.identity_evidence_profile == LINUX_PROCESS_IDENTITY_EVIDENCE_PROFILE


def test_systemd_identity_rejects_conflicting_declared_unit(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4328)

    with pytest.raises(ToolPrepareProcessMarkerError, match="systemdUnit"):
        ToolPrepareProcessMarker.capture(
            process_instance_id="process-wrong-unit-1",
            process_pid=4328,
            hostname="runner-8",
            platform_name="linux",
            proc_root=proc_root,
            boot_id_path=boot_id_path,
            environment={
                "H2OMETA_REMOTE_SERVICE_UNIT": "other-runner.service",
                "INVOCATION_ID": INVOCATION_ID,
            },
        )


def test_unsupported_platform_marker_is_explicitly_unverifiable() -> None:
    marker = ToolPrepareProcessMarker.capture(
        process_instance_id="process-windows-1",
        process_pid=123,
        hostname="desktop-runner",
        platform_name="win32",
    )

    assert marker.identity_evidence_profile == UNSUPPORTED_PROCESS_IDENTITY_EVIDENCE_PROFILE
    assert marker.boot_id == ""
    assert marker.proc_start_ticks == 0
    assert marker.systemd_invocation_id == ""
    assert marker.cgroup_path == ""


def test_explicit_zero_pid_is_rejected_instead_of_using_current_process() -> None:
    with pytest.raises(ToolPrepareProcessMarkerError, match="processPid"):
        ToolPrepareProcessMarker.capture(
            process_instance_id="process-zero-pid",
            process_pid=0,
            hostname="desktop-runner",
            platform_name="win32",
        )


def test_linux_cannot_use_unsupported_identity_profile() -> None:
    with pytest.raises(ToolPrepareProcessMarkerError, match="unsupported linux identity"):
        ToolPrepareProcessMarker.unsupported(
            process_instance_id="process-linux-downgrade",
            process_pid=123,
            hostname="runner-linux",
            platform_name="linux",
        )


def test_marker_fingerprint_and_identity_binding_are_verified(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4323)
    marker = ToolPrepareProcessMarker.capture(
        process_instance_id="process-binding-1",
        process_pid=4323,
        hostname="runner-3",
        platform_name="linux",
        proc_root=proc_root,
        boot_id_path=boot_id_path,
        environment={},
    )

    verified = validate_persisted_tool_prepare_process_marker(
        marker_json=marker.canonical_json(),
        marker_fingerprint=marker.fingerprint(),
        expected_process_instance_id="process-binding-1",
        expected_process_pid=4323,
        expected_hostname="runner-3",
    )
    assert verified == marker

    with pytest.raises(ToolPrepareProcessMarkerError, match=TOOL_PREPARE_PROCESS_MARKER_INVALID):
        validate_persisted_tool_prepare_process_marker(
            marker_json=marker.canonical_json(),
            marker_fingerprint="sha256:" + "0" * 64,
            expected_process_instance_id="process-binding-1",
            expected_process_pid=4323,
            expected_hostname="runner-3",
        )
    with pytest.raises(ToolPrepareProcessMarkerError, match="processPid binding"):
        validate_persisted_tool_prepare_process_marker(
            marker_json=marker.canonical_json(),
            marker_fingerprint=marker.fingerprint(),
            expected_process_instance_id="process-binding-1",
            expected_process_pid=9999,
            expected_hostname="runner-3",
        )


def test_marker_rejects_noncanonical_or_internally_inconsistent_payload(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4324)
    marker = ToolPrepareProcessMarker.capture(
        process_instance_id="process-canonical-1",
        process_pid=4324,
        hostname="runner-4",
        platform_name="linux",
        proc_root=proc_root,
        boot_id_path=boot_id_path,
        environment={},
    )

    with pytest.raises(ToolPrepareProcessMarkerError, match="non-canonical JSON"):
        ToolPrepareProcessMarker.from_json(marker.canonical_json() + " ")
    with pytest.raises(ToolPrepareProcessMarkerError, match="identityEvidenceProfile"):
        replace(
            marker,
            identity_evidence_profile=SYSTEMD_PROCESS_IDENTITY_EVIDENCE_PROFILE,
        ).validate()


def test_linux_capture_fails_closed_when_procfs_identity_is_missing(tmp_path: Path) -> None:
    boot_id_path = tmp_path / "boot_id"
    boot_id_path.write_text(BOOT_ID, encoding="utf-8")

    with pytest.raises(ToolPrepareProcessMarkerError, match=TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED):
        ToolPrepareProcessMarker.capture(
            process_instance_id="process-missing-1",
            process_pid=4325,
            hostname="runner-5",
            platform_name="linux",
            proc_root=tmp_path / "missing-proc",
            boot_id_path=boot_id_path,
            environment={},
        )


def test_linux_capture_rejects_proc_stat_for_another_pid(tmp_path: Path) -> None:
    proc_root, boot_id_path = _fake_procfs(tmp_path, pid=4327)
    stat_path = proc_root / "4327" / "stat"
    stat_path.write_text(stat_path.read_text(encoding="utf-8").replace("4327 ", "9999 ", 1))

    with pytest.raises(ToolPrepareProcessMarkerError, match=TOOL_PREPARE_PROCESS_MARKER_CAPTURE_FAILED):
        ToolPrepareProcessMarker.capture(
            process_instance_id="process-pid-mismatch",
            process_pid=4327,
            hostname="runner-7",
            platform_name="linux",
            proc_root=proc_root,
            boot_id_path=boot_id_path,
            environment={},
        )


def test_after_fork_callback_discards_inherited_marker_and_lock() -> None:
    inherited_marker = ToolPrepareProcessMarker.unsupported(
        process_instance_id="process-parent",
        process_pid=123,
        hostname="parent-runner",
        platform_name="test",
    )
    inherited_lock = process_marker_module._CURRENT_MARKER_LOCK
    process_marker_module._CURRENT_MARKER = inherited_marker

    process_marker_module._reset_current_process_marker_after_fork()

    assert process_marker_module._CURRENT_MARKER is None
    assert process_marker_module._CURRENT_MARKER_LOCK is not inherited_lock


def _fake_procfs(tmp_path: Path, *, pid: int) -> tuple[Path, Path]:
    proc_root = tmp_path / "proc"
    process_root = proc_root / str(pid)
    process_root.mkdir(parents=True)
    fields_before_start = ["S", *(str(index) for index in range(4, 22))]
    process_root.joinpath("stat").write_text(
        f"{pid} (worker ) name) {' '.join(fields_before_start)} 777 0 0\n",
        encoding="utf-8",
    )
    process_root.joinpath("cgroup").write_text(
        "0::/user.slice/h2ometa-remote.service\n",
        encoding="utf-8",
    )
    boot_id_path = tmp_path / "boot_id"
    boot_id_path.write_text(BOOT_ID + "\n", encoding="utf-8")
    return proc_root, boot_id_path
