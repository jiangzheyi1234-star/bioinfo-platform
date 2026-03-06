"""存储管理器 — 远程磁盘空间监控与中间文件清理。

职责:
1. 监控远端 /h2ometa/ 磁盘使用情况
2. 中间文件自动清理（intermediate tier）
3. 项目存储报告生成
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

# 磁盘使用率清理阈值
DEFAULT_CLEANUP_THRESHOLD = 0.85


class SSHServiceProtocol(Protocol):
    """SSHService 最小接口"""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]: ...


@dataclass
class DiskUsage:
    """磁盘使用情况"""

    total_gb: float
    used_gb: float
    available_gb: float
    percent: float       # 0.0 ~ 1.0
    mount_point: str


@dataclass
class StorageReport:
    """项目存储报告"""

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
    """远程存储管理器

    典型用法::

        manager = StorageManager(ssh_service)
        usage = manager.check_disk_usage("/h2ometa")
        if usage.percent > 0.85:
            cleaned = manager.cleanup_intermediate(
                "/h2ometa/projects/proj_abc/intermediate",
                data_registry=registry,
            )
    """

    def __init__(self, ssh_service: SSHServiceProtocol) -> None:
        self._ssh = ssh_service

    def check_disk_usage(self, remote_path: str = "/h2ometa") -> DiskUsage:
        """检查远端磁盘使用情况

        Args:
            remote_path: 远端路径，用于确定所在分区

        Returns:
            DiskUsage 数据

        Raises:
            RuntimeError: SSH 命令执行失败或解析失败
        """
        rc, stdout, stderr = self._ssh.run(
            f"df -B1 {remote_path} | tail -1", timeout=15,
        )

        if rc != 0:
            raise RuntimeError(f"df 命令失败: {stderr.strip()}")

        return self._parse_df_output(stdout.strip())

    def get_storage_report(
        self,
        project_remote_base: str,
    ) -> StorageReport:
        """获取项目存储报告

        分别统计 raw、intermediate、result 目录的大小。

        Args:
            project_remote_base: 项目远端根目录，如 /h2ometa/projects/proj_abc

        Returns:
            StorageReport 包含三个 tier 的大小
        """
        tiers = ["raw", "intermediate", "result"]
        sizes: dict[str, int] = {}

        for tier in tiers:
            tier_path = f"{project_remote_base}/{tier}"
            size = self._get_dir_size(tier_path)
            sizes[tier] = size

        total = sum(sizes.values())
        return StorageReport(
            raw_bytes=sizes["raw"],
            intermediate_bytes=sizes["intermediate"],
            result_bytes=sizes["result"],
            total_bytes=total,
        )

    def cleanup_intermediate(
        self,
        intermediate_dir: str,
        dry_run: bool = False,
    ) -> list[str]:
        """清理中间文件目录

        删除 intermediate 目录下的所有文件，保留目录结构。
        raw 和 result 文件永不删除。

        Args:
            intermediate_dir: 中间文件目录路径
            dry_run: 如果为 True，只列出文件不实际删除

        Returns:
            已删除（或将被删除）的文件路径列表
        """
        # 列出所有文件
        rc, stdout, stderr = self._ssh.run(
            f"find {intermediate_dir} -type f 2>/dev/null", timeout=30,
        )

        if rc != 0:
            logger.warning("列出中间文件失败: %s", stderr.strip())
            return []

        files = [f.strip() for f in stdout.strip().split("\n") if f.strip()]

        if not files:
            logger.info("中间文件目录为空: %s", intermediate_dir)
            return []

        if dry_run:
            logger.info("干运行: 将删除 %d 个中间文件", len(files))
            return files

        # 实际删除
        rc, _, stderr = self._ssh.run(
            f"find {intermediate_dir} -type f -delete", timeout=60,
        )

        if rc != 0:
            logger.error("删除中间文件失败: %s", stderr.strip())
            return []

        logger.info("已清理 %d 个中间文件: %s", len(files), intermediate_dir)
        return files

    def should_cleanup(
        self,
        remote_path: str = "/h2ometa",
        threshold: float = DEFAULT_CLEANUP_THRESHOLD,
    ) -> bool:
        """检查是否需要清理磁盘

        Args:
            remote_path: 远端路径
            threshold: 清理阈值（0.0~1.0）

        Returns:
            True 如果磁盘使用率超过阈值
        """
        try:
            usage = self.check_disk_usage(remote_path)
            return usage.percent >= threshold
        except Exception:
            logger.exception("检查磁盘使用率失败")
            return False

    # ── 内部方法 ──────────────────────────────────────────────

    def _get_dir_size(self, remote_dir: str) -> int:
        """获取远端目录大小（字节）"""
        rc, stdout, _ = self._ssh.run(
            f"du -sb {remote_dir} 2>/dev/null | cut -f1", timeout=30,
        )
        if rc != 0 or not stdout.strip():
            return 0
        try:
            return int(stdout.strip())
        except ValueError:
            return 0

    @staticmethod
    def _parse_df_output(line: str) -> DiskUsage:
        """解析 df -B1 输出行

        格式示例:
        /dev/sda1  500107862016  200043544064  274624765952  43% /home
        """
        parts = line.split()

        # df 输出可能跨行，取最后 6 列
        if len(parts) < 4:
            raise RuntimeError(f"无法解析 df 输出: {line}")

        # 从后向前取值更可靠（设备名可能包含空格）
        try:
            mount_point = parts[-1]
            percent_str = parts[-2]
            available = int(parts[-3])
            used = int(parts[-4])
            total = int(parts[-5])
        except (ValueError, IndexError) as e:
            raise RuntimeError(f"解析 df 输出失败: {line}") from e

        # 解析百分比
        percent_match = re.search(r"(\d+)%", percent_str)
        percent = int(percent_match.group(1)) / 100.0 if percent_match else 0.0

        return DiskUsage(
            total_gb=total / (1024 ** 3),
            used_gb=used / (1024 ** 3),
            available_gb=available / (1024 ** 3),
            percent=percent,
            mount_point=mount_point,
        )
