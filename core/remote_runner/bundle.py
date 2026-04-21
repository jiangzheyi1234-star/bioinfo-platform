from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path


REMOTE_RUNNER_VERSION = "0.1.0-control-plane"
REMOTE_RUNNER_PORT = 8876


@dataclass
class BuiltBootstrapBundle:
    version: str
    bundle_dir: Path
    archive_path: Path


@dataclass
class BuiltRunnerRuntimeArtifact:
    fingerprint: str
    archive_path: Path
    python_relative_path: str = "runner-env/bin/python"


class LocalRunnerRuntimePackager:
    def __init__(
        self,
        *,
        requirements_path: Path | None = None,
        cache_root: Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self._requirements_path = requirements_path or repo_root / "apps" / "remote_runner" / "requirements.txt"
        self._cache_root = cache_root or (repo_root / ".omx" / "runner-runtime-cache")
        self._python_executable = python_executable or sys.executable

    def build(self, target_platform: str = "") -> BuiltRunnerRuntimeArtifact:
        self._cache_root.mkdir(parents=True, exist_ok=True)
        fingerprint = self._compute_fingerprint(target_platform=target_platform)
        archive_path = self._cache_root / f"runner-runtime-{fingerprint}.tar.gz"
        if archive_path.exists():
            return BuiltRunnerRuntimeArtifact(fingerprint=fingerprint, archive_path=archive_path)
        if platform.system() == "Windows" and target_platform.startswith("linux"):
            return self._build_in_wsl(fingerprint=fingerprint, archive_path=archive_path)

        with tempfile.TemporaryDirectory(prefix=f"runner-runtime-{fingerprint}-") as tmp:
            tmp_path = Path(tmp)
            env_root = tmp_path / "runner-env"
            self._run_local([self._python_executable, "-m", "venv", str(env_root)], step="create local runner env")
            env_python = env_root / "bin" / "python"
            self._run_local(
                [str(env_python), "-m", "pip", "install", "--upgrade", "pip"],
                step="upgrade pip in local runner env",
            )
            self._run_local(
                [str(env_python), "-m", "pip", "install", "-r", str(self._requirements_path)],
                step="install runner runtime requirements",
            )
            tmp_archive = archive_path.with_suffix(".tmp")
            if tmp_archive.exists():
                tmp_archive.unlink()
            with tarfile.open(tmp_archive, "w:gz") as archive:
                archive.add(env_root, arcname="runner-env")
            tmp_archive.replace(archive_path)

        return BuiltRunnerRuntimeArtifact(fingerprint=fingerprint, archive_path=archive_path)

    def _compute_fingerprint(self, *, target_platform: str) -> str:
        hasher = hashlib.sha256()
        hasher.update(self._requirements_path.read_bytes())
        hasher.update(self._python_executable.encode("utf-8"))
        hasher.update(platform.system().encode("utf-8"))
        hasher.update(platform.machine().encode("utf-8"))
        hasher.update(target_platform.encode("utf-8"))
        version = subprocess.run(
            [self._python_executable, "-c", "import sys; print(sys.version)"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        hasher.update(version.encode("utf-8"))
        return hasher.hexdigest()[:16]

    def _build_in_wsl(self, *, fingerprint: str, archive_path: Path) -> BuiltRunnerRuntimeArtifact:
        requirements_wsl = self._to_wsl_path(self._requirements_path)
        cache_wsl = self._to_wsl_path(self._cache_root)
        script_contents = f"""#!/usr/bin/env bash
set -euo pipefail
REQ={requirements_wsl!r}
CACHE={cache_wsl!r}
ARCHIVE="$CACHE/runner-runtime-{fingerprint}.tar.gz"
if [ -f "$ARCHIVE" ]; then
  exit 0
fi
mkdir -p "$CACHE"
TMPDIR="$(mktemp -d)"
cleanup() {{
  rm -rf "$TMPDIR"
}}
trap cleanup EXIT
python3 -m venv "$TMPDIR/runner-env"
"$TMPDIR/runner-env/bin/python" -m pip install --upgrade pip
"$TMPDIR/runner-env/bin/python" -m pip install -r "$REQ"
tar -czf "$ARCHIVE.tmp" -C "$TMPDIR" runner-env
mv "$ARCHIVE.tmp" "$ARCHIVE"
"""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sh", dir=self._cache_root, encoding="utf-8", newline="\n") as handle:
            handle.write(script_contents)
            script_path = Path(handle.name)
        try:
            script_wsl = self._to_wsl_path(script_path)
            completed = subprocess.run(
                ["wsl.exe", "bash", script_wsl],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "build runner runtime artifact in WSL failed").strip()
                raise RuntimeError(f"build runner runtime artifact in WSL: {detail}")
            return BuiltRunnerRuntimeArtifact(fingerprint=fingerprint, archive_path=archive_path)
        finally:
            script_path.unlink(missing_ok=True)

    @staticmethod
    def _run_local(cmd: list[str], *, step: str) -> None:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or step).strip()
            raise RuntimeError(f"{step}: {detail}")

    @staticmethod
    def _to_wsl_path(path: Path) -> str:
        raw = str(path)
        if len(raw) >= 3 and raw[1:3] == ":\\":
            drive = raw[0].lower()
            suffix = raw[3:].replace("\\", "/")
            return f"/mnt/{drive}/{suffix}"
        completed = subprocess.run(
            ["wsl.exe", "wslpath", "-a", str(path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "wslpath failed").strip()
            raise RuntimeError(f"resolve WSL path: {detail}")
        return completed.stdout.strip()


class RemoteRunnerBundleBuilder:
    def build(self, version: str = REMOTE_RUNNER_VERSION) -> BuiltBootstrapBundle:
        root = Path(tempfile.mkdtemp(prefix="h2ometa-remote-bundle-"))
        bundle_dir = root / "bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        source_pkg = Path(__file__).resolve().parents[2] / "apps" / "remote_runner"
        shutil.copytree(source_pkg, bundle_dir / "remote_runner")

        manifest = {
            "service": "h2ometa-remote",
            "version": version,
            "port": REMOTE_RUNNER_PORT,
        }
        self._write_text_lf(bundle_dir / "bootstrap_manifest.json", json.dumps(manifest, indent=2))
        self._write_text_lf(
            bundle_dir / "start_service.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'CONFIG_PATH="${1:?config path required}"\n'
            'LOG_PATH="${2:?log path required}"\n'
            'RUN_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'cd "$RUN_DIR"\n'
            'export H2OMETA_REMOTE_CONFIG="$CONFIG_PATH"\n'
            'nohup "$RUN_DIR/launch_remote_runner.sh" >>"$LOG_PATH" 2>&1 &\n'
            'echo $! > "$RUN_DIR/runner.pid"\n',
        )
        self._write_text_lf(
            bundle_dir / "launch_remote_runner.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'RUN_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'cd "$RUN_DIR"\n'
            'RUNNER_PYTHON="${H2OMETA_REMOTE_RUNNER_PYTHON:-}"\n'
            'if [ -n "${H2OMETA_REMOTE_CONFIG:-}" ]; then\n'
            '  SHARED_ROOT="$(cd "$(dirname "$H2OMETA_REMOTE_CONFIG")/.." && pwd)"\n'
            '  TOOLS_BIN="$SHARED_ROOT/tools/bin"\n'
            '  if [ -d "$TOOLS_BIN" ]; then\n'
            '    export PATH="$TOOLS_BIN:$PATH"\n'
            "  fi\n"
            '  if [ -z "$RUNNER_PYTHON" ] && [ -f "$H2OMETA_REMOTE_CONFIG" ]; then\n'
            "    RUNNER_PYTHON=\"$(sed -n 's/.*\\\"runner_python\\\"[[:space:]]*:[[:space:]]*\\\"\\([^\\\"]*\\)\\\".*/\\1/p' \"$H2OMETA_REMOTE_CONFIG\" | head -n 1)\"\n"
            "  fi\n"
            "fi\n"
            'if [ -z "$RUNNER_PYTHON" ]; then\n'
            '  RUNNER_PYTHON="$RUN_DIR/.venv/bin/python"\n'
            "fi\n"
            'exec "$RUNNER_PYTHON" -m remote_runner.run\n',
        )
        self._write_text_lf(
            bundle_dir / "check_service.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'RUN_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'if [ -f "$RUN_DIR/runner.pid" ] && kill -0 "$(cat "$RUN_DIR/runner.pid")" >/dev/null 2>&1; then\n'
            '  echo "running"\n'
            "else\n"
            '  echo "stopped"\n'
            "  exit 1\n"
            "fi\n",
        )
        self._write_text_lf(
            bundle_dir / "run_workflow.sh",
            "#!/usr/bin/env bash\n"
            'echo "workflow execution is not enabled in phase 1" >&2\n'
            "exit 1\n",
        )
        self._write_text_lf(
            bundle_dir / "h2ometa-remote.service",
            "[Unit]\n"
            "Description=H2OMeta Remote Runner\n"
            "After=default.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "WorkingDirectory=%h/.h2ometa/runner/current\n"
            "Environment=H2OMETA_REMOTE_CONFIG=%h/.h2ometa/runner/shared/config/runner.json\n"
            "ExecStart=%h/.h2ometa/runner/current/launch_remote_runner.sh\n"
            "Restart=on-failure\n"
            "RestartSec=2\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
        )

        for path in bundle_dir.glob("*.sh"):
            path.chmod(0o755)

        archive_path = root / f"h2ometa-remote-{version}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(bundle_dir, arcname=".")

        return BuiltBootstrapBundle(version=version, bundle_dir=bundle_dir, archive_path=archive_path)

    @staticmethod
    def _write_text_lf(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8", newline="\n")
