from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .base import EnvironmentInspection, EnvironmentLock


class CondaAdapter:
    name = "conda"

    def __init__(
        self,
        *,
        conda_command: str = "",
        conda_prefix: str = "",
        conda_frontend: str = "mamba",
    ) -> None:
        self._conda_command = str(conda_command or "").strip()
        self._conda_prefix = str(conda_prefix or "").strip()
        self._conda_frontend = str(conda_frontend or "mamba").strip()

    def prepare(
        self,
        *,
        work_dir: str,
        environment_spec: dict[str, Any],
    ) -> EnvironmentLock:
        env_name = str(environment_spec.get("name") or "").strip()
        env_file = str(environment_spec.get("file") or "").strip()
        channels = list(environment_spec.get("channels") or [])
        dependencies = list(environment_spec.get("dependencies") or [])
        if not env_name and not env_file and not dependencies:
            return EnvironmentLock(
                adapter=self.name,
                version=self._detect_version(),
                metadata={"configured": bool(self._conda_command)},
            )
        version = self._detect_version()
        digest_parts = [env_name, env_file, str(sorted(channels)), str(sorted(dependencies))]
        digest = ":".join(p for p in digest_parts if p)
        return EnvironmentLock(
            adapter=self.name,
            version=version,
            digest=digest,
            metadata={
                "name": env_name,
                "file": env_file,
                "channels": channels,
                "dependencies": dependencies,
                "frontend": self._conda_frontend,
            },
        )

    def build_command(
        self,
        command: list[str],
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> list[str]:
        return list(command)

    def build_environment(
        self,
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> dict[str, str]:
        env = dict(os.environ)
        path_entries: list[str] = []
        if self._conda_command:
            path_entries.append(str(Path(self._conda_command).parent))
        if self._conda_command:
            env["CONDA_EXE"] = self._conda_command
        current_path = env.get("PATH", "")
        seen: set[str] = set()
        merged: list[str] = []
        for entry in [*path_entries, *current_path.split(os.pathsep)]:
            if entry and entry not in seen:
                seen.add(entry)
                merged.append(entry)
        env["PATH"] = os.pathsep.join(merged)
        if self._conda_prefix:
            env["MAMBA_ROOT_PREFIX"] = self._conda_prefix
        return env

    def inspect(self) -> EnvironmentInspection:
        if not self._conda_command:
            return EnvironmentInspection(
                ok=False,
                message="Conda command is not configured.",
                adapter=self.name,
            )
        conda_path = Path(self._conda_command)
        if not conda_path.exists():
            return EnvironmentInspection(
                ok=False,
                message=f"Conda command does not exist: {self._conda_command}",
                adapter=self.name,
            )
        if not os.access(conda_path, os.X_OK):
            return EnvironmentInspection(
                ok=False,
                message=f"Conda command is not executable: {self._conda_command}",
                adapter=self.name,
            )
        version = self._detect_version()
        return EnvironmentInspection(
            ok=True,
            message="Conda environment is ready.",
            adapter=self.name,
            version=version,
        )

    def _detect_version(self) -> str:
        if not self._conda_command:
            return ""
        try:
            result = subprocess.run(
                [self._conda_command, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return (result.stdout or result.stderr or "").strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            pass
        return ""
