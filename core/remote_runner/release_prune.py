from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from typing import Any

from core.contracts.execution_activity import summarize_execution_activity
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.layout import remote_runner_config, remote_runner_current, remote_runner_root
from core.remote_runner.lifecycle_guard_owner import execution_lifecycle_guard_owner


RELEASE_PRUNE_SCHEMA_VERSION = "h2ometa.remote-runner-release-prune.v1"
RELEASE_PRUNE_CONFIRMATION = "prune-runner-releases"
RELEASE_PRUNE_ACTIVE_LEASES_REASON = "RUNNER_RELEASE_PRUNE_ACTIVE_LEASES"
RELEASE_PRUNE_BLOCKED_REASON = "RUNNER_RELEASE_PRUNE_BLOCKED"
RELEASE_PRUNE_GUARD_UNAVAILABLE_REASON = "RUNNER_RELEASE_PRUNE_GUARD_UNAVAILABLE"
RELEASE_PRUNE_PLAN_CHANGED_REASON = "RUNNER_RELEASE_PRUNE_PLAN_CHANGED"
EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION = "h2ometa.execution-lifecycle-guard.v1"
_VERSIONED_RELEASE_NAME = re.compile(r"^[0-9][0-9A-Za-z._-]*$")


class RemoteRunnerReleasePruneMixin:
    _manager_error: type[Exception]

    def preview_release_prune(self, **kwargs) -> dict[str, Any]:
        return self._build_release_prune_plan(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            server_record=dict(kwargs["server_record"]),
        )

    def run_release_prune(self, **kwargs) -> dict[str, Any]:
        server_id = str(kwargs["server_id"])
        ssh_service = kwargs["ssh_service"]
        server_record = dict(kwargs["server_record"])
        expected_plan_hash = str(kwargs["plan_hash"] or "").strip()
        home_dir = self._resolve_remote_home(ssh_service)
        runner_root = remote_runner_root(home_dir)
        lock_dir = f"{runner_root}/locks/release-prune.lock"
        lock_metadata = {"operation": "runner-release-prune", "serverId": server_id}
        lock_owner_token = self._acquire_remote_install_lock(
            ssh_service=ssh_service,
            lock_dir=lock_dir,
            remote_root=runner_root,
            bootstrap_metadata=lock_metadata,
            attempts=3,
            delay_seconds=0.5,
        )
        try:
            plan = self._build_release_prune_plan(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
            )
            _raise_if_prune_blocked(plan, server_id=server_id, make_error=self._manager_error)
            _require_matching_plan_hash(
                plan,
                expected_plan_hash=expected_plan_hash,
                server_id=server_id,
                make_error=self._manager_error,
            )
            guard_owner = execution_lifecycle_guard_owner(server_id=server_id, action="prune")
            guard = self._request_prune_lifecycle_guard(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                owner=guard_owner,
            )
            try:
                guarded_plan = self._build_release_prune_plan(
                    server_id=server_id,
                    ssh_service=ssh_service,
                    server_record=server_record,
                )
                _raise_if_prune_blocked(guarded_plan, server_id=server_id, make_error=self._manager_error)
                _require_matching_plan_hash(
                    guarded_plan,
                    expected_plan_hash=expected_plan_hash,
                    server_id=server_id,
                    make_error=self._manager_error,
                )
                deletable = [item for item in guarded_plan["releases"] if bool(item.get("deletable"))]
                deleted = self._delete_release_paths(
                    ssh_service=ssh_service,
                    releases_dir=str(guarded_plan["releasesDir"]),
                    release_paths=[str(item["path"]) for item in deletable],
                )
            except (RemoteRunnerManagerError, RemoteRunnerClientError, OSError, EOFError, ValueError, KeyError):
                self._release_prune_lifecycle_guard_best_effort(
                    server_id=server_id,
                    ssh_service=ssh_service,
                    server_record=server_record,
                    owner=guard_owner,
                )
                raise
            guard_release = self._release_prune_lifecycle_guard(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                owner=guard_owner,
            )
        finally:
            self._release_remote_install_lock(
                ssh_service=ssh_service,
                lock_dir=lock_dir,
                owner_token=lock_owner_token,
            )
        return {
            **guarded_plan,
            "executionLifecycleGuard": guard,
            "executionLifecycleGuardRelease": guard_release,
            "deletedReleases": deleted,
            "deletedReleaseCount": len(deleted),
            "prunedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _build_release_prune_plan(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
    ) -> dict[str, Any]:
        home_dir = self._resolve_remote_home(ssh_service)
        runner_root = remote_runner_root(home_dir)
        releases_dir = f"{runner_root}/releases"
        current_release = _read_current_release_target(ssh_service, remote_runner_current(home_dir))
        config_release = _read_config_release_dir(
            ssh_service,
            remote_runner_config(home_dir),
            make_error=self._manager_error,
        )
        diagnostics = self.get_execution_diagnostics(
            server_id=server_id,
            ssh_service=ssh_service,
            server_record=server_record,
        )
        activity = summarize_execution_activity(diagnostics, make_error=self._manager_error)
        block_reasons = list(activity["blockReasons"])
        protected_paths = _protected_release_paths(
            current_release=current_release,
            config_release=config_release,
            server_record=server_record,
        )
        raw_releases = _list_remote_releases(
            ssh_service,
            releases_dir,
            make_error=self._manager_error,
        )
        fallback_rollback_path = _fallback_rollback_path(
            raw_releases,
            current_release=current_release,
            protected_paths=protected_paths,
        )
        if fallback_rollback_path:
            protected_paths.add(fallback_rollback_path)
        releases = []
        for release in raw_releases:
            reasons = _protection_reasons(
                path=str(release["path"]),
                current_release=current_release,
                config_release=config_release,
                protected_paths=protected_paths,
                fallback_rollback_path=fallback_rollback_path,
                block_reasons=block_reasons,
            )
            releases.append({**release, "deletable": not reasons, "protectedReasons": reasons})
        releases.sort(key=lambda item: str(item["name"]))
        plan = {
            "schemaVersion": RELEASE_PRUNE_SCHEMA_VERSION,
            "serverId": server_id,
            "runnerRoot": runner_root,
            "releasesDir": releases_dir,
            "currentRelease": current_release,
            "configRelease": config_release,
            "protectedReleasePaths": sorted(protected_paths),
            "activeLeaseCount": activity["activeLeaseCount"],
            "allocatedResourceCount": activity["allocatedResourceCount"],
            "resourceWaitCount": activity["resourceWaitCount"],
            "queuedJobCount": activity["queuedJobCount"],
            "claimedJobCount": activity["claimedJobCount"],
            "runningSlotCount": activity["runningSlotCount"],
            "blockReasons": block_reasons,
            "releases": releases,
        }
        plan["deletableReleaseCount"] = sum(1 for item in releases if bool(item["deletable"]))
        plan["deletableBytes"] = sum(int(item["sizeBytes"]) for item in releases if bool(item["deletable"]))
        plan["planHash"] = _plan_hash(plan)
        return plan

    def _request_prune_lifecycle_guard(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        owner: str,
    ) -> dict[str, Any]:
        try:
            return self.request_execution_lifecycle_guard(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                action="prune",
                owner=owner,
                ttl_seconds=600,
                timeout=30,
            )
        except RemoteRunnerManagerError as exc:
            if (
                exc.status_code == 409
                and isinstance(exc.detail, dict)
                and exc.detail.get("schemaVersion") == EXECUTION_LIFECYCLE_GUARD_SCHEMA_VERSION
            ):
                _raise_lifecycle_guard_blocked(exc.detail, server_id=server_id, make_error=self._manager_error)
            raise self._manager_error(
                "runner release prune guard failed because execution lifecycle diagnostics are unavailable",
                status_code=409,
                detail={
                    "reasonCode": RELEASE_PRUNE_GUARD_UNAVAILABLE_REASON,
                    "serverId": server_id,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_PRUNE",
                },
            ) from exc
        except RemoteRunnerClientError as exc:
            raise self._manager_error(
                "runner release prune guard failed because execution lifecycle diagnostics are unavailable",
                status_code=409,
                detail={
                    "reasonCode": RELEASE_PRUNE_GUARD_UNAVAILABLE_REASON,
                    "serverId": server_id,
                    "nextAction": "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_PRUNE",
                },
            ) from exc

    def _release_prune_lifecycle_guard(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        owner: str,
    ) -> dict[str, Any]:
        return self.release_execution_lifecycle_guard(
            server_id=server_id,
            ssh_service=ssh_service,
            server_record=server_record,
            action="prune",
            owner=owner,
            timeout=30,
        )

    def _release_prune_lifecycle_guard_best_effort(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
        owner: str,
    ) -> None:
        try:
            self._release_prune_lifecycle_guard(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
                owner=owner,
            )
        except (RemoteRunnerManagerError, RemoteRunnerClientError, OSError, EOFError, ValueError, KeyError):
            return

    @classmethod
    def _delete_release_paths(
        cls,
        *,
        ssh_service,
        releases_dir: str,
        release_paths: list[str],
    ) -> list[dict[str, Any]]:
        if not release_paths:
            return []
        for path in release_paths:
            if not _is_child_release_path(path, releases_dir):
                raise cls._manager_error(f"refusing to prune release outside releases dir: {path}")
        command = (
            "bash -s -- {releases_dir} {paths} <<'H2OMETA_PRUNE_RELEASES'\n"
            "set -eu\n"
            "RELEASES_DIR=$1\n"
            "REAL_RELEASES_DIR=$(realpath -m -- \"$RELEASES_DIR\")\n"
            "shift\n"
            "for target in \"$@\"; do\n"
            "  [ -e \"$target\" ] || continue\n"
            "  [ ! -L \"$target\" ] || {{ printf 'refusing symlink %s\\n' \"$target\" >&2; exit 22; }}\n"
            "  real_target=$(realpath -m -- \"$target\")\n"
            "  case \"$target\" in\n"
            "    \"$RELEASES_DIR\"/*) : ;;\n"
            "    *) printf 'refusing %s\\n' \"$target\" >&2; exit 22 ;;\n"
            "  esac\n"
            "  case \"$real_target\" in\n"
            "    \"$REAL_RELEASES_DIR\"/*) rm -rf -- \"$real_target\" ;;\n"
            "    *) printf 'refusing canonical %s\\n' \"$real_target\" >&2; exit 22 ;;\n"
            "  esac\n"
            "done\n"
            "H2OMETA_PRUNE_RELEASES"
        ).format(
            releases_dir=shlex.quote(releases_dir),
            paths=" ".join(shlex.quote(path) for path in release_paths),
        )
        cls._run_checked(
            ssh_service,
            command,
            step="prune remote runner releases",
            timeout=60,
        )
        return [{"path": path, "name": path.rstrip("/").rsplit("/", 1)[-1]} for path in release_paths]


def _read_current_release_target(ssh_service, remote_current: str) -> str:
    exit_code, stdout, _stderr = ssh_service.run(f"readlink -f {shlex.quote(remote_current)}", timeout=10)
    return stdout.strip() if exit_code == 0 else ""


def _list_remote_releases(ssh_service, releases_dir: str, *, make_error: type[Exception]) -> list[dict[str, Any]]:
    command = (
        f"bash -s -- {shlex.quote(releases_dir)} <<'H2OMETA_LIST_RELEASES'\n"
        "set -u\n"
        "RELEASES_DIR=$1\n"
        "if [ ! -d \"$RELEASES_DIR\" ]; then exit 0; fi\n"
        "REAL_RELEASES_DIR=$(realpath -m -- \"$RELEASES_DIR\")\n"
        "for release in \"$RELEASES_DIR\"/*; do\n"
        "  [ -e \"$release\" ] || continue\n"
        "  [ ! -L \"$release\" ] || continue\n"
        "  [ -d \"$release\" ] || continue\n"
        "  name=${release##*/}\n"
        "  case \"$name\" in .* ) continue ;; esac\n"
        "  real_release=$(realpath -m -- \"$release\")\n"
        "  case \"$real_release\" in \"$REAL_RELEASES_DIR\"/*) ;; *) continue ;; esac\n"
        "  size_kb=$(du -sk -- \"$release\" 2>/dev/null | awk '{print $1}')\n"
        "  case \"$size_kb\" in ''|*[!0-9]*) size_kb=0 ;; esac\n"
        "  printf '%s\\t%s\\t%s\\n' \"$name\" \"$real_release\" \"$size_kb\"\n"
        "done\n"
        "H2OMETA_LIST_RELEASES"
    )
    exit_code, stdout, stderr = ssh_service.run(command, timeout=20)
    if exit_code != 0:
        detail = stderr.strip() or stdout.strip() or "list remote runner releases failed"
        raise make_error(detail)
    releases: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, path, size_kb = parts
        if not _is_versioned_release_name(name):
            continue
        try:
            size_bytes = max(0, int(size_kb or 0)) * 1024
        except ValueError as exc:
            raise make_error(f"remote runner release size is invalid for {name}") from exc
        releases.append(
            {
                "name": name,
                "path": path,
                "sizeBytes": size_bytes,
            }
        )
    return releases


def _read_config_release_dir(ssh_service, remote_config_path: str, *, make_error: type[Exception]) -> str:
    exit_code, stdout, _stderr = ssh_service.run(f"cat {shlex.quote(remote_config_path)}", timeout=10)
    if exit_code != 0:
        return ""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise make_error("remote runner config is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise make_error("remote runner config is not an object")
    return str(payload.get("release_dir") or "").strip()


def _protected_release_paths(
    *,
    current_release: str,
    config_release: str,
    server_record: dict[str, Any],
) -> set[str]:
    protected = {path for path in (current_release, config_release) if path}
    metadata = server_record.get("bootstrap_metadata") if isinstance(server_record.get("bootstrap_metadata"), dict) else {}
    for section_name in ("release_switch", "rollback"):
        section = metadata.get(section_name) if isinstance(metadata.get(section_name), dict) else {}
        for key in ("active_release", "target_release", "previous_release"):
            value = str(section.get(key) or "").strip()
            if value:
                protected.add(value)
    return protected


def _protection_reasons(
    *,
    path: str,
    current_release: str,
    config_release: str,
    protected_paths: set[str],
    fallback_rollback_path: str,
    block_reasons: list[str],
) -> list[str]:
    reasons = list(block_reasons)
    if current_release and path == current_release:
        reasons.append("current-release")
    if config_release and path == config_release and "remote-config-release" not in reasons:
        reasons.append("remote-config-release")
    if fallback_rollback_path and path == fallback_rollback_path:
        reasons.append("fallback-rollback-release")
    if path in protected_paths and "current-release" not in reasons:
        reasons.append("rollback-protected-release")
    return _unique(reasons)


def _fallback_rollback_path(
    releases: list[dict[str, Any]],
    *,
    current_release: str,
    protected_paths: set[str],
) -> str:
    non_current_protected = [path for path in protected_paths if path and path != current_release]
    if non_current_protected:
        return ""
    candidates = [
        str(release["path"])
        for release in sorted(releases, key=lambda item: str(item["name"]), reverse=True)
        if str(release["path"]) != current_release
    ]
    return candidates[0] if candidates else ""


def _block_reason_code(block_reasons: list[str]) -> str:
    if "active-workflow-leases" in block_reasons:
        return RELEASE_PRUNE_ACTIVE_LEASES_REASON
    return RELEASE_PRUNE_BLOCKED_REASON


def _raise_if_prune_blocked(plan: dict[str, Any], *, server_id: str, make_error: type[Exception]) -> None:
    block_reasons = [str(item) for item in plan.get("blockReasons") or []]
    if not block_reasons:
        return
    raise make_error(
        "runner release prune blocked because runner execution state is not idle",
        status_code=409,
        detail={
            "reasonCode": _block_reason_code(block_reasons),
            "serverId": server_id,
            "blockReasons": block_reasons,
            "activeLeaseCount": int(plan.get("activeLeaseCount") or 0),
            "queuedJobCount": int(plan.get("queuedJobCount") or 0),
            "nextAction": "WAIT_FOR_RUNS_OR_REPAIR_BEFORE_PRUNE",
        },
    )


def _raise_lifecycle_guard_blocked(
    guard_payload: dict[str, Any],
    *,
    server_id: str,
    make_error: type[Exception],
) -> None:
    block_reasons = [str(item) for item in guard_payload.get("blockReasons") or []]
    raise make_error(
        "runner release prune blocked because runner execution state is not idle",
        status_code=409,
        detail={
            "reasonCode": _block_reason_code(block_reasons),
            "serverId": server_id,
            "blockReasons": block_reasons,
            "activeLeaseCount": int(guard_payload.get("activeLeaseCount") or 0),
            "queuedJobCount": int(guard_payload.get("queuedJobCount") or 0),
            "nextAction": "WAIT_FOR_RUNS_OR_REPAIR_BEFORE_PRUNE",
        },
    )


def _require_matching_plan_hash(
    plan: dict[str, Any],
    *,
    expected_plan_hash: str,
    server_id: str,
    make_error: type[Exception],
) -> None:
    actual = str(plan.get("planHash") or "")
    if expected_plan_hash and expected_plan_hash == actual:
        return
    raise make_error(
        "runner release prune plan hash is stale or missing",
        status_code=409,
        detail={
            "reasonCode": RELEASE_PRUNE_PLAN_CHANGED_REASON,
            "serverId": server_id,
            "expectedPlanHash": actual,
        },
    )


def _is_versioned_release_name(name: str) -> bool:
    return bool(_VERSIONED_RELEASE_NAME.fullmatch(name))


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def _is_child_release_path(path: str, releases_dir: str) -> bool:
    normalized_dir = releases_dir.rstrip("/")
    normalized_path = path.rstrip("/")
    return normalized_path.startswith(f"{normalized_dir}/") and "\n" not in normalized_path


def _plan_hash(plan: dict[str, Any]) -> str:
    comparable = {
        key: value
        for key, value in plan.items()
        if key not in {"planHash"}
    }
    payload = json.dumps(comparable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
