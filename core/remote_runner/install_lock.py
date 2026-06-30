from __future__ import annotations

import json
import secrets
import shlex
import time
from collections.abc import Callable
from typing import Any


ManagerErrorFactory = Callable[[str], Exception]


_ACTIVE_INSTALL_PROCESS_PATTERN = (
    r"t[a]r[[:space:]].*-xzf[[:space:]].*\.h2ometa/runner/(bundle-|tools/workflow-runtime-)"
    r"|[c]onda-unpack"
    r"|[l]aunch_remote_runner[.]sh"
    r"|[s]tart_service[.]sh"
)
_OWNER_LOCK_MIN_AGE_SECONDS = 30 * 60


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
    ) -> str:
        return acquire_remote_install_lock(
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
    def _release_remote_install_lock(*, ssh_service, lock_dir: str, owner_token: str) -> None:
        release_remote_install_lock(
            ssh_service=ssh_service,
            lock_dir=lock_dir,
            owner_token=owner_token,
        )


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
) -> str:
    parent = f"{remote_root}/locks"
    owner_token = secrets.token_urlsafe(24)
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
            previous_lock = dict(bootstrap_metadata.get("install_lock") or {})
            lock_metadata: dict[str, Any] = {
                "path": lock_dir,
                "acquired": True,
                "waited": attempt > 0,
            }
            if previous_lock.get("stale_reclaimed"):
                lock_metadata["stale_reclaimed"] = True
            if previous_lock.get("last_reclaim_status"):
                lock_metadata["last_reclaim_status"] = previous_lock["last_reclaim_status"]
            lock_metadata["ownerFenced"] = True
            bootstrap_metadata["install_lock"] = {
                **lock_metadata,
            }
            owner = {
                "version": str(lock_dir).rsplit("/", 1)[-1],
                "createdAt": int(time.time()),
                "ownerToken": owner_token,
            }
            quoted_owner = shlex.quote(json.dumps(owner, separators=(",", ":")))
            owner_exit_code, owner_stdout, owner_stderr = ssh_service.run(
                f"printf %s {quoted_owner} > {shlex.quote(f'{lock_dir}/owner.json')}",
                timeout=10,
            )
            if owner_exit_code != 0:
                detail = owner_stderr.strip() or owner_stdout.strip() or "remote install lock owner write failed"
                ssh_service.run(f"rmdir {shlex.quote(lock_dir)} >/dev/null 2>&1 || true", timeout=10)
                raise make_error(f"write remote install lock owner: {detail}")
            return owner_token
        if marker != "busy":
            raise make_error(f"acquire remote install lock: unexpected response {marker!r}")
        bootstrap_metadata["install_lock"]["waited"] = True
        reclaimed, reclaim_status = reclaim_stale_install_lock_status(
            ssh_service=ssh_service,
            lock_dir=lock_dir,
        )
        bootstrap_metadata["install_lock"]["last_reclaim_status"] = reclaim_status
        if reclaimed:
            bootstrap_metadata["install_lock"]["stale_reclaimed"] = True
            continue
        if attempt < attempts - 1:
            sleep(delay_seconds)
    details = describe_remote_install_lock(ssh_service=ssh_service, lock_dir=lock_dir)
    reclaim_status = str(dict(bootstrap_metadata.get("install_lock") or {}).get("last_reclaim_status") or "not-attempted")
    suffix = f" (last reclaim status: {reclaim_status})"
    suffix = f"{suffix}; {details}" if details else suffix
    raise make_error(f"remote runner install lock is busy: {lock_dir}{suffix}")


def reclaim_stale_install_lock(*, ssh_service, lock_dir: str, min_age_seconds: int = 120) -> bool:
    reclaimed, _status = reclaim_stale_install_lock_status(
        ssh_service=ssh_service,
        lock_dir=lock_dir,
        min_age_seconds=min_age_seconds,
    )
    return reclaimed


def reclaim_stale_install_lock_status(*, ssh_service, lock_dir: str, min_age_seconds: int = 120) -> tuple[bool, str]:
    command = r"""
set -u
LOCK=$1
MIN_AGE=$2
OWNER_MIN_AGE=$3
ACTIVE_PATTERN=$4
if [ ! -d "$LOCK" ]; then
  printf missing
  exit 0
fi
NOW=$(date +%s)
SOURCE_MTIME=$(stat -c %Y "$LOCK" 2>/dev/null || printf "$NOW")
HAS_OWNER=no
if [ -f "$LOCK/owner.json" ]; then
  HAS_OWNER=yes
  OWNER_CREATED=$(sed -n 's/.*"createdAt"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$LOCK/owner.json" | head -n 1)
  case "$OWNER_CREATED" in
    ''|*[!0-9]*)
      SOURCE_MTIME=$(stat -c %Y "$LOCK/owner.json" 2>/dev/null || printf "$SOURCE_MTIME")
      ;;
    *)
      SOURCE_MTIME=$OWNER_CREATED
      ;;
  esac
fi
MTIME=$SOURCE_MTIME
AGE=$((NOW - MTIME))
EFFECTIVE_MIN_AGE=$MIN_AGE
YOUNG_STATUS=young
if [ "$HAS_OWNER" = yes ] && [ "$OWNER_MIN_AGE" -gt "$EFFECTIVE_MIN_AGE" ]; then
  EFFECTIVE_MIN_AGE=$OWNER_MIN_AGE
  YOUNG_STATUS=young-owner
fi
if [ "$AGE" -lt 0 ] || [ "$AGE" -lt "$EFFECTIVE_MIN_AGE" ]; then
  printf "$YOUNG_STATUS"
  exit 0
fi
if ps -eo args= | grep -E "$ACTIVE_PATTERN" | grep -v grep >/dev/null; then
  printf active
  exit 0
fi
rm -rf "$LOCK"
printf reclaimed
""".strip()
    exit_code, stdout, _stderr = ssh_service.run(
        "bash -s -- {lock} {age} {owner_age} {pattern} <<'H2OMETA_RECLAIM_LOCK'\n{script}\nH2OMETA_RECLAIM_LOCK".format(
            lock=shlex.quote(lock_dir),
            age=shlex.quote(str(min_age_seconds)),
            owner_age=shlex.quote(str(max(min_age_seconds, _OWNER_LOCK_MIN_AGE_SECONDS))),
            pattern=shlex.quote(_ACTIVE_INSTALL_PROCESS_PATTERN),
            script=command,
        ),
        timeout=15,
    )
    tokens = stdout.strip().split()
    marker = tokens[-1] if tokens else ""
    if exit_code != 0:
        return False, f"error:{exit_code}"
    if marker == "reclaimed":
        return True, marker
    return False, marker or "empty"


def describe_remote_install_lock(*, ssh_service, lock_dir: str) -> str:
    command = r"""
set -u
LOCK=$1
ACTIVE_PATTERN=$2
if [ ! -e "$LOCK" ]; then
  printf 'exists=no'
  exit 0
fi
TYPE=file
if [ -d "$LOCK" ]; then
  TYPE=dir
fi
NOW=$(date +%s)
MTIME=$(stat -c %Y "$LOCK" 2>/dev/null || printf "$NOW")
AGE=$((NOW - MTIME))
ACTIVE=no
if ps -eo args= | grep -E "$ACTIVE_PATTERN" | grep -v grep >/dev/null; then
  ACTIVE=yes
fi
OWNER=
if [ -f "$LOCK/owner.json" ]; then
  OWNER=$(tr -d '\n' < "$LOCK/owner.json" | sed 's/"ownerToken"[[:space:]]*:[[:space:]]*"[^"]*"/"ownerToken":"<redacted>"/g' | cut -c 1-400)
fi
printf 'exists=yes type=%s ageSeconds=%s activeProcess=%s owner=%s' "$TYPE" "$AGE" "$ACTIVE" "$OWNER"
""".strip()
    exit_code, stdout, stderr = ssh_service.run(
        "bash -s -- {lock} {pattern} <<'H2OMETA_DESCRIBE_LOCK'\n{script}\nH2OMETA_DESCRIBE_LOCK".format(
            lock=shlex.quote(lock_dir),
            pattern=shlex.quote(_ACTIVE_INSTALL_PROCESS_PATTERN),
            script=command,
        ),
        timeout=15,
    )
    if exit_code != 0:
        return (stderr.strip() or stdout.strip() or "lock diagnostics unavailable").strip()
    return stdout.strip()


def release_remote_install_lock(*, ssh_service, lock_dir: str, owner_token: str) -> None:
    command = r"""
set -u
LOCK=$1
OWNER_TOKEN=$2
if [ ! -d "$LOCK" ]; then
  printf missing
  exit 0
fi
if [ ! -f "$LOCK/owner.json" ]; then
  printf owner-missing
  exit 23
fi
ACTUAL=$(sed -n 's/.*"ownerToken"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$LOCK/owner.json" | head -n 1)
if [ "$ACTUAL" != "$OWNER_TOKEN" ]; then
  printf owner-mismatch
  exit 23
fi
rm -rf "$LOCK"
printf released
""".strip()
    ssh_service.run(
        "bash -s -- {lock} {owner_token} <<'H2OMETA_RELEASE_LOCK'\n{script}\nH2OMETA_RELEASE_LOCK".format(
            lock=shlex.quote(lock_dir),
            owner_token=shlex.quote(owner_token),
            script=command,
        ),
        timeout=10,
    )
