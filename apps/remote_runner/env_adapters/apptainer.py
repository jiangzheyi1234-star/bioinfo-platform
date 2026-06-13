from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .base import EnvironmentInspection, EnvironmentLock


class ApptainerAdapter:
    name = "apptainer"

    def __init__(
        self,
        *,
        apptainer_command: str = "apptainer",
        singularity_command: str = "",
    ) -> None:
        self._apptainer_command = str(apptainer_command or "apptainer").strip()
        self._singularity_command = str(singularity_command or "").strip()

    def prepare(
        self,
        *,
        work_dir: str,
        environment_spec: dict[str, Any],
    ) -> EnvironmentLock:
        image = str(environment_spec.get("image") or "").strip()
        image_digest = str(environment_spec.get("digest") or "").strip()
        if not image:
            return EnvironmentLock(
                adapter=self.name,
                version=self._detect_version(),
                metadata={"configured": bool(self._resolved_command())},
            )
        version = self._detect_version()
        return EnvironmentLock(
            adapter=self.name,
            version=version,
            digest=image_digest or image,
            metadata={
                "image": image,
                "digest": image_digest,
                "binds": list(environment_spec.get("binds") or []),
                "nv": bool(environment_spec.get("nv")),
                "writable": bool(environment_spec.get("writable")),
            },
        )

    def build_command(
        self,
        command: list[str],
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> list[str]:
        image = ""
        binds: list[str] = []
        nv = False
        writable = False
        if environment_lock is not None:
            image = str(environment_lock.metadata.get("image") or "").strip()
            binds = [
                str(bind).strip()
                for bind in environment_lock.metadata.get("binds") or []
                if str(bind).strip()
            ]
            nv = bool(environment_lock.metadata.get("nv"))
            writable = bool(environment_lock.metadata.get("writable"))
        if not image:
            return list(command)
        exec_args = [self._execution_command(), "exec"]
        if nv:
            exec_args.append("--nv")
        if writable:
            exec_args.append("--writable")
        exec_args.extend(["--pwd", work_dir])
        for bind in binds:
            exec_args.extend(["--bind", bind])
        if work_dir:
            exec_args.extend(["--bind", f"{work_dir}:{work_dir}"])
        exec_args.append(image)
        exec_args.extend(command)
        return exec_args

    def _execution_command(self) -> str:
        return self._resolved_command() or self._apptainer_command or self._singularity_command

    def build_environment(
        self,
        *,
        work_dir: str,
        environment_lock: EnvironmentLock | None = None,
    ) -> dict[str, str]:
        return dict(os.environ)

    def inspect(self) -> EnvironmentInspection:
        resolved = self._resolved_command()
        if not resolved:
            return EnvironmentInspection(
                ok=False,
                message="Neither apptainer nor singularity command is available.",
                adapter=self.name,
                supported=False,
            )
        version = self._detect_version()
        return EnvironmentInspection(
            ok=True,
            message=f"Apptainer environment is ready ({resolved}).",
            adapter=self.name,
            version=version,
            details={"command": resolved},
        )

    def _resolved_command(self) -> str:
        if self._apptainer_command and shutil.which(self._apptainer_command):
            return self._apptainer_command
        if self._singularity_command and shutil.which(self._singularity_command):
            return self._singularity_command
        return ""

    def _detect_version(self) -> str:
        resolved = self._resolved_command()
        if not resolved:
            return ""
        try:
            result = subprocess.run(
                [resolved, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return (result.stdout or result.stderr or "").strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError):
            pass
        return ""
