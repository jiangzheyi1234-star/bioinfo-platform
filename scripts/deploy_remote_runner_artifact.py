from __future__ import annotations

import hashlib
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
from core.remote.ssh_connector import ssh_connect
from core.remote_runner.artifact import RemoteRunnerArtifactProvider
from core.remote_runner.release_manifest import REMOTE_RUNNER_VERSION


def connect_ssh():
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
        raise RuntimeError(f"SSH failed: {result.message}")
    return result.client


def run(client, command: str, timeout: int = 120) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return code, out, err


def run_checked(client, command: str, timeout: int = 120) -> str:
    code, out, err = run(client, command, timeout=timeout)
    if code != 0:
        raise RuntimeError(err.strip() or out.strip() or f"command failed: {command}")
    return out


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    archive = RemoteRunnerArtifactProvider(repo_root=REPO_ROOT).resolve(
        REMOTE_RUNNER_VERSION,
        platform="linux-64",
    ).archive_path
    digest = sha256_file(archive)
    client = connect_ssh()
    try:
        home = run_checked(client, "printf '%s' \"$HOME\"", timeout=10).strip()
        root = f"{home}/.h2ometa/runner"
        release = f"{root}/releases/{REMOTE_RUNNER_VERSION}"
        remote_bundle = f"{root}/bundle-{REMOTE_RUNNER_VERSION}.tar.gz"
        run_checked(
            client,
            (
                f"test -d {shlex.quote(root)} && "
                f"test -d {shlex.quote(root + '/shared')} && "
                f"test -f {shlex.quote(root + '/shared/config/runner.json')}"
            ),
            timeout=20,
        )
        sftp = client.open_sftp()
        try:
            sftp.put(str(archive), remote_bundle)
        finally:
            sftp.close()
        run_checked(
            client,
            (
                "systemctl --user stop h2ometa-remote.service >/dev/null 2>&1 || true; "
                f"if [ -x {shlex.quote(root + '/current/stop_service.sh')} ]; then "
                f"  bash {shlex.quote(root + '/current/stop_service.sh')} >/dev/null 2>&1 || true; "
                "fi; "
                f"rm -rf {shlex.quote(release)} && mkdir -p {shlex.quote(release)} && "
                f"tar -xzf {shlex.quote(remote_bundle)} -C {shlex.quote(release)} && "
                f"chmod 0755 {shlex.quote(release)}/*.sh && "
                f"printf '%s' {shlex.quote(digest)} > {shlex.quote(release + '/artifact.sha256')} && "
                f"ln -sfn {shlex.quote(release)} {shlex.quote(root + '/current')} && "
                f"rm -f {shlex.quote(remote_bundle)} {shlex.quote(root + '/shared/runtime/runner-state.json')}"
            ),
            timeout=180,
        )
        run_checked(client, "systemctl --user daemon-reload >/dev/null 2>&1 || true; systemctl --user restart h2ometa-remote.service", timeout=30)
        print(f"DEPLOYED {release} {digest}")
        return 0
    except RuntimeError as exc:
        raise SystemExit(
            "deploy_remote_runner_artifact.py only updates an already bootstrapped remote runner install with a "
            "prebuilt release artifact. It does not create ~/.h2ometa/runner, shared config, or runtime prerequisites. "
            f"Remote deploy failed: {exc}"
        ) from exc
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
