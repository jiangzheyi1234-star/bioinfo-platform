"""Remote storage manager utilities."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

DEFAULT_CLEANUP_THRESHOLD = 0.85


class SSHServiceProtocol(Protocol):
    """Minimum SSH protocol used by this module."""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]: ...


@dataclass
class DiskUsage:
    """Disk usage stats in GiB."""

    total_gb: float
    used_gb: float
    available_gb: float
    percent: float  # 0.0 ~ 1.0
    mount_point: str


@dataclass
class StorageReport:
    """Per-project storage report by tier."""

    raw_bytes: int
    intermediate_bytes: int
    result_bytes: int
    total_bytes: int

    @property
    def raw_mb(self) -> float:
        return self.raw_bytes / (1024 * 1024)

    @property
    def intermediate_mb(self) -> float:
        return self.intermediate_bytes / (1024 * 1024)

    @property
    def result_mb(self) -> float:
        return self.result_bytes / (1024 * 1024)

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)


class StorageManager:
    """Manage remote disk usage and intermediate cleanup."""

    def __init__(self, ssh_service: SSHServiceProtocol) -> None:
        self._ssh = ssh_service

    def get_disk_usage(self, remote_path: str = "/h2ometa") -> DiskUsage:
        """Fetch disk usage for the partition containing ``remote_path``."""
        rc, stdout, stderr = self._ssh.run(
            f"df -B1 {remote_path} 2>/dev/null | tail -1", timeout=15
        )

        if rc != 0 or not stdout.strip():
            logger.debug("Path %s unavailable, trying root partition", remote_path)
            rc, stdout, stderr = self._ssh.run("df -B1 / 2>/dev/null | tail -1", timeout=15)

        if rc != 0 or not stdout.strip():
            err = stderr.strip() if stderr else "no output"
            raise RuntimeError(f"df 命令失败: {err}")

        return self._parse_df_output(stdout.strip())

    def get_storage_report(self, project_remote_base: str) -> StorageReport:
        """Get raw/intermediate/result size report."""
        tiers = ["raw", "intermediate", "result"]
        sizes: dict[str, int] = {}

        for tier in tiers:
            tier_path = f"{project_remote_base}/{tier}"
            sizes[tier] = self._get_dir_size(tier_path)

        total = sum(sizes.values())
        return StorageReport(
            raw_bytes=sizes["raw"],
            intermediate_bytes=sizes["intermediate"],
            result_bytes=sizes["result"],
            total_bytes=total,
        )

    def cleanup_intermediate(self, intermediate_dir: str, dry_run: bool = False) -> list[str]:
        """Delete all files inside intermediate dir (keep directory tree)."""
        rc, stdout, stderr = self._ssh.run(
            f"find {intermediate_dir} -type f 2>/dev/null", timeout=30
        )

        if rc != 0:
            logger.warning("List intermediate files failed: %s", stderr.strip())
            return []

        files = [f.strip() for f in stdout.strip().split("\n") if f.strip()]
        if not files:
            return []

        if dry_run:
            return files

        rc, _, stderr = self._ssh.run(
            f"find {intermediate_dir} -type f -delete", timeout=60
        )
        if rc != 0:
            logger.error("Delete intermediate files failed: %s", stderr.strip())
            return []

        return files

    def should_cleanup(
        self,
        remote_path: str = "/h2ometa",
        threshold: float = DEFAULT_CLEANUP_THRESHOLD,
    ) -> bool:
        """Return True if disk usage is above threshold."""
        try:
            usage = self.get_disk_usage(remote_path)
            return usage.percent >= threshold
        except Exception:
            logger.exception("Failed to check disk usage")
            return False

    def _get_dir_size(self, remote_dir: str) -> int:
        """Return directory size in bytes."""
        rc, stdout, _ = self._ssh.run(
            f"du -sb {remote_dir} 2>/dev/null | cut -f1", timeout=30
        )
        if rc != 0 or not stdout.strip():
            return 0
        try:
            return int(stdout.strip())
        except ValueError:
            return 0

    @staticmethod
    def _parse_df_output(line: str) -> DiskUsage:
        """Parse one ``df -B1`` line."""
        line = line.strip()
        if not line:
            raise RuntimeError("df 输出为空")

        parts = line.split()
        if len(parts) < 6:
            raise RuntimeError(f"df 输出列数不足 ({len(parts)} < 6): {line}")

        try:
            mount_point = parts[-1]
            percent_str = parts[-2]
            available = int(parts[-3])
            used = int(parts[-4])
            total = int(parts[-5])
        except (ValueError, IndexError) as exc:
            raise RuntimeError(f"解析 df 输出失败: {line}, parts={parts}") from exc

        percent_match = re.search(r"(\d+)%", percent_str)
        if percent_match:
            percent = int(percent_match.group(1)) / 100.0
        else:
            percent = used / total if total > 0 else 0.0

        return DiskUsage(
            total_gb=total / (1024**3),
            used_gb=used / (1024**3),
            available_gb=available / (1024**3),
            percent=percent,
            mount_point=mount_point,
        )
