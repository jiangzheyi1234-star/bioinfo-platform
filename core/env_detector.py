"""conda 环境检测与 Miniforge 自动安装模块。

纯 Python 模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现。
参考 Galaxy CondaContext 和 Snakemake 的 conda 发现逻辑。
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)

# ssh_run_fn 类型: (cmd, timeout) -> (rc, stdout, stderr)
SshRunFn = Callable[[str, int], Tuple[int, str, str]]

# Miniforge 下载 URL（业界统一推荐：Snakemake/Bioconda/Galaxy 均用 Miniforge3）
_MINIFORGE_URL = (
    "https://github.com/conda-forge/miniforge/releases/latest/download/"
    "Miniforge3-Linux-x86_64.sh"
)

# 默认安装目录
_DEFAULT_INSTALL_DIR = "~/.h2ometa/conda"

# 远端常见 conda 安装目录（参考 Galaxy find_conda_prefix）
_COMMON_CONDA_PATHS = [
    "~/.h2ometa/conda/bin/conda",
    "~/miniforge3/bin/conda",
    "~/miniconda3/bin/conda",
    "~/anaconda3/bin/conda",
    "/opt/miniforge3/bin/conda",
    "/opt/conda/bin/conda",
]

# conda --version 输出正则: "conda 24.1.2"
_VERSION_RE = re.compile(r"conda\s+(\d+\.\d+(?:\.\d+)?)")


class CondaStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    VERSION_PARSE_FAILED = "version_parse_failed"


@dataclass(frozen=True)
class CondaDetectResult:
    status: CondaStatus
    executable: Optional[str]   # 绝对路径，NOT_FOUND 时为 None
    version: Optional[str]      # "24.1.2"
    message: str                # 人类可读描述


def _validate_conda(ssh_run_fn: SshRunFn, exe: str, timeout: int = 15) -> CondaDetectResult:
    """验证 conda 可执行文件：运行 --version 并解析版本号。"""
    try:
        rc, stdout, stderr = ssh_run_fn(f"{exe} --version", timeout)
        if rc != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND,
                executable=None,
                version=None,
                message=f"{exe} --version 返回非零退出码 {rc}",
            )
        # conda 可能将版本输出到 stdout 或 stderr
        output = (stdout + "\n" + stderr).strip()
        m = _VERSION_RE.search(output)
        if m:
            version = m.group(1)
            return CondaDetectResult(
                status=CondaStatus.OK,
                executable=exe,
                version=version,
                message=f"检测到 conda {version} ({exe})",
            )
        return CondaDetectResult(
            status=CondaStatus.VERSION_PARSE_FAILED,
            executable=exe,
            version=None,
            message=f"检测到 conda 但版本号无法解析: {output[:80]}",
        )
    except Exception as e:
        logger.debug("验证 %s 失败: %s", exe, e)
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND,
            executable=None,
            version=None,
            message=f"验证 {exe} 时出错: {e}",
        )


def detect(
    ssh_run_fn: SshRunFn,
    configured_path: str = "",
    timeout: int = 15,
) -> CondaDetectResult:
    """按优先级检测远端 conda 可执行文件。

    检测顺序（参考 Galaxy CondaContext.__init__ + find_conda_prefix）：
    1. configured_path 非空 → 直接验证
    2. which conda → 取 stdout → 验证
    3. 常见安装目录扫描
    4. 全部失败 → NOT_FOUND

    Args:
        ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
        configured_path: 用户配置的 conda 路径（优先级最高）
        timeout: 单次命令超时秒数

    Returns:
        CondaDetectResult
    """
    # 1. 用户配置路径
    if configured_path and configured_path.strip():
        result = _validate_conda(ssh_run_fn, configured_path.strip(), timeout)
        if result.status == CondaStatus.OK:
            logger.info("配置路径有效: %s", configured_path)
            return result
        logger.info("配置路径无效 (%s), 继续搜索", configured_path)

    # 2. which conda
    try:
        rc, stdout, _stderr = ssh_run_fn("which conda", timeout)
        if rc == 0 and stdout.strip():
            which_path = stdout.strip().splitlines()[0].strip()
            if which_path:
                result = _validate_conda(ssh_run_fn, which_path, timeout)
                if result.status in (CondaStatus.OK, CondaStatus.VERSION_PARSE_FAILED):
                    logger.info("which conda 找到: %s (status=%s)", which_path, result.status)
                    return result
    except Exception as e:
        logger.debug("which conda 失败: %s", e)

    # 3. 常见安装目录扫描
    for candidate in _COMMON_CONDA_PATHS:
        try:
            # 用 test -x 先检查可执行性，减少不必要的 --version 调用
            rc, _, _ = ssh_run_fn(
                f'test -x "$(eval echo {candidate})" && eval echo {candidate}',
                timeout,
            )
            if rc != 0:
                continue
            result = _validate_conda(ssh_run_fn, candidate, timeout)
            if result.status == CondaStatus.OK:
                logger.info("常见目录扫描命中: %s", candidate)
                return result
            if result.status == CondaStatus.VERSION_PARSE_FAILED:
                return result
        except Exception:
            continue

    # 4. 全部失败
    return CondaDetectResult(
        status=CondaStatus.NOT_FOUND,
        executable=None,
        version=None,
        message="未在远端检测到 conda，请安装 Miniforge 或手动指定路径",
    )


def can_install(
    ssh_run_fn: SshRunFn,
    install_dir: str = _DEFAULT_INSTALL_DIR,
    timeout: int = 15,
) -> tuple[bool, str]:
    """检查是否可以安装 Miniforge（参考 Galaxy can_install_conda）。

    检查项：
    - 架构为 x86_64（初期只支持）
    - 有 curl 或 wget
    - 目标目录不存在或为空

    Returns:
        (can_install, reason)
    """
    # 检查架构
    try:
        rc, stdout, _ = ssh_run_fn("uname -m", timeout)
        arch = stdout.strip() if rc == 0 else ""
        if arch not in ("x86_64", "aarch64"):
            return False, f"不支持的架构: {arch or '未知'}（仅支持 x86_64/aarch64）"
    except Exception as e:
        return False, f"无法检测架构: {e}"

    # 检查下载工具
    try:
        rc_curl, _, _ = ssh_run_fn("command -v curl", timeout)
        rc_wget, _, _ = ssh_run_fn("command -v wget", timeout)
        if rc_curl != 0 and rc_wget != 0:
            return False, "需要 curl 或 wget 用于下载安装脚本"
    except Exception as e:
        return False, f"无法检测下载工具: {e}"

    # 检查目标目录
    try:
        expanded_dir = install_dir.replace("~", "$HOME")
        rc, stdout, _ = ssh_run_fn(
            f'dir="$(eval echo {expanded_dir})"; '
            f'if [ -d "$dir" ] && [ "$(ls -A "$dir" 2>/dev/null)" ]; then '
            f'echo "exists"; else echo "ok"; fi',
            timeout,
        )
        if rc == 0 and "exists" in stdout:
            return False, f"目标目录 {install_dir} 已存在且非空"
    except Exception as e:
        return False, f"无法检查目标目录: {e}"

    return True, "可以安装"


def install_miniforge(
    ssh_run_fn: SshRunFn,
    install_dir: str = _DEFAULT_INSTALL_DIR,
    timeout: int = 600,
) -> CondaDetectResult:
    """在远端安装 Miniforge3（参考 Galaxy conda_auto_init）。

    流程：
    1. can_install 前置检查
    2. 下载 Miniforge3 安装脚本
    3. 静默安装到 install_dir
    4. 清理安装脚本
    5. 添加 bioconda channel + 设置 strict channel_priority
    6. 验证安装

    Args:
        ssh_run_fn: SSH 命令执行回调
        install_dir: 安装目录，默认 ~/.h2ometa/conda
        timeout: 总超时秒数

    Returns:
        CondaDetectResult
    """
    # 前置检查
    ok, reason = can_install(ssh_run_fn, install_dir)
    if not ok:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND,
            executable=None,
            version=None,
            message=f"无法安装: {reason}",
        )

    # 确定架构
    rc, stdout, _ = ssh_run_fn("uname -m", 15)
    arch = stdout.strip() if rc == 0 else "x86_64"
    url = _MINIFORGE_URL.replace("x86_64", arch)
    installer = "/tmp/miniforge_install.sh"

    # 下载
    try:
        rc_curl, _, _ = ssh_run_fn("command -v curl", 10)
        if rc_curl == 0:
            dl_cmd = f"curl -fsSL -o {installer} {url}"
        else:
            dl_cmd = f"wget -q -O {installer} {url}"

        rc, _, stderr = ssh_run_fn(dl_cmd, timeout)
        if rc != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND,
                executable=None,
                version=None,
                message=f"下载 Miniforge 失败: {stderr[:100]}",
            )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND,
            executable=None,
            version=None,
            message=f"下载 Miniforge 出错: {e}",
        )

    # 安装
    expanded_dir = install_dir.replace("~", "$HOME")
    install_cmd = (
        f'bash {installer} -b -p "$(eval echo {expanded_dir})"'
    )
    try:
        rc, _, stderr = ssh_run_fn(install_cmd, timeout)
        if rc != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND,
                executable=None,
                version=None,
                message=f"Miniforge 安装失败: {stderr[:100]}",
            )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND,
            executable=None,
            version=None,
            message=f"Miniforge 安装出错: {e}",
        )

    # 清理
    try:
        ssh_run_fn(f"rm -f {installer}", 10)
    except Exception:
        pass

    # 配置 channels
    conda_exe = f"{install_dir}/bin/conda"
    try:
        ssh_run_fn(f"{conda_exe} config --add channels bioconda", 30)
        ssh_run_fn(f"{conda_exe} config --set channel_priority strict", 30)
    except Exception as e:
        logger.warning("配置 bioconda channel 失败: %s", e)

    # 验证
    result = _validate_conda(ssh_run_fn, conda_exe, 15)
    if result.status == CondaStatus.OK:
        logger.info("Miniforge 安装成功: %s", result.executable)
    return result


def enable_libmamba(
    ssh_run_fn: SshRunFn,
    conda_path: str,
    timeout: int = 30,
) -> bool:
    """启用 libmamba solver。

    Args:
        ssh_run_fn: SSH 命令执行回调
        conda_path: conda 可执行文件路径
        timeout: 命令超时秒数

    Returns:
        True 如果成功
    """
    try:
        rc, _, _ = ssh_run_fn(
            f"{conda_path} config --set solver libmamba", timeout,
        )
        return rc == 0
    except Exception as e:
        logger.warning("enable_libmamba 失败: %s", e)
        return False


def rewrite_install_cmd(install_cmd: str, conda_executable: str) -> str:
    """将 install_cmd 中的裸 'conda' 替换为检测到的绝对路径。

    纯字符串替换，无状态。

    Args:
        install_cmd: 原始安装命令（如 "conda create -n fastp_env ..."）
        conda_executable: 检测到的 conda 绝对路径

    Returns:
        替换后的命令
    """
    if not conda_executable:
        return install_cmd

    stripped = install_cmd.lstrip()
    if not (stripped == "conda" or stripped.startswith("conda ")):
        return install_cmd

    prefix = install_cmd[: len(install_cmd) - len(stripped)]
    remainder = stripped[len("conda"):]
    return f"{prefix}{conda_executable}{remainder}"
