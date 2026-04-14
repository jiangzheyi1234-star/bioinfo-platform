"""Shared server capability types for remote workflow preflight and doctor checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

SshRunFn = Callable[[str, int], tuple[int, str, str]]

_SUPPORTED_ARCHES = {"x86_64", "aarch64"}
_CANONICAL_PROFILE_ORDER = (
    "hpc_slurm_apptainer",
    "hpc_slurm_conda",
    "personal_docker",
    "personal_podman",
    "personal_conda",
)


class PreflightError(RuntimeError):
    """Raised when remote preflight detects blocking capability issues."""

    def __init__(self, failures: list[str] | str):
        if isinstance(failures, str):
            cleaned = [failures.strip()] if failures.strip() else []
        else:
            cleaned = [str(item).strip() for item in failures if str(item).strip()]
        self.failures = cleaned
        super().__init__("；".join(cleaned) if cleaned else "服务器预检失败")


@dataclass(frozen=True)
class ServerCapabilities:
    """Remote server capability snapshot used by workflow-first entry points."""

    arch: str
    has_bash: bool
    has_curl: bool
    has_wget: bool
    has_sha256sum: bool
    has_screen: bool
    has_java: bool
    java_version: str
    has_nextflow: bool
    nextflow_version: str
    has_docker: bool
    has_podman: bool
    has_apptainer: bool
    has_micromamba: bool
    has_conda: bool
    has_sbatch: bool
    free_disk_gb: float
    home_writable: bool

    @property
    def downloader(self) -> Literal["curl", "wget"]:
        if self.has_curl:
            return "curl"
        if self.has_wget:
            return "wget"
        raise PreflightError(["远端缺少 curl/wget，无法下载所需文件"])

    @property
    def recommended_profile_kind(self) -> str:
        if self.has_sbatch:
            if self.has_apptainer:
                return "hpc_slurm_apptainer"
            if self.has_micromamba or self.has_conda:
                return "hpc_slurm_conda"
        if self.has_docker:
            return "personal_docker"
        if self.has_podman:
            return "personal_podman"
        return "personal_conda"

    def supports_profile_kind(self, profile_kind: str) -> bool:
        normalized = str(profile_kind or "").strip()
        if normalized == "hpc_slurm_apptainer":
            return self.has_sbatch and self.has_apptainer
        if normalized == "hpc_slurm_conda":
            return self.has_sbatch and (self.has_micromamba or self.has_conda)
        if normalized == "personal_docker":
            return self.has_docker
        if normalized == "personal_podman":
            return self.has_podman
        if normalized == "personal_conda":
            return self.has_micromamba or self.has_conda
        return False

    @property
    def supported_profile_kinds(self) -> tuple[str, ...]:
        return tuple(profile_kind for profile_kind in _CANONICAL_PROFILE_ORDER if self.supports_profile_kind(profile_kind))

    @property
    def recommended_executor(self) -> str:
        return "slurm" if self.recommended_profile_kind.startswith("hpc_slurm_") else "local"

    @property
    def recommended_packaging_mode(self) -> Literal["container", "conda"]:
        return "container" if self.recommended_profile_kind.endswith(("docker", "podman", "apptainer")) else "conda"

    @property
    def recommended_container_runtime(self) -> str:
        if self.recommended_profile_kind == "personal_docker":
            return "docker"
        if self.recommended_profile_kind == "personal_podman":
            return "podman"
        if self.recommended_profile_kind == "hpc_slurm_apptainer":
            return "apptainer"
        return ""

    def bootstrap_failures(self, min_free_disk_gb: float = 5.0) -> list[str]:
        failures: list[str] = []
        if self.arch not in _SUPPORTED_ARCHES:
            failures.append(f"不支持的服务器架构: {self.arch or '未知'}（仅支持 x86_64/aarch64）")
        if not self.has_bash:
            failures.append("远端缺少 bash，无法执行 workflow launcher")
        if not self.has_curl and not self.has_wget:
            failures.append("远端缺少 curl/wget，无法下载所需文件")
        if not self.has_sha256sum:
            failures.append("远端缺少 sha256sum，无法校验下载内容完整性")
        if not self.home_writable:
            failures.append("HOME 目录不可写，无法创建 workflow 运行目录")
        if self.free_disk_gb < min_free_disk_gb:
            failures.append(f"远端磁盘空间不足: {self.free_disk_gb:.1f} GB < {min_free_disk_gb:.1f} GB")
        return failures

    def runtime_failures(self) -> list[str]:
        failures: list[str] = []
        if not self.has_java:
            failures.append("远端缺少 Java，无法运行 Nextflow")
        if not self.has_nextflow:
            failures.append("远端缺少 Nextflow，可先在连接页安装运行时")
        if self.recommended_profile_kind.startswith("hpc_slurm_"):
            if not self.has_sbatch:
                failures.append("缺少 sbatch，无法使用 Slurm backend")
            if not self.has_apptainer and not (self.has_micromamba or self.has_conda):
                failures.append("HPC 运行时缺少 Apptainer 或 micromamba/conda")
        elif not (self.has_docker or self.has_podman or self.has_micromamba or self.has_conda):
            failures.append("个人服务器缺少 Docker/Podman 或 micromamba/conda")
        return failures

    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if not self.has_screen:
            warnings.append("未检测到 screen；这不会阻塞 workflow run，但旧环境安装流程可能受限")
        if self.has_java and not self.java_version:
            warnings.append("Java 已检测到，但版本字符串为空")
        if self.has_nextflow and not self.nextflow_version:
            warnings.append("Nextflow 已检测到，但版本字符串为空")
        return warnings
