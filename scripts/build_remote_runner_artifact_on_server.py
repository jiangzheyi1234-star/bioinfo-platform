#!/usr/bin/env python3
"""Build the Linux remote-runner control-plane artifact on the configured SSH server."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.release_manifest import REMOTE_RUNNER_ARTIFACT, REMOTE_RUNNER_VERSION  # noqa: E402

CORE_RUNTIME_HELPER_FILES = (
    "async_boundary.py",
    "api_payloads.py",
    "api_responses.py",
    "logging_config.py",
    "problem_responses.py",
    "problem_status.py",
)


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


def run(client, command: str, *, timeout: int = 1800) -> str:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print_json(
        "REMOTE_RUN",
        {
            "command": command[:220],
            "exit_code": exit_code,
            "stdout_tail": out[-1600:],
            "stderr_tail": err[-1600:],
        },
    )
    if exit_code != 0:
        raise RuntimeError(err.strip() or out.strip() or f"remote command failed: {exit_code}")
    return out


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download_artifact_atomically(sftp, remote_artifact: str, local_artifact: Path) -> str:
    tmp_artifact = local_artifact.with_name(f".{local_artifact.name}.downloading")
    tmp_checksum = local_artifact.with_name(f".{local_artifact.name}.sha256.tmp")
    try:
        tmp_artifact.unlink(missing_ok=True)
        tmp_checksum.unlink(missing_ok=True)
        sftp.get(remote_artifact, str(tmp_artifact))
        digest = sha256_file(tmp_artifact)
        tmp_checksum.write_text(f"{digest}  {local_artifact.name}\n", encoding="utf-8")
        tmp_artifact.replace(local_artifact)
        tmp_checksum.replace(Path(str(local_artifact) + ".sha256"))
        return digest
    except Exception:
        tmp_artifact.unlink(missing_ok=True)
        tmp_checksum.unlink(missing_ok=True)
        raise


def platform_from_uname(value: str) -> str:
    normalized = value.strip()
    if normalized == "Linux:x86_64":
        return "linux-64"
    if normalized in {"Linux:aarch64", "Linux:arm64"}:
        return "linux-aarch64"
    raise RuntimeError(f"unsupported remote runner build platform: {normalized}")


def micromamba_platform(platform: str) -> str:
    if platform in {"linux-64", "linux-aarch64"}:
        return platform
    raise RuntimeError(f"unsupported remote runner build platform: {platform}")


def mkdir_p_sftp(sftp, remote_dir: str) -> None:
    parts = [part for part in remote_dir.split("/") if part]
    current = ""
    for part in parts:
        current = f"{current}/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def git_status_for_path(path: Path) -> str:
    return git_status_for_paths([path])


def git_status_for_paths(paths: list[Path] | tuple[Path, ...]) -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *(str(path.relative_to(REPO_ROOT)) for path in paths)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def remote_runner_release_source_paths() -> tuple[Path, ...]:
    return (
        REPO_ROOT / "apps" / "remote_runner",
        REPO_ROOT / "core" / "__init__.py",
        *(REPO_ROOT / "core" / filename for filename in CORE_RUNTIME_HELPER_FILES),
        REPO_ROOT / "core" / "contracts",
    )


def git_tracked_release_files(local_dir: Path, *, include_untracked: bool = False) -> list[Path]:
    release_roots = [str(local_dir.relative_to(REPO_ROOT))]
    commands = [["git", "ls-files", *release_roots]]
    if include_untracked:
        commands.append(["git", "ls-files", "--others", "--exclude-standard", *release_roots])
    raw_paths: list[str] = []
    for command in commands:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        raw_paths.extend(result.stdout.splitlines())
    files: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        path = REPO_ROOT / raw.strip()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            continue
        rel_parts = path.relative_to(local_dir).parts
        if ".test" in rel_parts and rel_parts[-1] != "run-config.json":
            continue
        if "__pycache__" in rel_parts:
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    if not files:
        raise RuntimeError(f"no release files found under {local_dir}")
    return files


def upload_tree(sftp, local_dir: Path, remote_dir: str, *, include_untracked: bool = False) -> None:
    mkdir_p_sftp(sftp, remote_dir)
    for path in git_tracked_release_files(local_dir, include_untracked=include_untracked):
        rel = path.relative_to(local_dir).as_posix()
        remote_path = posixpath.join(remote_dir, rel)
        mkdir_p_sftp(sftp, posixpath.dirname(remote_path))
        sftp.put(str(path), remote_path)


def upload_file(sftp, local_file: Path, remote_file: str) -> None:
    mkdir_p_sftp(sftp, posixpath.dirname(remote_file))
    sftp.put(str(local_file), remote_file)


def upload_remote_runner_sources(sftp, build_root: str, *, include_untracked: bool = False) -> None:
    upload_tree(
        sftp,
        REPO_ROOT / "apps" / "remote_runner",
        posixpath.join(build_root, "bundle", "remote_runner"),
        include_untracked=include_untracked,
    )
    upload_file(
        sftp,
        REPO_ROOT / "core" / "__init__.py",
        posixpath.join(build_root, "bundle", "core", "__init__.py"),
    )
    for filename in CORE_RUNTIME_HELPER_FILES:
        upload_file(
            sftp,
            REPO_ROOT / "core" / filename,
            posixpath.join(build_root, "bundle", "core", filename),
        )
    upload_tree(
        sftp,
        REPO_ROOT / "core" / "contracts",
        posixpath.join(build_root, "bundle", "core", "contracts"),
        include_untracked=include_untracked,
    )


def validate_explicit_lock(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"explicit lock file not found: {path}")
    first_line = path.read_text(encoding="utf-8").splitlines()[0:1]
    if first_line != ["@EXPLICIT"]:
        raise SystemExit(f"explicit lock file must start with @EXPLICIT: {path}")


def default_lock_file(*, platform: str) -> Path:
    relative = REMOTE_RUNNER_ARTIFACT.conda_explicit_specs.get(platform)
    if not relative:
        raise SystemExit(f"remote runner manifest has no explicit conda spec for platform: {platform}")
    return REPO_ROOT / relative


def build_runtime_script(*, platform: str, runtime_source: str) -> str:
    micromamba_target = micromamba_platform(platform)
    if runtime_source == "lockfile":
        return f"""
test -f explicit.txt
curl -fsSL https://micro.mamba.pm/api/micromamba/{micromamba_target}/latest -o micromamba.tar.bz2
mkdir -p micromamba bundle/runtime
tar -xjf micromamba.tar.bz2 -C micromamba
MAMBA_ROOT_PREFIX="$BUILD_ROOT/mamba-root" ./micromamba/bin/micromamba create -y -p "$BUILD_ROOT/runtime-src" --file explicit.txt
"""
    if runtime_source == "clean-solve":
        return f"""
curl -fsSL https://micro.mamba.pm/api/micromamba/{micromamba_target}/latest -o micromamba.tar.bz2
mkdir -p micromamba bundle/runtime
tar -xjf micromamba.tar.bz2 -C micromamba
MAMBA_ROOT_PREFIX="$BUILD_ROOT/mamba-root" ./micromamba/bin/micromamba create -y -p "$BUILD_ROOT/runtime-src" -c conda-forge \\
  "python>=3.12,<3.13" "fastapi>=0.115.0" "uvicorn>=0.34.0" "pydantic>=2.10.0" "conda-pack>=0.8.0"
"""
    if runtime_source == "explicit-from-current":
        return f"""
SRC="$HOME/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}/runtime"
test -d "$SRC/conda-meta"
python3 - <<'PY'
import json
from pathlib import Path
src = Path.home() / ".h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}/runtime/conda-meta"
urls = []
for path in sorted(src.glob("*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    url = data.get("url")
    if not url:
        channel = str(data.get("channel") or "").rstrip("/")
        subdir = str(data.get("subdir") or "linux-64")
        filename = data.get("fn")
        if channel and filename:
            url = f"{{channel}}/{{subdir}}/{{filename}}"
    if url:
        urls.append(url)
if not urls:
    raise SystemExit("no explicit package URLs found in current remote runner runtime")
Path("explicit.txt").write_text("@EXPLICIT\\n" + "\\n".join(urls) + "\\n", encoding="utf-8")
PY
curl -fsSL https://micro.mamba.pm/api/micromamba/{micromamba_target}/latest -o micromamba.tar.bz2
mkdir -p micromamba bundle/runtime
tar -xjf micromamba.tar.bz2 -C micromamba
MAMBA_ROOT_PREFIX="$BUILD_ROOT/mamba-root" ./micromamba/bin/micromamba create -y -p "$BUILD_ROOT/runtime-src" --file explicit.txt
"""
    if runtime_source == "copy-from-current":
        return f"""
SRC="$HOME/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION}/runtime"
test -x "$SRC/bin/python"
test -x "$SRC/bin/conda-unpack"
mkdir -p bundle
cp -a "$SRC" bundle/runtime
"""
    raise RuntimeError(f"unsupported runtime source: {runtime_source}")


def build_remote_script(
    *,
    version: str,
    platform: str,
    runtime_source: str,
    artifact_name: str,
    lock_file_name: str,
    lock_sha256: str,
) -> str:
    if runtime_source == "copy-from-current":
        runtime_validation = '"$BUILD_ROOT/bundle/runtime/bin/python" -c "import fastapi, uvicorn, pydantic"'
        runtime_pack = ""
    else:
        runtime_validation = '"$BUILD_ROOT/runtime-src/bin/python" -c "import fastapi, uvicorn, pydantic"'
        runtime_pack = (
            '"$BUILD_ROOT/runtime-src/bin/conda-pack" -p "$BUILD_ROOT/runtime-src" '
            '-o "$BUILD_ROOT/runtime.tar.gz" --force\n'
            'tar -xzf "$BUILD_ROOT/runtime.tar.gz" -C "$BUILD_ROOT/bundle/runtime"'
        )
    manifest = {
        "service": REMOTE_RUNNER_ARTIFACT.service,
        "version": version,
        "platform": platform,
        "runtime": {
            "provider": "bundled",
            "python": "runtime/bin/python",
        },
        "build": {
            "runtimeSource": runtime_source,
            "lockFile": lock_file_name if runtime_source == "lockfile" else "",
            "lockSha256": lock_sha256 if runtime_source == "lockfile" else "",
        },
    }
    return f"""
set -euo pipefail
cd "$BUILD_ROOT"
{build_runtime_script(platform=platform, runtime_source=runtime_source)}
{runtime_validation}
{runtime_pack}
python3 - <<'PY'
import json
from pathlib import Path
payload = json.loads({json.dumps(manifest, sort_keys=True)!r})
Path("bundle/bootstrap_manifest.json").write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
PY
cat > "$BUILD_ROOT/bundle/start_service.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH="${{1:?config path required}}"
LOG_PATH="${{2:?log path required}}"
RUN_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$RUN_DIR"
export H2OMETA_REMOTE_CONFIG="$CONFIG_PATH"
nohup "$RUN_DIR/launch_remote_runner.sh" >>"$LOG_PATH" 2>&1 &
echo $! > "$RUN_DIR/runner.pid"
SH
cat > "$BUILD_ROOT/bundle/launch_remote_runner.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$RUN_DIR"
RUNNER_PYTHON="${{H2OMETA_REMOTE_RUNNER_PYTHON:-}}"
if [ -n "${{H2OMETA_REMOTE_CONFIG:-}}" ]; then
  SHARED_ROOT="$(cd "$(dirname "$H2OMETA_REMOTE_CONFIG")/.." && pwd)"
  TOOLS_BIN="$SHARED_ROOT/tools/bin"
  if [ -d "$TOOLS_BIN" ]; then
    export PATH="$TOOLS_BIN:$PATH"
  fi
  if [ -z "$RUNNER_PYTHON" ] && [ -f "$H2OMETA_REMOTE_CONFIG" ]; then
    RUNNER_PYTHON="$(sed -n 's/.*\\"runner_python\\"[[:space:]]*:[[:space:]]*\\"\\([^\\"]*\\)\\".*/\\1/p' "$H2OMETA_REMOTE_CONFIG" | head -n 1)"
  fi
fi
if [ -z "$RUNNER_PYTHON" ]; then
  RUNNER_PYTHON="$RUN_DIR/runtime/bin/python"
fi
if [ -x "$RUN_DIR/runtime/bin/conda-unpack" ] && [ ! -f "$RUN_DIR/runtime/.h2ometa-conda-unpacked" ]; then
  "$RUN_DIR/runtime/bin/python" "$RUN_DIR/runtime/bin/conda-unpack"
  touch "$RUN_DIR/runtime/.h2ometa-conda-unpacked"
fi
exec "$RUNNER_PYTHON" -m remote_runner.run
SH
cat > "$BUILD_ROOT/bundle/check_service.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$RUN_DIR/runner.pid" ] && kill -0 "$(cat "$RUN_DIR/runner.pid")" >/dev/null 2>&1; then
  echo "running"
else
  echo "stopped"
  exit 1
fi
SH
cat > "$BUILD_ROOT/bundle/stop_service.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
RUN_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$RUN_DIR/runner.pid"
if [ ! -f "$PID_FILE" ]; then
  echo "stopped"
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" >/dev/null 2>&1; then
  kill "$PID"
  i=0
  while [ "$i" -lt 10 ]; do
    if ! kill -0 "$PID" >/dev/null 2>&1; then
      break
    fi
    sleep 1
    i=$((i + 1))
  done
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill -9 "$PID"
  fi
fi
rm -f "$PID_FILE"
echo "stopped"
SH
cat > "$BUILD_ROOT/bundle/run_workflow.sh" <<'SH'
#!/usr/bin/env bash
echo "workflow execution is not enabled in phase 1" >&2
exit 1
SH
cat > "$BUILD_ROOT/bundle/h2ometa-remote.service" <<'SERVICE'
[Unit]
Description=H2OMeta Remote Runner
After=default.target

[Service]
Type=simple
WorkingDirectory=%h/.h2ometa/runner/current
Environment=H2OMETA_REMOTE_CONFIG=%h/.h2ometa/runner/shared/config/runner.json
ExecStart=%h/.h2ometa/runner/current/launch_remote_runner.sh
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
SERVICE
chmod 755 "$BUILD_ROOT/bundle"/*.sh
test -x "$BUILD_ROOT/bundle/runtime/bin/python"
tar -czf {shlex.quote(artifact_name)} -C "$BUILD_ROOT/bundle" .
printf "%s\\n" "$BUILD_ROOT/{artifact_name}"
"""


def build_remote_script_plan(
    *,
    version: str,
    platform: str,
    runtime_source: str,
    lock_file_name: str = "",
    lock_sha256: str = "",
) -> dict[str, str]:
    artifact_name = f"{REMOTE_RUNNER_ARTIFACT.name}-{version}-{platform}.tar.gz"
    return {
        "artifactName": artifact_name,
        "version": version,
        "platform": platform,
        "runtimeSource": runtime_source,
        "remoteScript": build_remote_script(
            version=version,
            platform=platform,
            runtime_source=runtime_source,
            artifact_name=artifact_name,
            lock_file_name=lock_file_name,
            lock_sha256=lock_sha256,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and download the remote-runner control-plane artifact.")
    parser.add_argument("--version", default=REMOTE_RUNNER_VERSION)
    parser.add_argument("--platform", default="", choices=("", "linux-64", "linux-aarch64"))
    parser.add_argument("--output-dir", default=str(Path("resources") / "remote-runner"))
    parser.add_argument(
        "--runtime-source",
        choices=("lockfile", "clean-solve", "explicit-from-current", "copy-from-current"),
        default="lockfile",
        help=(
            "lockfile builds from a checked-in explicit spec. clean-solve is a dev-only "
            "refresh path. explicit-from-current exports package URLs from the currently "
            "installed remote runner runtime and rebuilds a fresh env from that lock-like spec. "
            "copy-from-current reuses the currently installed remote runner runtime for staging."
        ),
    )
    parser.add_argument(
        "--lock-file",
        default="",
        help="Explicit conda spec used when --runtime-source=lockfile. Defaults to resources/remote-runner/locks.",
    )
    parser.add_argument(
        "--print-remote-script",
        action="store_true",
        help="Print the generated remote build script and exit without reading SSH config or connecting.",
    )
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="Allow building from a dirty apps/remote_runner tree. Intended for development only.",
    )
    args = parser.parse_args()

    requested_platform = args.platform or REMOTE_RUNNER_ARTIFACT.default_platform
    lock_file = Path(args.lock_file) if args.lock_file else default_lock_file(platform=requested_platform)
    lock_file_name = lock_file.name if args.runtime_source == "lockfile" else ""
    lock_sha256 = sha256_text(lock_file) if args.runtime_source == "lockfile" else ""
    if args.runtime_source == "lockfile":
        validate_explicit_lock(lock_file)
    if args.print_remote_script:
        print_json(
            "REMOTE_RUNNER_REMOTE_SCRIPT",
            build_remote_script_plan(
                version=args.version,
                platform=requested_platform,
                runtime_source=args.runtime_source,
                lock_file_name=lock_file_name,
                lock_sha256=lock_sha256,
            ),
        )
        return 0

    source_status = git_status_for_paths(remote_runner_release_source_paths())
    if source_status and not args.allow_dirty_source:
        raise SystemExit(
            "remote runner release sources have uncommitted changes; commit or stash before release build, "
            "or pass --allow-dirty-source for a development-only build"
        )

    client = connect()
    build_root = ""
    try:
        uname = run(client, 'printf "%s:%s" "$(uname -s)" "$(uname -m)"', timeout=30).strip()
        detected_platform = platform_from_uname(uname)
        platform = args.platform or detected_platform
        if platform != detected_platform:
            raise RuntimeError(f"requested platform {platform} does not match remote platform {detected_platform}")

        build_root = run(client, "mktemp -d /tmp/h2ometa-remote-runner.XXXXXX", timeout=30).strip()
        sftp = client.open_sftp()
        try:
            upload_remote_runner_sources(sftp, build_root, include_untracked=args.allow_dirty_source)
            if args.runtime_source == "lockfile":
                sftp.put(str(lock_file), posixpath.join(build_root, "explicit.txt"))
        finally:
            sftp.close()

        plan = build_remote_script_plan(
            version=args.version,
            platform=platform,
            runtime_source=args.runtime_source,
            lock_file_name=lock_file_name,
            lock_sha256=lock_sha256,
        )
        artifact_name = plan["artifactName"]
        remote_command = f"BUILD_ROOT={shlex.quote(build_root)} bash -lc {shlex.quote(plan['remoteScript'])}"
        output = run(client, remote_command, timeout=3600)
        remote_artifact = output.strip().splitlines()[-1].strip()
        if not remote_artifact.endswith(artifact_name):
            raise RuntimeError(f"remote build did not report expected artifact path: {remote_artifact}")

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        local_artifact = output_dir / artifact_name
        sftp = client.open_sftp()
        try:
            digest = download_artifact_atomically(sftp, remote_artifact, local_artifact)
        finally:
            sftp.close()
    finally:
        if build_root:
            try:
                run(client, f"rm -rf {shlex.quote(build_root)}", timeout=60)
            except Exception as exc:
                print_json("REMOTE_CLEANUP_WARNING", {"buildRoot": build_root, "error": str(exc)})
        client.close()

    print_json(
        "REMOTE_RUNNER_ARTIFACT",
        {
            "path": str(local_artifact),
            "sha256": str(Path(str(local_artifact) + ".sha256")),
            "digest": digest,
            "runtimeSource": args.runtime_source,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
