from __future__ import annotations

import json
import shutil
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
