from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from core.remote_runner.install_lock import (
    _OWNER_LOCK_MIN_AGE_SECONDS,
    acquire_remote_install_lock,
    reclaim_stale_install_lock,
    reclaim_stale_install_lock_status,
    release_remote_install_lock,
)
from core.remote_runner.manager import RemoteRunnerManagerError


class FakeSSH:
    def __init__(self, responses: list[tuple[int, str, str]]) -> None:
        self.responses = list(responses)
        self.commands: list[str] = []

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        self.commands.append(cmd)
        if not self.responses:
            raise AssertionError(f"unexpected command: {cmd}")
        return self.responses.pop(0)


class LocalSSH:
    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        completed = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr


def test_reclaim_stale_install_lock_uses_owner_created_at_without_runner_process_guard() -> None:
    ssh = FakeSSH([(0, "reclaimed", "")])

    assert reclaim_stale_install_lock(
        ssh_service=ssh,
        lock_dir="/home/tester/.h2ometa/runner/locks/install-0.1.1-control-plane.lock",
    )

    command = ssh.commands[0]
    assert '"createdAt"' in command
    assert "OWNER_MIN_AGE" in command
    assert "young-owner" in command
    assert "stat -c %Y \"$LOCK/owner.json\"" in command
    assert "remote_runner\\.run" not in command
    assert "[l]aunch_remote_runner[.]sh" in command
    assert "[s]tart_service[.]sh" in command
    assert "t[a]r[[:space:]].*-xzf" in command
    assert "[c]onda-unpack" in command


@pytest.mark.skipif(os.name == "nt", reason="remote install-lock reclaim shell uses POSIX bash heredoc")
def test_reclaim_stale_install_lock_preserves_recent_owner_lock(tmp_path: Path) -> None:
    lock_dir = tmp_path / "install-test.lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(
        f'{{"createdAt":{int(time.time()) - 121}}}',
        encoding="utf-8",
    )

    reclaimed, status = reclaim_stale_install_lock_status(
        ssh_service=LocalSSH(),
        lock_dir=str(lock_dir),
        min_age_seconds=120,
    )

    assert not reclaimed
    assert status == "young-owner"
    assert lock_dir.exists()


@pytest.mark.skipif(os.name == "nt", reason="remote install-lock reclaim shell uses POSIX bash heredoc")
def test_reclaim_stale_install_lock_reclaims_old_owner_lock(tmp_path: Path) -> None:
    lock_dir = tmp_path / "install-test.lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(
        f'{{"createdAt":{int(time.time()) - _OWNER_LOCK_MIN_AGE_SECONDS - 5}}}',
        encoding="utf-8",
    )

    reclaimed, status = reclaim_stale_install_lock_status(
        ssh_service=LocalSSH(),
        lock_dir=str(lock_dir),
        min_age_seconds=120,
    )

    assert reclaimed
    assert status == "reclaimed"
    assert not lock_dir.exists()


def test_acquire_remote_install_lock_retries_immediately_after_stale_reclaim() -> None:
    ssh = FakeSSH(
        [
            (0, "busy", ""),
            (0, "reclaimed", ""),
            (0, "acquired", ""),
            (0, "", ""),
        ]
    )
    metadata: dict[str, object] = {}
    sleeps: list[float] = []

    owner_token = acquire_remote_install_lock(
        ssh_service=ssh,
        lock_dir="/home/tester/.h2ometa/runner/locks/install-0.1.1-control-plane.lock",
        remote_root="/home/tester/.h2ometa/runner",
        bootstrap_metadata=metadata,
        make_error=RemoteRunnerManagerError,
        attempts=2,
        delay_seconds=7,
        sleep=sleeps.append,
    )

    assert sleeps == []
    assert owner_token
    assert len(ssh.commands) == 4
    assert ssh.commands[0].startswith("mkdir -p")
    assert "H2OMETA_RECLAIM_LOCK" in ssh.commands[1]
    assert ssh.commands[2].startswith("mkdir -p")
    assert ssh.commands[3].endswith("/owner.json")
    assert '"ownerToken"' in ssh.commands[3]
    assert metadata["install_lock"] == {
        "path": "/home/tester/.h2ometa/runner/locks/install-0.1.1-control-plane.lock",
        "acquired": True,
        "waited": True,
        "stale_reclaimed": True,
        "last_reclaim_status": "reclaimed",
        "ownerFenced": True,
    }


def test_release_remote_install_lock_is_owner_fenced() -> None:
    ssh = FakeSSH([(0, "released", "")])

    release_remote_install_lock(
        ssh_service=ssh,
        lock_dir="/home/tester/.h2ometa/runner/locks/install-0.1.1-control-plane.lock",
        owner_token="owner-token-123",
    )

    command = ssh.commands[0]
    assert "H2OMETA_RELEASE_LOCK" in command
    assert "owner-token-123" in command
    assert '"ownerToken"' in command
    assert "owner-mismatch" in command
    assert command.count("rm -rf") == 1
