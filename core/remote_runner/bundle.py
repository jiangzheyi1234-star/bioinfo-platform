from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.remote_runner.layout import REMOTE_RUNNER_RELATIVE_ROOT
from core.remote_runner.release_manifest import REMOTE_RUNNER_ARTIFACT, REMOTE_RUNNER_VERSION


@dataclass
class BuiltBootstrapBundle:
    version: str
    platform: str
    bundle_dir: Path
    archive_path: Path


class RemoteRunnerBundleBuilder:
    def build(
        self,
        version: str = REMOTE_RUNNER_VERSION,
        *,
        platform: str = "linux-64",
        runtime_dir: Path,
    ) -> BuiltBootstrapBundle:
        if not runtime_dir.exists():
            raise FileNotFoundError(f"remote runner runtime directory not found: {runtime_dir}")
        runtime_python = runtime_dir / "bin" / "python"
        if not runtime_python.exists():
            raise FileNotFoundError(f"remote runner runtime python not found: {runtime_python}")

        root = Path(tempfile.mkdtemp(prefix="h2ometa-remote-bundle-"))
        bundle_dir = root / "bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)

        source_pkg = Path(__file__).resolve().parents[2] / "apps" / "remote_runner"
        shutil.copytree(
            source_pkg,
            bundle_dir / "remote_runner",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        shutil.copytree(runtime_dir, bundle_dir / "runtime", symlinks=True)

        manifest = {
            "service": REMOTE_RUNNER_ARTIFACT.service,
            "version": version,
            "platform": platform,
            "runtime": {
                "provider": "bundled",
                "python": "runtime/bin/python",
            },
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
            '  RUNNER_PYTHON="$RUN_DIR/runtime/bin/python"\n'
            "fi\n"
            'if [ -x "$RUN_DIR/runtime/bin/conda-unpack" ] && [ ! -f "$RUN_DIR/runtime/.h2ometa-conda-unpacked" ]; then\n'
            '  "$RUN_DIR/runtime/bin/python" "$RUN_DIR/runtime/bin/conda-unpack"\n'
            '  touch "$RUN_DIR/runtime/.h2ometa-conda-unpacked"\n'
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
            bundle_dir / "stop_service.sh",
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'RUN_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
            'PID_FILE="$RUN_DIR/runner.pid"\n'
            'if [ ! -f "$PID_FILE" ]; then\n'
            '  echo "stopped"\n'
            "  exit 0\n"
            "fi\n"
            'PID="$(cat "$PID_FILE")"\n'
            'if kill -0 "$PID" >/dev/null 2>&1; then\n'
            '  kill "$PID"\n'
            "  i=0\n"
            '  while [ "$i" -lt 10 ]; do\n'
            '    if ! kill -0 "$PID" >/dev/null 2>&1; then\n'
            "      break\n"
            "    fi\n"
            "    sleep 1\n"
            '    i=$((i + 1))\n'
            "  done\n"
            '  if kill -0 "$PID" >/dev/null 2>&1; then\n'
            '    kill -9 "$PID"\n'
            "  fi\n"
            "fi\n"
            'rm -f "$PID_FILE"\n'
            'echo "stopped"\n',
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
            f"WorkingDirectory=%h/{REMOTE_RUNNER_RELATIVE_ROOT}/current\n"
            f"Environment=H2OMETA_REMOTE_CONFIG=%h/{REMOTE_RUNNER_RELATIVE_ROOT}/shared/config/runner.json\n"
            f"ExecStart=%h/{REMOTE_RUNNER_RELATIVE_ROOT}/current/launch_remote_runner.sh\n"
            "Restart=on-failure\n"
            "RestartSec=2\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
        )

        for path in bundle_dir.glob("*.sh"):
            path.chmod(0o755)

        archive_path = root / f"{REMOTE_RUNNER_ARTIFACT.name}-{version}-{platform}.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(bundle_dir, arcname=".")

        return BuiltBootstrapBundle(version=version, platform=platform, bundle_dir=bundle_dir, archive_path=archive_path)

    @staticmethod
    def _write_text_lf(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8", newline="\n")
