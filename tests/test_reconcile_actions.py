from __future__ import annotations

import time

from ui.main_window import MainWindow


class _FakeSSH:
    def __init__(self, mapping: dict[str, tuple[int, str, str]]) -> None:
        self._mapping = mapping

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        for key, value in self._mapping.items():
            if key in cmd:
                return value
        return (1, "", "")


def test_collect_reconcile_actions_marks_completed_on_done() -> None:
    ssh = _FakeSSH(
        {
            "status.txt": (0, "DONE\n", ""),
            "exit_code.txt": (0, "0\n", ""),
        }
    )
    actions = MainWindow._collect_reconcile_actions(
        ssh,
        "/remote/base",
        [("exec_1", "smp_1", "fastp")],
        [],
    )
    assert len(actions["mark_completed"]) == 1
    assert actions["mark_completed"][0]["execution_id"] == "exec_1"


def test_collect_reconcile_actions_marks_failed_on_stale_heartbeat() -> None:
    stale = str(int(time.time()) - 901)
    ssh = _FakeSSH(
        {
            "status.txt": (0, "RUNNING\n", ""),
            "exit_code.txt": (1, "", ""),
            "heartbeat.txt": (0, f"{stale}\n", ""),
        }
    )
    actions = MainWindow._collect_reconcile_actions(
        ssh,
        "/remote/base",
        [("exec_2", "smp_2", "fastp")],
        [],
    )
    assert len(actions["mark_failed"]) == 1
    assert actions["mark_failed"][0]["execution_id"] == "exec_2"


def test_collect_reconcile_actions_relinks_failed_when_resumed() -> None:
    fresh = str(int(time.time()))
    ssh = _FakeSSH(
        {
            "status.txt": (0, "RUNNING\n", ""),
            "heartbeat.txt": (0, f"{fresh}\n", ""),
        }
    )
    actions = MainWindow._collect_reconcile_actions(
        ssh,
        "/remote/base",
        [],
        [("exec_3", "smp_3", "fastp")],
    )
    assert len(actions["relink_running"]) == 1
    assert actions["relink_running"][0]["execution_id"] == "exec_3"


def test_parse_status_bundle_extracts_values() -> None:
    parsed = MainWindow._parse_status_bundle(
        "__STATUS__\nRUNNING\n__EXIT__\n0\n__HEARTBEAT__\n12345\n"
    )
    assert parsed["status"] == "RUNNING"
    assert parsed["exit"] == "0"
    assert parsed["heartbeat"] == "12345"


def test_read_status_bundle_falls_back_to_single_file_reads() -> None:
    ssh = _FakeSSH(
        {
            "__STATUS__": (1, "", ""),
            "status.txt": (0, "RUNNING\n", ""),
            "exit_code.txt": (0, "0\n", ""),
            "heartbeat.txt": (0, "12345\n", ""),
        }
    )
    status_text, exit_code, heartbeat = MainWindow._read_status_bundle(ssh, "/remote/base/task")
    assert status_text == "RUNNING"
    assert exit_code == "0"
    assert heartbeat == "12345"
