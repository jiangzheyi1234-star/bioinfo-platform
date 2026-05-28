#!/usr/bin/env python3
"""Build the Linux workflow-runtime artifact on the configured SSH server."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import shlex
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.release_manifest import WORKFLOW_RUNTIME_ARTIFACT, WORKFLOW_RUNTIME_VERSION  # noqa: E402


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
            "exit_code": exit_code,
            "command": command[:220],
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
    raise RuntimeError(f"unsupported workflow runtime build platform: {normalized}")


def micromamba_platform(platform: str) -> str:
    if platform in {"linux-64", "linux-aarch64"}:
        return platform
    raise RuntimeError(f"unsupported workflow runtime build platform: {platform}")


def validate_explicit_lock(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"explicit lock file not found: {path}")
    first_line = path.read_text(encoding="utf-8").splitlines()[0:1]
    if first_line != ["@EXPLICIT"]:
        raise SystemExit(f"explicit lock file must start with @EXPLICIT: {path}")


def default_lock_file(*, platform: str) -> Path:
    relative = WORKFLOW_RUNTIME_ARTIFACT.conda_explicit_specs.get(platform)
    if not relative:
        raise SystemExit(f"workflow runtime manifest has no explicit conda spec for platform: {platform}")
    return REPO_ROOT / relative


def build_environment_script(*, platform: str, runtime_source: str, snakemake_version: str) -> str:
    package_spec = f"snakemake={snakemake_version}" if snakemake_version else "snakemake>=9,<10"
    micromamba_target = micromamba_platform(platform)
    if runtime_source == "lockfile":
        return f"""
test -f explicit.txt
curl -fsSL https://micro.mamba.pm/api/micromamba/{micromamba_target}/latest -o micromamba.tar.bz2
mkdir -p micromamba bundle/workflow-env
tar -xjf micromamba.tar.bz2 -C micromamba
MAMBA_ROOT_PREFIX="$BUILD_ROOT/mamba-root" ./micromamba/bin/micromamba create -y -p "$BUILD_ROOT/workflow-env-src" --file explicit.txt
"""
    if runtime_source == "clean-solve":
        return f"""
curl -fsSL https://micro.mamba.pm/api/micromamba/{micromamba_target}/latest -o micromamba.tar.bz2
mkdir -p micromamba bundle/workflow-env
tar -xjf micromamba.tar.bz2 -C micromamba
MAMBA_ROOT_PREFIX="$BUILD_ROOT/mamba-root" ./micromamba/bin/micromamba create -y -p "$BUILD_ROOT/workflow-env-src" -c conda-forge -c bioconda \\
  "python>=3.12,<3.13" "conda>=24" "conda-pack>=0.8.0" {shlex.quote(package_spec)}
"""
    raise RuntimeError(f"unsupported runtime source: {runtime_source}")


def build_remote_script(
    *,
    version: str,
    platform: str,
    snakemake_version: str,
    artifact_name: str,
    runtime_source: str,
    lock_file_name: str,
    lock_sha256: str,
) -> str:
    manifest = {
        "service": WORKFLOW_RUNTIME_ARTIFACT.service,
        "version": version,
        "platform": platform,
        "provider": "conda-pack",
        "entrypoints": {
            "python": "workflow-env/bin/python",
            "conda": "workflow-env/bin/conda",
            "condaUnpack": "workflow-env/bin/conda-unpack",
            "snakemake": "workflow-env/bin/snakemake",
        },
        "packages": {"snakemake": snakemake_version},
        "build": {
            "runtimeSource": runtime_source,
            "lockFile": lock_file_name if runtime_source == "lockfile" else "",
            "lockSha256": lock_sha256 if runtime_source == "lockfile" else "",
        },
    }
    return f"""
set -euo pipefail
BUILD_ROOT="$(mktemp -d /tmp/h2ometa-workflow-runtime.XXXXXX)"
cd "$BUILD_ROOT"
{build_environment_script(platform=platform, runtime_source=runtime_source, snakemake_version=snakemake_version)}
"$BUILD_ROOT/workflow-env-src/bin/python" -c "import snakemake"
SNAKEMAKE_VERSION="$("$BUILD_ROOT/workflow-env-src/bin/snakemake" --version | head -n 1)"
"$BUILD_ROOT/workflow-env-src/bin/conda-pack" -p "$BUILD_ROOT/workflow-env-src" -o "$BUILD_ROOT/workflow-env.tar.gz" --force
tar -xzf "$BUILD_ROOT/workflow-env.tar.gz" -C "$BUILD_ROOT/bundle/workflow-env"
test -x "$BUILD_ROOT/bundle/workflow-env/bin/python"
test -x "$BUILD_ROOT/bundle/workflow-env/bin/conda"
test -x "$BUILD_ROOT/bundle/workflow-env/bin/conda-unpack"
test -x "$BUILD_ROOT/bundle/workflow-env/bin/snakemake"
find "$BUILD_ROOT/bundle/workflow-env/lib" -path '*/site-packages/snakemake/__init__.py' -type f | grep -q .
printf "%s\\n" "$SNAKEMAKE_VERSION" > snakemake.version
"$BUILD_ROOT/workflow-env-src/bin/python" - <<'PY'
import json
from pathlib import Path
payload = json.loads({json.dumps(manifest, sort_keys=True)!r})
if not payload["packages"]["snakemake"]:
    payload["packages"]["snakemake"] = Path("snakemake.version").read_text(encoding="utf-8").strip()
path = Path("bundle/bootstrap_manifest.json")
path.write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
PY
tar -czf {shlex.quote(artifact_name)} -C "$BUILD_ROOT/bundle" .
printf "%s\\n" "$BUILD_ROOT/{artifact_name}"
"""


def build_remote_script_plan(
    *,
    version: str,
    platform: str,
    snakemake_version: str,
    runtime_source: str,
    lock_file_name: str = "",
    lock_sha256: str = "",
) -> dict[str, str]:
    artifact_name = f"{WORKFLOW_RUNTIME_ARTIFACT.name}-{version}-{platform}.tar.gz"
    return {
        "artifactName": artifact_name,
        "version": version,
        "platform": platform,
        "remoteScript": build_remote_script(
            version=version,
            platform=platform,
            snakemake_version=snakemake_version,
            artifact_name=artifact_name,
            runtime_source=runtime_source,
            lock_file_name=lock_file_name,
            lock_sha256=lock_sha256,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and download the managed Snakemake workflow runtime artifact.")
    parser.add_argument("--version", default=WORKFLOW_RUNTIME_VERSION)
    parser.add_argument("--platform", default="", choices=("", "linux-64", "linux-aarch64"))
    parser.add_argument(
        "--snakemake-version",
        default="",
        help="Exact Snakemake version for --runtime-source=clean-solve. Lockfile builds record the locked version.",
    )
    parser.add_argument(
        "--runtime-source",
        choices=("lockfile", "clean-solve"),
        default="lockfile",
        help="lockfile builds from a checked-in explicit spec. clean-solve is a dev-only refresh path.",
    )
    parser.add_argument(
        "--lock-file",
        default="",
        help="Explicit conda spec used when --runtime-source=lockfile. Defaults to resources/remote-runner/locks.",
    )
    parser.add_argument("--output-dir", default=str(Path("resources") / "remote-runner"))
    parser.add_argument(
        "--print-remote-script",
        action="store_true",
        help="Print the generated remote build script and exit without reading SSH config or connecting.",
    )
    args = parser.parse_args()
    requested_platform = args.platform or WORKFLOW_RUNTIME_ARTIFACT.default_platform
    lock_file = Path(args.lock_file) if args.lock_file else default_lock_file(platform=requested_platform)
    lock_file_name = lock_file.name if args.runtime_source == "lockfile" else ""
    lock_sha256 = sha256_text(lock_file) if args.runtime_source == "lockfile" else ""
    if args.runtime_source == "lockfile":
        validate_explicit_lock(lock_file)
    if args.print_remote_script:
        plan = build_remote_script_plan(
            version=args.version,
            platform=requested_platform,
            snakemake_version=str(args.snakemake_version or "").strip(),
            runtime_source=args.runtime_source,
            lock_file_name=lock_file_name,
            lock_sha256=lock_sha256,
        )
        print_json("WORKFLOW_RUNTIME_REMOTE_SCRIPT", plan)
        return 0

    client = connect()
    build_root = ""
    try:
        uname = run(client, 'printf "%s:%s" "$(uname -s)" "$(uname -m)"', timeout=30).strip()
        detected_platform = platform_from_uname(uname)
        platform = args.platform or detected_platform
        if platform != detected_platform:
            raise RuntimeError(f"requested platform {platform} does not match remote platform {detected_platform}")
        plan = build_remote_script_plan(
            version=args.version,
            platform=platform,
            snakemake_version=str(args.snakemake_version or "").strip(),
            runtime_source=args.runtime_source,
            lock_file_name=lock_file_name,
            lock_sha256=lock_sha256,
        )
        artifact_name = plan["artifactName"]
        remote_script = plan["remoteScript"]
        if args.runtime_source == "lockfile":
            build_root = run(client, "mktemp -d /tmp/h2ometa-workflow-runtime.XXXXXX", timeout=30).strip()
            sftp = client.open_sftp()
            try:
                sftp.put(str(lock_file), posixpath.join(build_root, "explicit.txt"))
            finally:
                sftp.close()
            remote_script = remote_script.replace(
                'BUILD_ROOT="$(mktemp -d /tmp/h2ometa-workflow-runtime.XXXXXX)"',
                f"BUILD_ROOT={shlex.quote(build_root)}",
                1,
            )
        output = run(client, f"bash -lc {shlex.quote(remote_script)}", timeout=3600)
        remote_artifact = output.strip().splitlines()[-1].strip()
        if not remote_artifact.endswith(artifact_name):
            raise RuntimeError(f"remote build did not report expected artifact path: {remote_artifact}")
        build_root = posixpath.dirname(remote_artifact)

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
        "WORKFLOW_RUNTIME_ARTIFACT",
        {"path": str(local_artifact), "sha256": str(Path(str(local_artifact) + ".sha256")), "digest": digest},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
