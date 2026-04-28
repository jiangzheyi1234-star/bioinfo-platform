#!/usr/bin/env python3
"""Build a Linux remote-runner artifact on the configured SSH server and download it."""

from __future__ import annotations

import hashlib
import json
import posixpath
import shlex
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


VERSION = "0.1.0-control-plane"
PLATFORM = "linux-64"
ARTIFACT_NAME = f"h2ometa-remote-runner-{VERSION}-{PLATFORM}.tar.gz"


def find_repo_root() -> Path:
    path = Path.cwd().resolve()
    for candidate in (path, *path.parents):
        if (candidate / "config.py").exists() and (candidate / "core").is_dir():
            return candidate
    raise SystemExit("ERROR: run this script from inside the bio_ui repository")


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def print_json(label: str, payload: Any) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def connect():
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
        raise SystemExit(f"ERROR: SSH failed: {result.message}")
    return result.client


def run(client, command: str, *, timeout: int = 1200) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print_json("REMOTE_RUN", {"exit_code": exit_code, "command": command[:180], "stdout_tail": out[-1200:], "stderr_tail": err[-1200:]})
    if exit_code != 0:
        raise RuntimeError(err.strip() or out.strip() or f"remote command failed: {exit_code}")
    return out


def mkdir_p_sftp(sftp, remote_dir: str) -> None:
    parts = [part for part in remote_dir.split("/") if part]
    current = ""
    for part in parts:
        current = f"{current}/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def upload_tree(sftp, local_dir: Path, remote_dir: str) -> None:
    mkdir_p_sftp(sftp, remote_dir)
    for path in local_dir.rglob("*"):
        rel = path.relative_to(local_dir).as_posix()
        remote_path = posixpath.join(remote_dir, rel)
        if path.is_dir():
            mkdir_p_sftp(sftp, remote_path)
        else:
            mkdir_p_sftp(sftp, posixpath.dirname(remote_path))
            sftp.put(str(path), remote_path)


def write_remote_text(sftp, remote_path: str, content: str, mode: int | None = None) -> None:
    with sftp.open(remote_path, "w") as handle:
        handle.write(content)
    if mode is not None:
        sftp.chmod(remote_path, mode)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    out_dir = REPO_ROOT / "dist" / "remote-runner"
    out_dir.mkdir(parents=True, exist_ok=True)
    local_artifact = out_dir / ARTIFACT_NAME
    client = connect()
    try:
        run(client, 'test "$(uname -s):$(uname -m)" = "Linux:x86_64"')
        build_root = run(client, "mktemp -d /tmp/h2ometa-remote-artifact.XXXXXX").strip()
        bundle_dir = posixpath.join(build_root, "bundle")
        runtime_dir = posixpath.join(bundle_dir, "runtime")
        remote_runner_dir = posixpath.join(bundle_dir, "remote_runner")
        sftp = client.open_sftp()
        try:
            mkdir_p_sftp(sftp, bundle_dir)
            upload_tree(sftp, REPO_ROOT / "apps" / "remote_runner", remote_runner_dir)
            manifest = {
                "service": "h2ometa-remote",
                "version": VERSION,
                "platform": PLATFORM,
                "port": 8876,
                "runtime": {"provider": "bundled", "python": "runtime/bin/python"},
            }
            write_remote_text(sftp, posixpath.join(bundle_dir, "bootstrap_manifest.json"), json.dumps(manifest, indent=2) + "\n")
            write_remote_text(
                sftp,
                posixpath.join(bundle_dir, "launch_remote_runner.sh"),
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
                'RUNNER_PYTHON="${H2OMETA_RUNNER_PYTHON:-$RUN_DIR/runtime/bin/python}"\n'
                'if [ -x "$RUN_DIR/runtime/bin/conda-unpack" ] && [ ! -f "$RUN_DIR/runtime/.h2ometa-conda-unpacked" ]; then\n'
                '  "$RUN_DIR/runtime/bin/python" "$RUN_DIR/runtime/bin/conda-unpack"\n'
                '  touch "$RUN_DIR/runtime/.h2ometa-conda-unpacked"\n'
                "fi\n"
                'cd "$RUN_DIR"\n'
                'exec "$RUNNER_PYTHON" -m remote_runner.run\n',
                0o755,
            )
            write_remote_text(
                sftp,
                posixpath.join(bundle_dir, "start_service.sh"),
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'RUN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
                'CONFIG_PATH="${1:?config path required}"\n'
                'LOG_PATH="${2:?log path required}"\n'
                'mkdir -p "$(dirname "$LOG_PATH")"\n'
                'pkill -f "remote_runner.run" >/dev/null 2>&1 || true\n'
                'H2OMETA_REMOTE_CONFIG="$CONFIG_PATH" nohup "$RUN_DIR/launch_remote_runner.sh" >>"$LOG_PATH" 2>&1 &\n',
                0o755,
            )
            write_remote_text(
                sftp,
                posixpath.join(bundle_dir, "check_service.sh"),
                "#!/usr/bin/env bash\nset -euo pipefail\npgrep -af remote_runner.run\n",
                0o755,
            )
            write_remote_text(
                sftp,
                posixpath.join(bundle_dir, "run_workflow.sh"),
                "#!/usr/bin/env bash\nset -euo pipefail\nexec \"$@\"\n",
                0o755,
            )
            write_remote_text(
                sftp,
                posixpath.join(bundle_dir, "h2ometa-remote.service"),
                "[Unit]\nDescription=H2OMeta Remote Runner\n\n"
                "[Service]\nType=simple\nWorkingDirectory=%h/.h2ometa/runner/current\n"
                "Environment=H2OMETA_REMOTE_CONFIG=%h/.h2ometa/runner/shared/config/runner.json\n"
                "ExecStart=%h/.h2ometa/runner/current/launch_remote_runner.sh\nRestart=always\nRestartSec=2\n\n"
                "[Install]\nWantedBy=default.target\n",
            )
        finally:
            sftp.close()

        setup = f"""
set -euo pipefail
cd {shlex.quote(build_root)}
curl -fsSL https://micro.mamba.pm/api/micromamba/linux-64/latest -o micromamba.tar.bz2
mkdir -p micromamba
tar -xjf micromamba.tar.bz2 -C micromamba
MAMBA_ROOT_PREFIX="$PWD/mamba-root" ./micromamba/bin/micromamba create -y -p ./runtime-src -c conda-forge \
  "python>=3.12,<3.13" "fastapi>=0.115.0" "uvicorn>=0.34.0" "pydantic>=2.10.0" "conda-pack>=0.8.0"
./runtime-src/bin/conda-pack -p runtime-src -o runtime.tar.gz
mkdir -p {shlex.quote(runtime_dir)}
tar -xzf runtime.tar.gz -C {shlex.quote(runtime_dir)}
cd {shlex.quote(bundle_dir)}
tar -czf {shlex.quote(posixpath.join(build_root, ARTIFACT_NAME))} .
"""
        run(client, f"bash -lc {shlex.quote(setup)}", timeout=1800)
        sftp = client.open_sftp()
        try:
            sftp.get(posixpath.join(build_root, ARTIFACT_NAME), str(local_artifact))
        finally:
            sftp.close()
        digest = sha256_file(local_artifact)
        checksum = Path(str(local_artifact) + ".sha256")
        checksum.write_text(f"{digest}  {local_artifact.name}\n", encoding="utf-8")
        with tarfile.open(local_artifact, "r:gz") as archive:
            names = set(archive.getnames())
            if not any(name.strip("./") == "runtime/bin/python" for name in names):
                raise RuntimeError("downloaded artifact is missing runtime/bin/python")
        print_json("ARTIFACT", {"path": str(local_artifact), "sha256": str(checksum)})
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
