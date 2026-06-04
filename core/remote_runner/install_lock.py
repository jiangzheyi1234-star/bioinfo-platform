from __future__ import annotations

import json
import shlex
import time
from collections.abc import Callable
from typing import Any


ManagerErrorFactory = Callable[[str], Exception]


class RemoteRunnerInstallLockMixin:
    _manager_error: type[Exception]

    def _acquire_remote_install_lock(
        self,
        *,
        ssh_service,
        lock_dir: str,
        remote_root: str,
        bootstrap_metadata: dict[str, Any],
        attempts: int = 60,
        delay_seconds: float = 1.0,
    ) -> None:
        acquire_remote_install_lock(
            ssh_service=ssh_service,
            lock_dir=lock_dir,
            remote_root=remote_root,
            bootstrap_metadata=bootstrap_metadata,
            make_error=self._manager_error,
            attempts=attempts,
            delay_seconds=delay_seconds,
            sleep=time.sleep,
        )

    @staticmethod
    def _release_remote_install_lock(*, ssh_service, lock_dir: str) -> None:
        release_remote_install_lock(ssh_service=ssh_service, lock_dir=lock_dir)


def acquire_remote_install_lock(
    *,
    ssh_service,
    lock_dir: str,
    remote_root: str,
    bootstrap_metadata: dict[str, Any],
    make_error: ManagerErrorFactory,
    attempts: int = 60,
    delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    parent = f"{remote_root}/locks"
    command = (
        "mkdir -p {parent} && "
        "if mkdir {lock} 2>/dev/null; then "
        "printf acquired; "
        "else "
        "printf busy; "
        "fi"
    ).format(parent=shlex.quote(parent), lock=shlex.quote(lock_dir))
    bootstrap_metadata["install_lock"] = {"path": lock_dir, "acquired": False, "waited": False}
    for attempt in range(attempts):
        exit_code, stdout, stderr = ssh_service.run(command, timeout=10)
        if exit_code != 0:
            detail = stderr.strip() or stdout.strip() or "remote install lock check failed"
            raise make_error(f"acquire remote install lock: {detail}")
        marker = stdout.strip()
        if marker == "acquired" or marker == "":
            bootstrap_metadata["install_lock"] = {
                "path": lock_dir,
                "acquired": True,
                "waited": attempt > 0,
            }
            owner = {
                "version": str(lock_dir).rsplit("/", 1)[-1],
                "createdAt": int(time.time()),
            }
            quoted_owner = shlex.quote(json.dumps(owner, separators=(",", ":")))
            ssh_service.run(
                f"printf %s {quoted_owner} > {shlex.quote(f'{lock_dir}/owner.json')}",
                timeout=10,
            )
            return
        if marker != "busy":
            raise make_error(f"acquire remote install lock: unexpected response {marker!r}")
        bootstrap_metadata["install_lock"]["waited"] = True
        reclaimed = reclaim_stale_install_lock(
            ssh_service=ssh_service,
            lock_dir=lock_dir,
        )
        if reclaimed:
            bootstrap_metadata["install_lock"]["stale_reclaimed"] = True
            continue
        if attempt < attempts - 1:
            sleep(delay_seconds)
    raise make_error(f"remote runner install lock is busy: {lock_dir}")


def reclaim_stale_install_lock(*, ssh_service, lock_dir: str, min_age_seconds: int = 120) -> bool:
    command = r"""
set -u
LOCK=$1
MIN_AGE=$2
if [ ! -d "$LOCK" ]; then
  printf missing
  exit 0
fi
if [ -f "$LOCK/owner.json" ]; then
  printf owned
  exit 0
fi
NOW=$(date +%s)
MTIME=$(stat -c %Y "$LOCK" 2>/dev/null || printf "$NOW")
AGE=$((NOW - MTIME))
if [ "$AGE" -lt "$MIN_AGE" ]; then
  printf young
  exit 0
fi
if ps -ef | grep -E 'remote_runner\.run|launch_remote_runner|h2ometa-remote-runner' | grep -v grep >/dev/null; then
  printf active
  exit 0
fi
rm -rf "$LOCK"
printf reclaimed
""".strip()
    exit_code, stdout, _stderr = ssh_service.run(
        "bash -s -- {lock} {age} <<'H2OMETA_RECLAIM_LOCK'\n{script}\nH2OMETA_RECLAIM_LOCK".format(
            lock=shlex.quote(lock_dir),
            age=shlex.quote(str(min_age_seconds)),
            script=command,
        ),
        timeout=15,
    )
    return exit_code == 0 and stdout.strip() == "reclaimed"


def release_remote_install_lock(*, ssh_service, lock_dir: str) -> None:
    ssh_service.run(f"rm -rf {shlex.quote(lock_dir)}", timeout=10)
