"""容器检测与镜像管理模块。

纯 Python 模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现。
支持 Docker 和 Singularity 容器运行时。
"""

import logging
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ssh_run_fn 类型: (cmd, timeout) -> (rc, stdout, stderr)
SshRunFn = Callable[[str, int], Tuple[int, str, str]]


class ContainerRuntime(Enum):
    """容器运行时类型。"""
    NONE = "none"
    DOCKER = "docker"
    SINGULARITY = "singularity"


class ContainerStatus(Enum):
    """容器检测状态。"""
    OK = "ok"
    NOT_FOUND = "not_found"
    NOT_INSTALLED = "not_installed"


@dataclass(frozen=True)
class ContainerRuntimeInfo:
    """容器运行时信息。"""
    runtime: ContainerRuntime
    status: ContainerStatus
    version: Optional[str]  # Docker: "24.0.5", Singularity: "3.8.1"
    message: str


@dataclass(frozen=True)
class ContainerImageInfo:
    """容器镜像信息。"""
    name: str           # 镜像名称（含 tag）
    path: str           # 远端路径（Singularity: .sif 文件）
    size_mb: float      # 大小（MB）
    exists: bool        # 是否存在


# Docker --version 输出正则
_DOCKER_VERSION_RE = re.compile(r"Docker version (\d+\.\d+(?:\.\d+)?)")

# Singularity --version 输出正则
_SINGULARITY_VERSION_RE = re.compile(r"singularity version (\d+\.\d+(?:\.\d+)?)")


def _q(value: str) -> str:
    """Shell-safe quoting."""
    return shlex.quote(value)


def _q_path(path: str) -> str:
    """Quote path while preserving '~/...' expansion via $HOME on remote shell."""
    if path == "~":
        return "$HOME"
    if path.startswith("~/"):
        return f"$HOME/{_q(path[2:])}"
    return _q(path)


def detect_runtime(ssh_run_fn: SshRunFn, timeout: int = 15) -> ContainerRuntimeInfo:
    """检测远端容器运行时（Docker / Singularity）。

    检测顺序：
    1. Singularity（推荐 HPC 环境）
    2. Docker
    3. NONE

    Args:
        ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
        timeout: 单次命令超时秒数

    Returns:
        ContainerRuntimeInfo
    """
    # 1. 检测 Singularity
    try:
        rc, stdout, stderr = ssh_run_fn("singularity --version", timeout)
        if rc == 0:
            output = (stdout + "\n" + stderr).strip()
            m = _SINGULARITY_VERSION_RE.search(output)
            version = m.group(1) if m else None
            return ContainerRuntimeInfo(
                runtime=ContainerRuntime.SINGULARITY,
                status=ContainerStatus.OK,
                version=version,
                message=f"Singularity {version or 'unknown version'} detected",
            )
    except Exception as e:
        logger.debug("Singularity 检测失败: %s", e)

    # 2. 检测 Docker
    try:
        rc, stdout, stderr = ssh_run_fn("docker --version", timeout)
        if rc == 0:
            output = (stdout + "\n" + stderr).strip()
            m = _DOCKER_VERSION_RE.search(output)
            version = m.group(1) if m else None
            return ContainerRuntimeInfo(
                runtime=ContainerRuntime.DOCKER,
                status=ContainerStatus.OK,
                version=version,
                message=f"Docker {version or 'unknown version'} detected",
            )
    except Exception as e:
        logger.debug("Docker 检测失败: %s", e)

    # 3. 全部未检测到
    return ContainerRuntimeInfo(
        runtime=ContainerRuntime.NONE,
        status=ContainerStatus.NOT_FOUND,
        version=None,
        message="未检测到容器运行时 (Docker/Singularity)",
    )


def list_singularity_images(
    ssh_run_fn: SshRunFn,
    cache_dir: str = "~/.singularity",
    timeout: int = 30,
) -> List[ContainerImageInfo]:
    """列出 Singularity 镜像。

    Args:
        ssh_run_fn: SSH 命令执行回调
        cache_dir: Singularity 镜像缓存目录
        timeout: 超时秒数

    Returns:
        镜像列表
    """
    images: List[ContainerImageInfo] = []

    try:
        q_cache_dir = _q_path(cache_dir)
        # 列出 cache 目录中的 .sif 文件
        rc, stdout, _ = ssh_run_fn(
            f"find {q_cache_dir} -maxdepth 1 -name '*.sif' -type f 2>/dev/null | "
            "while IFS= read -r f; do "
            "size=$(stat -c %s \"$f\" 2>/dev/null || stat -f %z \"$f\" 2>/dev/null || echo 0); "
            "printf '%s\\t%s\\n' \"$f\" \"$size\"; "
            "done",
            timeout,
        )
        if rc == 0:
            for line in stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.rsplit("\t", 1)
                if len(parts) >= 2:
                    path = parts[0]
                    try:
                        size_bytes = int(parts[1])
                        size_mb = size_bytes / (1024 * 1024)
                    except (ValueError, IndexError):
                        size_mb = 0.0

                    # 提取镜像名（不含路径和 .sif 后缀）
                    name = path.rsplit("/", 1)[-1].replace(".sif", "")
                    images.append(ContainerImageInfo(
                        name=name,
                        path=path,
                        size_mb=size_mb,
                        exists=True,
                    ))
    except Exception as e:
        logger.debug("列出 Singularity 镜像失败: %s", e)

    return images


def list_docker_images(
    ssh_run_fn: SshRunFn,
    timeout: int = 30,
) -> List[ContainerImageInfo]:
    """列出 Docker 镜像。

    Args:
        ssh_run_fn: SSH 命令执行回调
        timeout: 超时秒数

    Returns:
        镜像列表
    """
    images: List[ContainerImageInfo] = []

    try:
        rc, stdout, _ = ssh_run_fn(
            "docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'",
            timeout,
        )
        if rc == 0:
            for line in stdout.strip().splitlines():
                if not line.strip() or line.startswith("REPOSITORY"):
                    continue

                # 解析格式: "biocontainers/fastp:v0.23.4 123MB"
                parts = line.strip().rsplit(" ", 1)
                if len(parts) == 2:
                    name = parts[0]
                    size_str = parts[1]

                    # 转换大小为 MB
                    try:
                        if size_str.endswith("MB"):
                            size_mb = float(size_str[:-2])
                        elif size_str.endswith("GB"):
                            size_mb = float(size_str[:-2]) * 1024
                        elif size_str.endswith("kB"):
                            size_mb = float(size_str[:-2]) / 1024
                        elif size_str.endswith("B"):
                            size_mb = float(size_str[:-1]) / (1024 * 1024)
                        else:
                            size_mb = 0.0
                    except ValueError:
                        size_mb = 0.0

                    images.append(ContainerImageInfo(
                        name=name,
                        path=name,  # Docker 使用镜像名作为路径
                        size_mb=size_mb,
                        exists=True,
                    ))
    except Exception as e:
        logger.debug("列出 Docker 镜像失败: %s", e)

    return images


def pull_singularity_image(
    ssh_run_fn: SshRunFn,
    image_uri: str,
    cache_dir: str = "~/.singularity",
    output_name: Optional[str] = None,
    timeout: int = 600,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """拉取 Singularity 镜像。

    Args:
        ssh_run_fn: SSH 命令执行回调
        image_uri: 镜像 URI (如 docker://biocontainers/fastp:v0.23.4)
        cache_dir: 缓存目录
        output_name: 输出文件名（不含 .sif），默认从 URI 推断
        timeout: 超时秒数
        progress_callback: 进度回调，接收进度消息

    Returns:
        (success, message)
    """
    if output_name is None:
        # 从 URI 推断名称: docker://biocontainers/fastp:v0.23.4 -> fastp_v0.23.4
        output_name = image_uri.rsplit(":", 1)[-1]
        if "/" in output_name:
            output_name = output_name.split("/")[-1]
        output_name = output_name.replace(".", "_")

    output_path = f"{cache_dir}/{output_name}.sif"
    output_path_cmd = _q_path(output_path)

    if progress_callback:
        progress_callback(f"正在下载镜像 {image_uri}...")

    # 使用 singularity pull
    cmd = (
        f"mkdir -p {_q_path(cache_dir)} && "
        f"singularity pull --force --name {output_path_cmd} {_q(image_uri)}"
    )

    try:
        rc, stdout, stderr = ssh_run_fn(cmd, timeout)

        if progress_callback:
            progress_callback(f"下载完成，exit code: {rc}")

        if rc == 0:
            return True, output_path
        else:
            error_msg = stderr[:200] if stderr else "Unknown error"
            return False, f"拉取失败: {error_msg}"
    except Exception as e:
        return False, f"拉取异常: {e}"


def pull_docker_image(
    ssh_run_fn: SshRunFn,
    image: str,
    timeout: int = 600,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[bool, str]:
    """拉取 Docker 镜像。

    Args:
        ssh_run_fn: SSH 命令执行回调
        image: 镜像名 (如 biocontainers/fastp:v0.23.4)
        timeout: 超时秒数
        progress_callback: 进度回调

    Returns:
        (success, message)
    """
    if progress_callback:
        progress_callback(f"正在拉取镜像 {image}...")

    cmd = f"docker pull {_q(image)}"

    try:
        rc, stdout, stderr = ssh_run_fn(cmd, timeout)

        if progress_callback:
            progress_callback(f"拉取完成，exit code: {rc}")

        if rc == 0:
            return True, image
        else:
            error_msg = stderr[:200] if stderr else "Unknown error"
            return False, f"拉取失败: {error_msg}"
    except Exception as e:
        return False, f"拉取异常: {e}"


def remove_singularity_image(
    ssh_run_fn: SshRunFn,
    image_path: str,
    timeout: int = 30,
) -> Tuple[bool, str]:
    """删除 Singularity 镜像。

    Args:
        ssh_run_fn: SSH 命令执行回调
        image_path: 镜像文件路径
        timeout: 超时秒数

    Returns:
        (success, message)
    """
    try:
        rc, _, stderr = ssh_run_fn(f"rm -f -- {_q(image_path)}", timeout)
        if rc == 0:
            return True, "已删除"
        else:
            return False, stderr[:100] if stderr else "删除失败"
    except Exception as e:
        return False, str(e)


def remove_docker_image(
    ssh_run_fn: SshRunFn,
    image: str,
    timeout: int = 30,
) -> Tuple[bool, str]:
    """删除 Docker 镜像。

    Args:
        ssh_run_fn: SSH 命令执行回调
        image: 镜像名
        timeout: 超时秒数

    Returns:
        (success, message)
    """
    try:
        rc, _, stderr = ssh_run_fn(f"docker rmi {_q(image)}", timeout)
        if rc == 0:
            return True, "已删除"
        else:
            return False, stderr[:100] if stderr else "删除失败"
    except Exception as e:
        return False, str(e)


def build_singularity_exec_command(
    image_path: str,
    command: str,
    binds: Optional[List[str]] = None,
    workdir: Optional[str] = None,
) -> str:
    """构建 Singularity 执行命令。

    Args:
        image_path: 镜像文件路径
        command: 要执行的命令
        binds: 绑定卷列表 ["host:container", ...]
        workdir: 工作目录

    Returns:
        完整的 singularity exec 命令
    """
    parts: List[str] = ["singularity", "exec"]

    # 添加绑定卷
    if binds:
        for bind in binds:
            parts.extend(["--bind", bind])

    # 添加工作目录
    if workdir:
        parts.extend(["--pwd", workdir])

    parts.append(image_path)
    parts.extend(["sh", "-lc", command])

    return " ".join(_q(p) for p in parts)


def build_docker_exec_command(
    image: str,
    command: str,
    binds: Optional[List[str]] = None,
    workdir: Optional[str] = None,
    rm: bool = True,
    interactive: bool = False,
) -> str:
    """构建 Docker 执行命令。

    Args:
        image: 镜像名
        command: 要执行的命令
        binds: 绑定卷列表 ["host:container", ...]
        workdir: 工作目录
        rm: 退出后删除容器
        interactive: 是否启用交互模式（-it），后台任务应设为 False

    Returns:
        完整的 docker run 命令
    """
    parts: List[str] = ["docker", "run"]

    # 交互式终端（后台任务不需要）
    if interactive:
        parts.append("-it")

    # 退出后删除容器
    if rm:
        parts.append("--rm")

    # 添加绑定卷
    if binds:
        for bind in binds:
            parts.extend(["-v", bind])

    # 添加工作目录
    if workdir:
        parts.extend(["-w", workdir])

    parts.append(image)
    parts.extend(["sh", "-lc", command])

    return " ".join(_q(p) for p in parts)
