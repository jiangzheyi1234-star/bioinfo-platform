"""Shared server capability types for remote preflight and installers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

SshRunFn = Callable[[str, int], tuple[int, str, str]]

_SUPPORTED_ARCHES = {"x86_64", "aarch64"}


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
    """Remote server capability snapshot used by installer entry points."""

    arch: str
    has_curl: bool
    has_wget: bool
    has_screen: bool
    has_sha256sum: bool
    free_disk_gb: float

    @property
    def downloader(self) -> Literal["curl", "wget"]:
        if self.has_curl:
            return "curl"
        if self.has_wget:
            return "wget"
        raise PreflightError(["远端缺少 curl/wget，无法下载所需文件"])

    def failures(self, min_free_disk_gb: float = 5.0) -> list[str]:
        failures: list[str] = []

        if self.arch not in _SUPPORTED_ARCHES:
            failures.append(f"不支持的服务器架构: {self.arch or '未知'}（仅支持 x86_64/aarch64）")
        if not self.has_curl and not self.has_wget:
            failures.append("远端缺少 curl/wget，无法下载所需文件")
        if not self.has_screen:
            failures.append("远端缺少 screen，无法提交后台任务")
        if not self.has_sha256sum:
            failures.append("远端缺少 sha256sum，无法校验下载内容完整性")
        if self.free_disk_gb < min_free_disk_gb:
            failures.append(f"远端磁盘空间不足: {self.free_disk_gb:.1f} GB < {min_free_disk_gb:.1f} GB")

        return failures
