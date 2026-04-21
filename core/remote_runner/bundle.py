from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
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
        github_repo: str | None = None,
        github_release_tag: str | None = None,
        github_token: str | None = None,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        self._requirements_path = requirements_path or repo_root / "apps" / "remote_runner" / "requirements.txt"
        self._cache_root = cache_root or (repo_root / ".omx" / "runner-runtime-cache")
        self._python_executable = python_executable or sys.executable
        self._github_repo = (github_repo if github_repo is not None else os.getenv("H2OMETA_RUNNER_ARTIFACT_GITHUB_REPO", "")).strip()
        self._github_release_tag = (github_release_tag if github_release_tag is not None else os.getenv("H2OMETA_RUNNER_ARTIFACT_GITHUB_TAG", "latest")).strip() or "latest"
        self._github_token = (github_token if github_token is not None else os.getenv("H2OMETA_RUNNER_ARTIFACT_GITHUB_TOKEN", "")).strip()

    def build(self, target_platform: str = "", version: str = REMOTE_RUNNER_VERSION) -> BuiltRunnerRuntimeArtifact:
        self._cache_root.mkdir(parents=True, exist_ok=True)
        resolved_platform = target_platform or self._local_platform_tag()
        artifact_name = f"runner-runtime-{resolved_platform}-{version}.tar.gz"
        archive_path = self._cache_root / artifact_name
        if archive_path.exists():
            self._verify_cached_artifact(archive_path)
            return BuiltRunnerRuntimeArtifact(
                fingerprint=self._artifact_fingerprint_from_name(artifact_name),
                archive_path=archive_path,
            )
        if target_platform and not self._can_build_target_locally(target_platform):
            return self._download_prebuilt_artifact(artifact_name=artifact_name, archive_path=archive_path)

        fingerprint = self._compute_fingerprint(target_platform=resolved_platform)
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

        return BuiltRunnerRuntimeArtifact(
            fingerprint=self._artifact_fingerprint_from_name(artifact_name),
            archive_path=archive_path,
        )

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

    @staticmethod
    def _run_local(cmd: list[str], *, step: str) -> None:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or step).strip()
            raise RuntimeError(f"{step}: {detail}")

    @staticmethod
    def _can_build_target_locally(target_platform: str) -> bool:
        if not target_platform:
            return True
        local_platform = f"{platform.system().lower()}-{platform.machine().lower()}"
        aliases = {
            "linux-x86_64": "linux-64",
            "linux-amd64": "linux-64",
            "linux-aarch64": "linux-aarch64",
            "linux-arm64": "linux-aarch64",
        }
        return aliases.get(local_platform, local_platform) == target_platform

    def _download_prebuilt_artifact(self, *, artifact_name: str, archive_path: Path) -> BuiltRunnerRuntimeArtifact:
        if not self._github_repo:
            raise RuntimeError(
                "prebuilt runner runtime artifact required for "
                f"{artifact_name}; configure H2OMETA_RUNNER_ARTIFACT_GITHUB_REPO or place the asset in cache"
            )
        release = self._fetch_release_metadata()
        asset_url = self._find_asset_download_url(release, artifact_name)
        checksum_url = self._find_asset_download_url(release, f"{artifact_name}.sha256")
        if not asset_url:
            raise RuntimeError(f"prebuilt runner runtime artifact missing from release: {artifact_name}")
        if not checksum_url:
            raise RuntimeError(f"prebuilt runner runtime checksum missing from release: {artifact_name}.sha256")
        archive_bytes = self._download_bytes(asset_url)
        checksum_text = self._download_bytes(checksum_url).decode("utf-8", errors="replace")
        expected = self._parse_sha256(checksum_text, artifact_name)
        actual = hashlib.sha256(archive_bytes).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"runner runtime artifact checksum mismatch for {artifact_name}: expected {expected}, got {actual}"
            )
        archive_path.write_bytes(archive_bytes)
        self._checksum_path(archive_path).write_text(f"{expected}  {artifact_name}\n", encoding="utf-8")
        return BuiltRunnerRuntimeArtifact(
            fingerprint=self._artifact_fingerprint_from_name(artifact_name),
            archive_path=archive_path,
        )

    def _fetch_release_metadata(self) -> dict:
        endpoint = (
            f"https://api.github.com/repos/{self._github_repo}/releases/latest"
            if self._github_release_tag == "latest"
            else f"https://api.github.com/repos/{self._github_repo}/releases/tags/{self._github_release_tag}"
        )
        payload = self._download_bytes(endpoint, accept="application/vnd.github+json")
        return json.loads(payload.decode("utf-8"))

    @staticmethod
    def _find_asset_download_url(release: dict, asset_name: str) -> str:
        for asset in list(release.get("assets") or []):
            if str(asset.get("name") or "") == asset_name:
                return str(asset.get("browser_download_url") or "").strip()
        return ""

    def _download_bytes(self, url: str, *, accept: str = "application/octet-stream") -> bytes:
        headers = {
            "Accept": accept,
            "User-Agent": "H2OMeta-RunnerArtifactResolver/1.0",
        }
        if self._github_token:
            headers["Authorization"] = f"Bearer {self._github_token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            message = f"github artifact download failed: {exc.code}"
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc.reason) or "github artifact download failed") from exc

    @staticmethod
    def _parse_sha256(checksum_text: str, artifact_name: str) -> str:
        for raw_line in checksum_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) == 1 and len(parts[0]) == 64:
                return parts[0].lower()
            if len(parts) >= 2 and parts[0] and parts[-1].lstrip("*") == artifact_name:
                return parts[0].lower()
        raise RuntimeError(f"invalid sha256 file for {artifact_name}")

    @staticmethod
    def _local_platform_tag() -> str:
        local_platform = f"{platform.system().lower()}-{platform.machine().lower()}"
        aliases = {
            "linux-x86_64": "linux-64",
            "linux-amd64": "linux-64",
            "linux-aarch64": "linux-aarch64",
            "linux-arm64": "linux-aarch64",
        }
        return aliases.get(local_platform, local_platform)

    @staticmethod
    def _verify_cached_artifact(archive_path: Path) -> None:
        checksum_path = LocalRunnerRuntimePackager._checksum_path(archive_path)
        if not checksum_path.exists():
            return
        expected = LocalRunnerRuntimePackager._parse_sha256(checksum_path.read_text(encoding="utf-8"), archive_path.name)
        actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"cached runner runtime artifact checksum mismatch for {archive_path.name}: expected {expected}, got {actual}"
            )

    @staticmethod
    def _checksum_path(archive_path: Path) -> Path:
        return Path(f"{archive_path}.sha256")

    @staticmethod
    def _artifact_fingerprint_from_name(artifact_name: str) -> str:
        return artifact_name.removesuffix(".tar.gz")


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
