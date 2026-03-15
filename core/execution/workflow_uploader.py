"""工作流脚本上传器 — 将插件本地 workflow/ 目录上传到远端服务器。

仅 primer_design 等包含自研脚本的插件需要此功能。
其余使用 conda 安装的工具不受影响。
"""
import logging
import os
import stat
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 需要设置可执行权限的文件后缀
_EXECUTABLE_SUFFIXES = {".sh", ".pl"}


def get_local_workflow_dir(descriptor_yaml_path: str) -> Optional[Path]:
    """检查插件 tool.yaml 同级是否有 workflow/ 目录。

    Args:
        descriptor_yaml_path: tool.yaml 的本地文件路径。

    Returns:
        workflow/ 目录的 Path，不存在则返回 None。
    """
    if not descriptor_yaml_path:
        return None
    yaml_path = Path(descriptor_yaml_path)
    workflow_dir = yaml_path.parent / "workflow"
    if workflow_dir.is_dir():
        return workflow_dir
    return None


def upload_workflow(ssh_service, local_dir: Path, remote_dir: str) -> None:
    """通过 SFTP 递归上传本地 workflow/ 目录到远端。

    Args:
        ssh_service: 具有 get_sftp() 方法的 SSH 服务对象。
        local_dir: 本地 workflow/ 目录路径。
        remote_dir: 远端目标目录路径。
    """
    sftp = ssh_service.get_sftp()

    for dirpath, dirnames, filenames in os.walk(local_dir):
        rel = os.path.relpath(dirpath, local_dir)
        if rel == ".":
            remote_sub = remote_dir
        else:
            remote_sub = f"{remote_dir}/{rel.replace(os.sep, '/')}"

        # 创建远端目录
        _sftp_makedirs(sftp, remote_sub)

        for fname in filenames:
            local_file = os.path.join(dirpath, fname)
            remote_file = f"{remote_sub}/{fname}"
            sftp.put(local_file, remote_file)

            # 设置可执行权限
            suffix = Path(fname).suffix.lower()
            if suffix in _EXECUTABLE_SUFFIXES or not suffix:
                # 无后缀文件（如 mfeprimer 二进制）也设为可执行
                sftp.chmod(remote_file, 0o755)

    logger.info("workflow 上传完成: %s -> %s", local_dir, remote_dir)


def _sftp_makedirs(sftp, remote_path: str) -> None:
    """递归创建远端目录（类似 mkdir -p）。"""
    parts = remote_path.split("/")
    current = ""
    for part in parts:
        if not part:
            current = "/"
            continue
        current = f"{current}/{part}" if current != "/" else f"/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)
