#!/usr/bin/env python3
"""Atomically deploy a development remote-runner artifact to the configured staging host."""

from __future__ import annotations

import argparse
import json
import posixpath
import shlex
import sys
import tarfile
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.artifact_io import read_expected_sha256, read_manifest, sha256_file  # noqa: E402


def _print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _connect():
    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect

    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    result = ssh_connect(
        ip=str(resolved.get("host") or ""),
        port=int(resolved.get("port") or 22),
        user=str(resolved.get("user") or ""),
        password=password,
        key_file=key_file,
        use_agent=auth_mode == "agent",
        timeout=int(resolved.get("timeout_sec") or 5),
    )
    if not result.ok or result.client is None:
        raise RuntimeError(f"SSH connection failed: {result.message}")
    return result.client


def _archive_text(artifact: Path, member_name: str) -> str:
    with tarfile.open(artifact, "r:gz") as archive:
        member = next(
            (item for item in archive.getmembers() if item.name.strip("./") == member_name),
            None,
        )
        if member is None:
            raise RuntimeError(f"artifact member missing: {member_name}")
        handle = archive.extractfile(member)
        if handle is None:
            raise RuntimeError(f"artifact member unreadable: {member_name}")
        return handle.read().decode("utf-8")


def validate_staging_artifact(artifact: Path) -> dict[str, Any]:
    checksum_path = Path(str(artifact) + ".sha256")
    if not artifact.is_file():
        raise RuntimeError(f"artifact not found: {artifact}")
    if not checksum_path.is_file():
        raise RuntimeError(f"artifact checksum not found: {checksum_path}")
    expected = read_expected_sha256(checksum_path)
    actual = sha256_file(artifact)
    if actual != expected:
        raise RuntimeError(f"artifact checksum mismatch: expected={expected} actual={actual}")
    manifest = read_manifest(artifact)
    if manifest.get("service") != "h2ometa-remote":
        raise RuntimeError(f"unexpected artifact service: {manifest.get('service')}")
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise RuntimeError("artifact version is missing")

    executor_artifacts = _archive_text(artifact, "remote_runner/executor_artifacts.py")
    reconciler = _archive_text(artifact, "remote_runner/reconciler.py")
    actions = _archive_text(artifact, "remote_runner/reconciler_actions.py")
    archive_members = {item.name.strip("./") for item in tarfile.open(artifact, "r:gz").getmembers()}
    markers = {
        "candidateAdoption": "adopt_verified_candidate_outputs" in executor_artifacts,
        "activeReconciler": "run_active_reconciler_once" in reconciler,
        "sigkillEscalation": "signal.SIGKILL" in actions,
        "runWorkerResourceConfig": "remote_runner/worker_resource_config.py" in archive_members,
        "multiSlotGate": "H2OMETA_REMOTE_ENABLE_MULTI_SLOT"
        in _archive_text(artifact, "remote_runner/worker_supervisor.py"),
        "cancelResultMapping": "RUN_CANCELLED" in _archive_text(artifact, "remote_runner/executor_outcomes.py"),
        "executionObservability": (
            "remote_runner/execution_observability.py" in archive_members
            and "execution-observability.v1" in _archive_text(artifact, "remote_runner/execution_observability.py")
        ),
        "executionPolicy": (
            "remote_runner/execution_policy.py" in archive_members
            and "attempt_start_to_close_exceeded" in _archive_text(artifact, "remote_runner/execution_policy.py")
            and "expire_queued_jobs_over_ttl" in actions
        ),
    }
    missing = [key for key, present in markers.items() if not present]
    if missing:
        raise RuntimeError(f"artifact is missing P0-1 markers: {', '.join(missing)}")
    return {
        "path": str(artifact),
        "sha256": actual,
        "version": version,
        "platform": str(manifest.get("platform") or ""),
        **markers,
    }


def _remote_deploy_script(*, remote_artifact: str, version: str, nonce: str) -> str:
    root = "$HOME/.h2ometa/runner"
    release = f"{root}/releases/{version}"
    stage = f"{root}/releases/.{version}.staging-{nonce}"
    backup = f"{root}/releases/.{version}.backup-{nonce}"
    failed = f"{root}/releases/.{version}.failed-{nonce}"
    runtime_state = f"{root}/shared/runtime/runner-state.json"
    return f"""
set -euo pipefail
ARTIFACT={shlex.quote(remote_artifact)}
ROOT="{root}"
RELEASE="{release}"
STAGE="{stage}"
BACKUP="{backup}"
FAILED="{failed}"
RUNTIME_STATE="{runtime_state}"

rollback() {{
  status=$?
  trap - ERR
  set +e
  systemctl --user stop h2ometa-remote.service >/dev/null 2>&1
  if [ -d "$RELEASE" ]; then mv "$RELEASE" "$FAILED"; fi
  if [ -d "$BACKUP" ]; then mv "$BACKUP" "$RELEASE"; fi
  rm -f "$RUNTIME_STATE"
  systemctl --user restart h2ometa-remote.service >/dev/null 2>&1
  printf 'ROLLBACK release=%s failed=%s\\n' "$RELEASE" "$FAILED" >&2
  exit "$status"
}}
trap rollback ERR

test -f "$ARTIFACT"
test "$(readlink -f "$ROOT/current")" = "$(readlink -f "$RELEASE")"
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar -xzf "$ARTIFACT" -C "$STAGE"
grep -q 'adopt_verified_candidate_outputs' "$STAGE/remote_runner/executor_artifacts.py"
grep -q 'run_active_reconciler_once' "$STAGE/remote_runner/reconciler.py"
grep -q 'signal.SIGKILL' "$STAGE/remote_runner/reconciler_actions.py"
test -f "$STAGE/remote_runner/worker_resource_config.py"
grep -q 'H2OMETA_REMOTE_ENABLE_MULTI_SLOT' "$STAGE/remote_runner/worker_supervisor.py"
grep -q 'RUN_CANCELLED' "$STAGE/remote_runner/executor_outcomes.py"
test -f "$STAGE/remote_runner/execution_policy.py"
test -f "$STAGE/remote_runner/execution_observability.py"
grep -q 'execution-observability.v1' "$STAGE/remote_runner/execution_observability.py"
grep -q 'attempt_start_to_close_exceeded' "$STAGE/remote_runner/execution_policy.py"
grep -q 'expire_queued_jobs_over_ttl' "$STAGE/remote_runner/reconciler_actions.py"
chmod +x "$STAGE"/*.sh

systemctl --user stop h2ometa-remote.service
rm -f "$RUNTIME_STATE"
mv "$RELEASE" "$BACKUP"
mv "$STAGE" "$RELEASE"
systemctl --user restart h2ometa-remote.service

ready=0
for _ in $(seq 1 60); do
  if python3 - "$RUNTIME_STATE" "$ROOT/shared/config/runner.json" <<'PY'
import json
import pathlib
import sys
import urllib.request

try:
    state_path = pathlib.Path(sys.argv[1])
    config_path = pathlib.Path(sys.argv[2])
    if not state_path.exists():
        raise SystemExit(1)
    state = json.loads(state_path.read_text())
    cfg = json.loads(config_path.read_text())
    req = urllib.request.Request(
        f"http://127.0.0.1:{{state['bindPort']}}/health/ready",
        headers={{"Authorization": "Bearer " + cfg["token"]}},
    )
    payload = json.loads(urllib.request.urlopen(req, timeout=2).read().decode())
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if payload.get("status") == "ok" else 1)
PY
  then
    ready=1
    break
  fi
  sleep 1
done
test "$ready" = 1

trap - ERR
python3 - "$RELEASE" "$BACKUP" "$RUNTIME_STATE" <<'PY'
import json
import pathlib
import sys

state = json.loads(pathlib.Path(sys.argv[3]).read_text())
print(json.dumps({{
    "release": sys.argv[1],
    "backup": sys.argv[2],
    "pid": int(state["pid"]),
    "bindPort": int(state["bindPort"]),
    "version": state["version"],
}}, sort_keys=True))
PY
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deploy a locally built development artifact without changing the production release manifest. "
            "The current release is backed up and restored automatically if readiness fails."
        )
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--allow-staging-deploy",
        action="store_true",
        help="Required acknowledgement that the configured remote runner service will be restarted.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not args.allow_staging_deploy:
        print("ERROR: --allow-staging-deploy is required.")
        return 2
    artifact = args.artifact.resolve()
    metadata = validate_staging_artifact(artifact)
    _print_json("STAGING_ARTIFACT", metadata)

    client = _connect()
    remote_artifact = f"/tmp/h2ometa-staging-{uuid.uuid4().hex}.tar.gz"
    nonce = uuid.uuid4().hex[:12]
    try:
        sftp = client.open_sftp()
        try:
            sftp.put(str(artifact), remote_artifact)
        finally:
            sftp.close()
        command = _remote_deploy_script(
            remote_artifact=remote_artifact,
            version=str(metadata["version"]),
            nonce=nonce,
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=180)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode("utf-8", errors="replace").strip()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        if exit_code != 0:
            raise RuntimeError(error or output or f"remote staging deploy failed: {exit_code}")
        lines = [line for line in output.splitlines() if line.strip()]
        result = json.loads(lines[-1])
        _print_json("STAGING_DEPLOY", result)
        print("RESULT: ok")
        return 0
    finally:
        try:
            _stdin, cleanup_stdout, _stderr = client.exec_command(
                f"rm -f {shlex.quote(remote_artifact)}",
                timeout=20,
            )
            cleanup_stdout.channel.recv_exit_status()
        finally:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
