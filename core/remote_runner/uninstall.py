from __future__ import annotations

import hashlib
import json
import re
import shlex
import time
from typing import Any

from core.remote_runner.layout import (
    REMOTE_RUNNER_PROFILE_NAME,
    remote_runner_config,
    remote_runner_current,
    remote_runner_root,
    remote_runner_runtime_state,
    remote_runner_shared,
)
from core.remote_runner.release_prune import summarize_execution_activity


RUNNER_UNINSTALL_SCHEMA_VERSION = "h2ometa.remote-runner-uninstall.v1"
RUNNER_UNINSTALL_CONFIRMATION = "uninstall-runner-control-plane"
RUNNER_UNINSTALL_ACTIVE_LEASES_REASON = "RUNNER_UNINSTALL_ACTIVE_LEASES"
RUNNER_UNINSTALL_BLOCKED_REASON = "RUNNER_UNINSTALL_BLOCKED"
RUNNER_UNINSTALL_PLAN_CHANGED_REASON = "RUNNER_UNINSTALL_PLAN_CHANGED"
_SAFE_TARGET_NAME = re.compile(r"^[A-Za-z0-9_.:-]+$")


class RemoteRunnerUninstallMixin:
    _manager_error: type[Exception]

    def preview_uninstall(self, **kwargs) -> dict[str, Any]:
        return self._build_uninstall_plan(
            server_id=str(kwargs["server_id"]),
            ssh_service=kwargs["ssh_service"],
            server_record=dict(kwargs["server_record"]),
        )

    def run_uninstall(self, **kwargs) -> dict[str, Any]:
        server_id = str(kwargs["server_id"])
        ssh_service = kwargs["ssh_service"]
        server_record = dict(kwargs["server_record"])
        expected_plan_hash = str(kwargs["plan_hash"] or "").strip()
        home_dir = self._resolve_remote_home(ssh_service)
        runner_root = remote_runner_root(home_dir)
        lock_dir = f"{runner_root}/locks/uninstall.lock"
        lock_metadata = {"operation": "runner-uninstall", "serverId": server_id}
        lock_owner_token = self._acquire_remote_install_lock(
            ssh_service=ssh_service,
            lock_dir=lock_dir,
            remote_root=runner_root,
            bootstrap_metadata=lock_metadata,
            attempts=3,
            delay_seconds=0.5,
        )
        try:
            plan = self._build_uninstall_plan(
                server_id=server_id,
                ssh_service=ssh_service,
                server_record=server_record,
            )
            block_reasons = [str(item) for item in plan.get("blockReasons") or []]
            if block_reasons:
                raise self._manager_error(
                    "runner uninstall blocked because runner execution state is not idle",
                    status_code=409,
                    detail={
                        "reasonCode": _block_reason_code(block_reasons),
                        "serverId": server_id,
                        "blockReasons": block_reasons,
                        "activeLeaseCount": int(plan.get("activeLeaseCount") or 0),
                        "nextAction": "WAIT_FOR_RUNS_OR_REPAIR_BEFORE_UNINSTALL",
                    },
                )
            if not expected_plan_hash or expected_plan_hash != str(plan.get("planHash") or ""):
                raise self._manager_error(
                    "runner uninstall plan hash is stale or missing",
                    status_code=409,
                    detail={
                        "reasonCode": RUNNER_UNINSTALL_PLAN_CHANGED_REASON,
                        "serverId": server_id,
                        "expectedPlanHash": str(plan.get("planHash") or ""),
                    },
                )
            removed = self._run_uninstall_targets(
                ssh_service=ssh_service,
                runner_root=str(plan["runnerRoot"]),
                targets=[dict(item) for item in plan["uninstallTargets"]],
            )
        finally:
            self._release_remote_install_lock(
                ssh_service=ssh_service,
                lock_dir=lock_dir,
                owner_token=lock_owner_token,
            )
        return {
            **plan,
            "removedTargets": removed,
            "removedTargetCount": len(removed),
            "uninstalledAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _build_uninstall_plan(
        self,
        *,
        server_id: str,
        ssh_service,
        server_record: dict[str, Any],
    ) -> dict[str, Any]:
        home_dir = self._resolve_remote_home(ssh_service)
        runner_root = remote_runner_root(home_dir)
        shared = remote_runner_shared(home_dir)
        diagnostics = self.get_execution_diagnostics(
            server_id=server_id,
            ssh_service=ssh_service,
            server_record=server_record,
        )
        activity = summarize_execution_activity(diagnostics, make_error=self._manager_error)
        targets = _list_remote_uninstall_targets(
            ssh_service=ssh_service,
            home_dir=home_dir,
            runner_root=runner_root,
            shared=shared,
            make_error=self._manager_error,
        )
        plan = {
            "schemaVersion": RUNNER_UNINSTALL_SCHEMA_VERSION,
            "serverId": server_id,
            "runnerRoot": runner_root,
            "sharedRoot": shared,
            "controlPlaneOnly": True,
            "stopRunnerFirst": True,
            "preservedPaths": _preserved_paths(shared=shared, runner_root=runner_root),
            "uninstallTargets": targets,
            "targetCount": len(targets),
            "activeLeaseCount": activity["activeLeaseCount"],
            "allocatedResourceCount": activity["allocatedResourceCount"],
            "resourceWaitCount": activity["resourceWaitCount"],
            "claimedJobCount": activity["claimedJobCount"],
            "runningSlotCount": activity["runningSlotCount"],
            "blockReasons": list(activity["blockReasons"]),
        }
        plan["planHash"] = _plan_hash(plan)
        return plan

    @classmethod
    def _run_uninstall_targets(
        cls,
        *,
        ssh_service,
        runner_root: str,
        targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not targets:
            return []
        for target in targets:
            _validate_target(target, runner_root=runner_root, make_error=cls._manager_error)
        target_payload = json.dumps(
            [
                {
                    "name": str(item["name"]),
                    "path": str(item["path"]),
                    "kind": str(item["kind"]),
                }
                for item in targets
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        command = (
            "bash -s -- __RUNNER_ROOT__ __TARGET_PAYLOAD__ <<'H2OMETA_UNINSTALL_RUNNER'\n"
            "set -eu\n"
            "RUNNER_ROOT=$1\n"
            "TARGETS_JSON=$2\n"
            "REAL_ROOT=$(realpath -m -- \"$RUNNER_ROOT\")\n"
            "case \"$REAL_ROOT\" in\n"
            "  */.h2ometa/runner) : ;;\n"
            "  *) printf 'refusing unexpected runner root %s\\n' \"$REAL_ROOT\" >&2; exit 22 ;;\n"
            "esac\n"
            "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true\n"
            "if [ -f \"$RUNNER_ROOT/current/stop_service.sh\" ]; then bash \"$RUNNER_ROOT/current/stop_service.sh\" >/dev/null 2>&1 || true; fi\n"
            "pkill -f '[r]emote_runner.run' >/dev/null 2>&1 || true\n"
            "python3 - \"$REAL_ROOT\" \"$TARGETS_JSON\" <<'PY'\n"
            "import json, os, shutil, sys\n"
            "root = os.path.realpath(sys.argv[1])\n"
            "targets = json.loads(sys.argv[2])\n"
            "removed = []\n"
            "def inside(path):\n"
            "    real = os.path.realpath(path)\n"
            "    return real == root or real.startswith(root + os.sep)\n"
            "for target in targets:\n"
            "    name = str(target.get('name') or '')\n"
            "    path = str(target.get('path') or '')\n"
            "    kind = str(target.get('kind') or '')\n"
            "    if not path or '\\n' in path or '\\r' in path:\n"
            "        raise SystemExit(f'refusing invalid path for {name}')\n"
            "    if kind == 'systemd-unit':\n"
            "        if os.path.exists(path) or os.path.islink(path):\n"
            "            os.unlink(path)\n"
            "            removed.append({'name': name, 'path': path, 'kind': kind})\n"
            "        continue\n"
            "    if not inside(path):\n"
            "        raise SystemExit(f'refusing target outside runner root: {path}')\n"
            "    if not os.path.lexists(path):\n"
            "        continue\n"
            "    if kind == 'symlink':\n"
            "        if not os.path.islink(path):\n"
            "            raise SystemExit(f'refusing non-symlink target: {path}')\n"
            "        os.unlink(path)\n"
            "    elif kind == 'file':\n"
            "        if os.path.isdir(path) and not os.path.islink(path):\n"
            "            raise SystemExit(f'refusing directory as file target: {path}')\n"
            "        os.unlink(path)\n"
            "    elif kind == 'directory':\n"
            "        if os.path.islink(path):\n"
            "            raise SystemExit(f'refusing symlink directory target: {path}')\n"
            "        shutil.rmtree(path)\n"
            "    else:\n"
            "        raise SystemExit(f'unsupported target kind: {kind}')\n"
            "    removed.append({'name': name, 'path': path, 'kind': kind})\n"
            "print(json.dumps(removed, sort_keys=True, separators=(',', ':')))\n"
            "PY\n"
            "systemctl --user daemon-reload >/dev/null 2>&1 || true\n"
            "H2OMETA_UNINSTALL_RUNNER"
        )
        command = command.replace("__RUNNER_ROOT__", shlex.quote(runner_root)).replace(
            "__TARGET_PAYLOAD__",
            shlex.quote(target_payload),
        )
        exit_code, stdout, stderr = cls._run_checked(
            ssh_service,
            command,
            step="uninstall remote runner control plane",
            timeout=60,
        )
        _ = exit_code, stderr
        return _parse_removed_targets(stdout, make_error=cls._manager_error)


def _list_remote_uninstall_targets(
    *,
    ssh_service,
    home_dir: str,
    runner_root: str,
    shared: str,
    make_error: type[Exception],
) -> list[dict[str, Any]]:
    profile_path = f"{shared}/config/snakemake/default/{REMOTE_RUNNER_PROFILE_NAME}"
    service_unit = f"{home_dir}/.config/systemd/user/h2ometa-remote.service"
    command = (
        "bash -s -- __RUNNER_ROOT__ __CURRENT__ __CONFIG__ __RUNTIME_STATE__ __PROFILE_PATH__ __SERVICE_UNIT__ <<'H2OMETA_LIST_UNINSTALL_TARGETS'\n"
        "set -u\n"
        "RUNNER_ROOT=$1\n"
        "CURRENT=$2\n"
        "CONFIG=$3\n"
        "RUNTIME_STATE=$4\n"
        "PROFILE=$5\n"
        "SERVICE_UNIT=$6\n"
        "emit() {\n"
        "  name=$1; path=$2; expected=$3\n"
        "  if [ -L \"$path\" ]; then kind=symlink\n"
        "  elif [ -f \"$path\" ]; then kind=file\n"
        "  elif [ -d \"$path\" ]; then kind=directory\n"
        "  else return 0\n"
        "  fi\n"
        "  if [ \"$expected\" != any ] && [ \"$kind\" != \"$expected\" ]; then return 0; fi\n"
        "  real=$(realpath -m -- \"$path\")\n"
        "  printf '%s\\t%s\\t%s\\t%s\\n' \"$name\" \"$path\" \"$kind\" \"$real\"\n"
        "}\n"
        "emit current-symlink \"$CURRENT\" symlink\n"
        "emit releases-dir \"$RUNNER_ROOT/releases\" directory\n"
        "emit runner-config \"$CONFIG\" file\n"
        "emit runtime-state \"$RUNTIME_STATE\" file\n"
        "emit workflow-profile \"$PROFILE\" file\n"
        "if [ -f \"$SERVICE_UNIT\" ]; then\n"
        "  service_real=$(realpath -m -- \"$SERVICE_UNIT\")\n"
        "  printf 'systemd-user-unit\\t%s\\tsystemd-unit\\t%s\\n' \"$SERVICE_UNIT\" \"$service_real\"\n"
        "fi\n"
        "for bundle in \"$RUNNER_ROOT\"/bundle-*.tar.gz; do\n"
        "  [ -e \"$bundle\" ] || continue\n"
        "  emit runner-bundle \"$bundle\" file\n"
        "done\n"
        "H2OMETA_LIST_UNINSTALL_TARGETS"
    )
    replacements = {
        "__RUNNER_ROOT__": shlex.quote(runner_root),
        "__CURRENT__": shlex.quote(remote_runner_current(home_dir)),
        "__CONFIG__": shlex.quote(remote_runner_config(home_dir)),
        "__RUNTIME_STATE__": shlex.quote(remote_runner_runtime_state(home_dir)),
        "__PROFILE_PATH__": shlex.quote(profile_path),
        "__SERVICE_UNIT__": shlex.quote(service_unit),
    }
    for token, value in replacements.items():
        command = command.replace(token, value)
    exit_code, stdout, stderr = ssh_service.run(command, timeout=20)
    if exit_code != 0:
        detail = stderr.strip() or stdout.strip() or "list remote runner uninstall targets failed"
        raise make_error(detail)
    targets: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        name, path, kind, real_path = parts
        target = {"name": name, "path": path, "kind": kind, "realPath": real_path}
        _validate_target(target, runner_root=runner_root, make_error=make_error)
        targets.append(target)
    return targets


def _preserved_paths(*, shared: str, runner_root: str) -> list[dict[str, str]]:
    return [
        {"path": f"{shared}/data", "reason": "runtime database, artifact ledger, lineage, and evidence"},
        {"path": f"{shared}/uploads", "reason": "submitted input payloads"},
        {"path": f"{shared}/results", "reason": "workflow outputs and exported result payloads"},
        {"path": f"{shared}/work", "reason": "run work directories and resume evidence"},
        {"path": f"{shared}/logs", "reason": "operator diagnostics and failure investigation"},
        {"path": f"{shared}/conda-envs", "reason": "workflow execution environments"},
        {"path": f"{runner_root}/tools", "reason": "managed workflow runtime and reusable tools"},
    ]


def _validate_target(target: dict[str, Any], *, runner_root: str, make_error: type[Exception]) -> None:
    name = str(target.get("name") or "")
    path = str(target.get("path") or "")
    kind = str(target.get("kind") or "")
    if not _SAFE_TARGET_NAME.fullmatch(name):
        raise make_error(f"runner uninstall target name is invalid: {name}")
    if kind not in {"symlink", "file", "directory", "systemd-unit"}:
        raise make_error(f"runner uninstall target kind is invalid: {kind}")
    if not path or "\n" in path or "\r" in path:
        raise make_error(f"runner uninstall target path is invalid for {name}")
    if kind == "systemd-unit":
        if not path.endswith("/.config/systemd/user/h2ometa-remote.service"):
            raise make_error(f"refusing unexpected systemd unit uninstall target: {path}")
        return
    root = runner_root.rstrip("/")
    normalized = path.rstrip("/")
    if normalized != root and not normalized.startswith(f"{root}/"):
        raise make_error(f"refusing uninstall target outside runner root: {path}")
    if normalized in {
        root,
        f"{root}/shared",
        f"{root}/shared/data",
        f"{root}/shared/uploads",
        f"{root}/shared/results",
        f"{root}/shared/work",
        f"{root}/shared/logs",
        f"{root}/tools",
    }:
        raise make_error(f"refusing to uninstall preserved runner state path: {path}")


def _parse_removed_targets(stdout: str, *, make_error: type[Exception]) -> list[dict[str, Any]]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return []
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise make_error("runner uninstall did not return a valid removal manifest") from exc
    if not isinstance(payload, list):
        raise make_error("runner uninstall removal manifest is not a list")
    removed: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        removed.append(
            {
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "kind": str(item.get("kind") or ""),
            }
        )
    return removed


def _block_reason_code(block_reasons: list[str]) -> str:
    if "active-workflow-leases" in block_reasons:
        return RUNNER_UNINSTALL_ACTIVE_LEASES_REASON
    return RUNNER_UNINSTALL_BLOCKED_REASON


def _plan_hash(plan: dict[str, Any]) -> str:
    comparable = {key: value for key, value in plan.items() if key not in {"planHash"}}
    payload = json.dumps(comparable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
