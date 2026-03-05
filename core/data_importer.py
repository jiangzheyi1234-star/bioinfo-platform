"""数据导入器 — 本地文件上传到远端并注册到 DataRegistry。

通用的"本地文件 -> SSH 上传 -> DataRegistry 注册"流程，
所有工具共用此模块进行数据导入。
"""

import logging
import os
from pathlib import Path
from typing import Any, Optional, Protocol

from PyQt6.QtCore import QObject, pyqtSignal

from core.data_registry import DataRegistry

logger = logging.getLogger(__name__)


class SSHServiceProtocol(Protocol):
    """SSHService 的最小接口，用于解耦和测试"""

    def run(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]: ...

    def upload(self, local_path: str, remote_path: str) -> None: ...


class DataImporter(QObject):
    """本地文件导入器

    负责将本地文件上传到远端服务器的项目目录中，
    然后注册到 DataRegistry 进行血缘追踪。

    Signals:
        upload_progress(str, int): 文件名, 上传百分比
        import_completed(str): 导入完成，参数为 data_id
        import_failed(str, str): 导入失败，参数为文件名和错误信息
    """

    upload_progress = pyqtSignal(str, int)   # filename, percent
    import_completed = pyqtSignal(str)        # data_id
    import_failed = pyqtSignal(str, str)      # filename, error

    def __init__(
        self,
        ssh_service: SSHServiceProtocol,
        registry: DataRegistry,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._ssh = ssh_service
        self._registry = registry

    def import_file(
        self,
        local_path: str,
        sample_id: str,
        data_type: str,
        project_remote_base: str,
        tier: str = "raw",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """导入单个文件到远端并注册

        Args:
            local_path: 本地文件路径
            sample_id: 所属样本 ID
            data_type: 文件格式 (fastq / fasta / ...)
            project_remote_base: 项目远端根目录 (如 /h2ometa/projects/proj_xxx)
            tier: 数据层级，默认 "raw"
            metadata: 额外元数据

        Returns:
            注册后的 data_id

        Raises:
            FileNotFoundError: 本地文件不存在
            RuntimeError: SSH 上传或远端目录创建失败
        """
        # 校验本地文件
        if not Path(local_path).exists():
            raise FileNotFoundError(f"本地文件不存在: {local_path}")

        filename = os.path.basename(local_path)
        remote_dir = f"{project_remote_base}/raw/{sample_id}"
        remote_path = f"{remote_dir}/{filename}"

        try:
            # 创建远端目录
            self.upload_progress.emit(filename, 0)
            rc, _, err = self._ssh.run(f"mkdir -p {remote_dir}", timeout=15)
            if rc != 0:
                raise RuntimeError(f"创建远端目录失败: {err}")

            # 上传文件
            self.upload_progress.emit(filename, 10)
            self._ssh.upload(local_path, remote_path)
            self.upload_progress.emit(filename, 90)

            # 注册到 DataRegistry
            data_id = self._registry.register_input(
                file_path=remote_path,
                sample_id=sample_id,
                data_type=data_type,
                tier=tier,
                metadata=metadata,
            )

            self.upload_progress.emit(filename, 100)
            self.import_completed.emit(data_id)
            logger.info("文件导入完成: %s -> %s (%s)", local_path, remote_path, data_id)
            return data_id

        except Exception as e:
            error_msg = str(e)
            logger.error("文件导入失败: %s -> %s", local_path, error_msg)
            self.import_failed.emit(filename, error_msg)
            raise

    def import_batch(
        self,
        files: list[dict[str, Any]],
        project_remote_base: str,
    ) -> list[str]:
        """批量导入文件

        Args:
            files: 文件列表，每项包含:
                - local_path (str): 本地路径
                - sample_id (str): 样本 ID
                - data_type (str): 文件格式
                - tier (str, optional): 数据层级，默认 "raw"
                - metadata (dict, optional): 额外元数据
            project_remote_base: 项目远端根目录

        Returns:
            data_id 列表（与输入顺序对应）
        """
        data_ids: list[str] = []
        for f in files:
            data_id = self.import_file(
                local_path=f["local_path"],
                sample_id=f["sample_id"],
                data_type=f["data_type"],
                project_remote_base=project_remote_base,
                tier=f.get("tier", "raw"),
                metadata=f.get("metadata"),
            )
            data_ids.append(data_id)

        logger.info("批量导入完成: %d 个文件", len(data_ids))
        return data_ids
