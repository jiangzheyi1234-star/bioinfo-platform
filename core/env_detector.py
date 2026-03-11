"""conda 环境检测与 Miniforge 自动安装模块。

纯 Python 模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现。
逻辑：有 conda → 用它；没有 → 装一个。
"""

import logging
import re
import shlex
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

# 远端常见 conda 安装目录（用户级）
_COMMON_CONDA_PATHS = [
    "~/anaconda3/bin/conda",
    "~/miniconda3/bin/conda",
    "~/miniforge3/bin/conda",
    "~/.h2ometa/conda/bin/conda",
]

# conda --version 输出正则: "conda 24.1.2"
_VERSION_RE = re.compile(r"conda\s+(\d+\.\d+(?:\.\d+)?)")


class CondaStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class CondaDetectResult:
    status: CondaStatus
    executable: Optional[str]   # 绝对路径，NOT_FOUND 时为 None
    version: Optional[str]      # "24.1.2"
    message: str                # 人类可读描述


def _validate_conda(ssh_run_fn: SshRunFn, exe: str, timeout: int = 15) -> CondaDetectResult:
    """验证 conda 可执行文件：运行 --version 并解析版本号。"""
    try:
        # 展开 ~ 为 $HOME（SSH 中直接执行 ~/xxx 可能不会展开）
        if exe.startswith("~"):
            exe_for_cmd = exe.replace("~/", "$HOME/", 1)
        else:
            exe_for_cmd = exe
        rc, stdout, stderr = ssh_run_fn(f"bash -c '{exe_for_cmd} --version'", timeout)
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
        # 如果使用了 $HOME，展开为实际路径
        final_exe = exe_for_cmd
        if exe_for_cmd.startswith("$HOME/"):
            try:
                rc2, stdout2, _ = ssh_run_fn(f"eval echo {exe_for_cmd}", 10)
                if rc2 == 0 and stdout2.strip():
                    final_exe = stdout2.strip()
            except Exception:
                pass
        return CondaDetectResult(
            status=CondaStatus.OK,
            executable=final_exe,
            version=version if m else None,
            message=f"检测到 conda {version if m else ''} ({final_exe})",
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
    timeout: int = 15,
) -> CondaDetectResult:
    """检测远端 conda 可执行文件（自动模式）。

    检测顺序：
    1. bash -ic 'which conda'（用户 shell 实际环境）
    2. 常见安装目录扫描（anaconda3/miniconda3/miniforge3/.h2ometa/conda）
    3. NOT_FOUND

    Args:
        ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
        timeout: 单次命令超时秒数

    Returns:
        CondaDetectResult
    """

    # Step 1: bash -ic 'which conda' — 用户 shell 实际环境（自动检测）
    try:
        rc, stdout, _stderr = ssh_run_fn(
            "bash -ic 'which conda' 2>/dev/null", timeout,
        )
        if rc == 0 and stdout.strip():
            which_path = stdout.strip().splitlines()[0].strip()
            if which_path and not which_path.startswith("which:"):
                result = _validate_conda(ssh_run_fn, which_path, timeout)
                if result.status == CondaStatus.OK:
                    logger.info("which conda 找到: %s", which_path)
                    return result
    except Exception as e:
        logger.debug("which conda 失败: %s", e)

    # Step 2: 常见安装目录扫描
    for candidate in _COMMON_CONDA_PATHS:
        try:
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
        except Exception:
            continue

    # Step 3: 全部失败
    return CondaDetectResult(
        status=CondaStatus.NOT_FOUND,
        executable=None,
        version=None,
        message="未在远端检测到 conda，请安装 Miniforge 或手动指定路径",
    )


def install_miniforge(
    ssh_run_fn: SshRunFn,
    timeout: int = 600,
) -> CondaDetectResult:
    """在远端安装 Miniforge3（默认路径 ~/miniforge3）。

    流程：
    1. 前置检查（架构、下载工具）
    2. 下载 Miniforge3 安装脚本
    3. 静默安装（Miniforge 默认装到 ~/miniforge3）
    4. 清理安装脚本
    5. 添加 bioconda channel + 设置 strict channel_priority
    6. 验证安装

    Args:
        ssh_run_fn: SSH 命令执行回调
        timeout: 总超时秒数

    Returns:
        CondaDetectResult
    """
    # ── 前置检查 ──
    # 检查架构
    try:
        rc, stdout, _ = ssh_run_fn("uname -m", 15)
        arch = stdout.strip() if rc == 0 else ""
        if arch not in ("x86_64", "aarch64"):
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND, executable=None, version=None,
                message=f"无法安装: 不支持的架构: {arch or '未知'}（仅支持 x86_64/aarch64）",
            )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"无法安装: 无法检测架构: {e}",
        )

    # 检查下载工具
    try:
        rc_curl, _, _ = ssh_run_fn("command -v curl", 15)
        rc_wget, _, _ = ssh_run_fn("command -v wget", 15)
        if rc_curl != 0 and rc_wget != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND, executable=None, version=None,
                message="无法安装: 需要 curl 或 wget 用于下载安装脚本",
            )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"无法安装: 无法检测下载工具: {e}",
        )

    # ── 下载 ──
    url = _MINIFORGE_URL.replace("x86_64", arch)
    installer = "/tmp/miniforge_install.sh"

    try:
        if rc_curl == 0:
            dl_cmd = f"curl -fsSL -o {installer} {url}"
        else:
            dl_cmd = f"wget -q -O {installer} {url}"

        rc, _, stderr = ssh_run_fn(dl_cmd, timeout)
        if rc != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND, executable=None, version=None,
                message=f"下载 Miniforge 失败: {stderr[:100]}",
            )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"下载 Miniforge 出错: {e}",
        )

    # ── 安装（-b 静默，不指定 -p，默认装到 ~/miniforge3） ──
    try:
        rc, _, stderr = ssh_run_fn(f"bash {installer} -b", timeout)
        if rc != 0:
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND, executable=None, version=None,
                message=f"Miniforge 安装失败: {stderr[:100]}",
            )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"Miniforge 安装出错: {e}",
        )

    # 清理
    try:
        ssh_run_fn(f"rm -f {installer}", 10)
    except Exception:
        pass

    # 配置 channels
    conda_exe = "~/miniforge3/bin/conda"
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


def infer_conda_root(conda_executable: str) -> str:
    """从 conda 可执行路径推断 conda 根目录。"""
    exe = (conda_executable or "").strip().rstrip("/")
    if not exe:
        return ""

    if exe.endswith("/bin/conda"):
        return exe[: -len("/bin/conda")]

    parts = exe.split("/")
    if len(parts) >= 3 and parts[-1] == "conda":
        return "/".join(parts[:-2])
    return ""


def expected_env_path(conda_executable: str, env_name: str) -> str:
    """给定 conda 可执行路径和环境名，返回预期的环境绝对路径。"""
    root = infer_conda_root(conda_executable)
    if not root or not env_name:
        return ""
    return f"{root}/envs/{env_name}"


def pin_create_env_to_conda_root(install_cmd: str, conda_executable: str) -> str:
    """将 `conda create -n/--name` 命令绑定到指定 conda 根目录下的 envs 目录。

    例如:
      /opt/conda/bin/conda create -n fastp_env -y
    -> /opt/conda/bin/conda create -p /opt/conda/envs/fastp_env -y
    """
    root = infer_conda_root(conda_executable)
    if not root or not install_cmd.strip():
        return install_cmd

    # 仅处理单条 conda create 命令，避免改写复合 shell 命令语义。
    if any(op in install_cmd for op in ("&&", "||", "|", ";", ">", "<")):
        return install_cmd

    try:
        tokens = shlex.split(install_cmd, posix=True)
    except Exception:
        return install_cmd

    if len(tokens) < 3:
        return install_cmd
    if not tokens[0].endswith("conda"):
        return install_cmd
    if tokens[1] != "create":
        return install_cmd
    if any(tok in ("-p", "--prefix") for tok in tokens):
        return install_cmd

    name_idx = -1
    env_name = ""
    for i, tok in enumerate(tokens):
        if tok in ("-n", "--name") and i + 1 < len(tokens):
            name_idx = i
            env_name = tokens[i + 1]
            break
        if tok.startswith("--name="):
            name_idx = i
            env_name = tok.split("=", 1)[1]
            break

    if not env_name:
        return install_cmd

    env_path = f"{root}/envs/{env_name}"
    if tokens[name_idx] in ("-n", "--name"):
        tokens[name_idx:name_idx + 2] = ["-p", env_path]
    else:
        tokens[name_idx:name_idx + 1] = ["-p", env_path]

    return " ".join(shlex.quote(tok) for tok in tokens)
