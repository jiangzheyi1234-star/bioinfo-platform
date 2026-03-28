"""conda 环境检测与 Miniforge 自动安装模块。

纯 Python 模块（不依赖 Qt），通过 ssh_run_fn 回调解耦 SSH 实现。
逻辑：有 conda → 用它；没有 → 装一个。
"""

import base64
import json
import logging
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.environment.h2o_env_paths import (
    H2O_CONDA_EXE,
    H2O_CONDA_HOME,
    H2O_CONDARC,
    h2o_env_prefix,
)
from core.environment.miniforge_condarc import CONDARC_TEMPLATE as _CONDARC_TEMPLATE
from core.environment.miniforge_release import (
    MINIFORGE_INSTALLER_MIN_BYTES,
    MINIFORGE_RELEASE_API_URL,
    MINIFORGE_SUPPORTED_ARCHES,
    build_miniforge_download_candidates,
)
from core.remote.server_capabilities import ServerCapabilities, SshRunFn

logger = logging.getLogger(__name__)

# conda --version 输出正则: "conda 24.1.2"
_VERSION_RE = re.compile(r"conda\s+(\d+\.\d+(?:\.\d+)?)")
_SHA256_RE = re.compile(r"\b([0-9a-fA-F]{64})\b")
_TAG_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class CondaStatus(Enum):
    OK = "ok"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class CondaDetectResult:
    status: CondaStatus
    executable: Optional[str]   # 绝对路径，NOT_FOUND 时为 None
    version: Optional[str]      # "24.1.2"
    message: str                # 人类可读描述


def _summarize_error(stdout: str, stderr: str, fallback: str) -> str:
    text = (stderr or stdout or fallback).strip()
    return text[:200] if text else fallback


def _cleanup_remote_files(ssh_run_fn: SshRunFn, *paths: str) -> None:
    quoted = " ".join(shlex.quote(path) for path in paths if path)
    if not quoted:
        return
    try:
        ssh_run_fn(f"rm -f {quoted}", 10)
    except Exception:
        logger.debug("清理远端临时文件失败: %s", paths)


def _mktemp_remote(ssh_run_fn: SshRunFn, template: str, timeout: int) -> str:
    rc, stdout, stderr = ssh_run_fn(f"mktemp {shlex.quote(template)}", timeout)
    if rc != 0 or not stdout.strip():
        raise RuntimeError(f"创建远端临时文件失败: {_summarize_error(stdout, stderr, template)}")
    return stdout.strip()


def _download_text(
    ssh_run_fn: SshRunFn,
    url: str,
    *,
    has_curl: bool,
    has_wget: bool,
    timeout: int,
) -> tuple[Optional[str], str]:
    errors: list[str] = []
    quoted_url = shlex.quote(url)
    if has_curl:
        rc, stdout, stderr = ssh_run_fn(
            f"curl -fsSL --connect-timeout 15 --max-time 60 {quoted_url}",
            timeout,
        )
        if rc == 0:
            return stdout, ""
        errors.append(f"curl: {_summarize_error(stdout, stderr, 'download failed')}")
    if has_wget:
        rc, stdout, stderr = ssh_run_fn(
            f"wget -q -O - --timeout=60 {quoted_url}",
            timeout,
        )
        if rc == 0:
            return stdout, ""
        errors.append(f"wget: {_summarize_error(stdout, stderr, 'download failed')}")
    return None, "; ".join(errors) or "download failed"


def _download_file(
    ssh_run_fn: SshRunFn,
    url: str,
    destination: str,
    *,
    has_curl: bool,
    has_wget: bool,
    timeout: int,
) -> tuple[bool, str]:
    errors: list[str] = []
    quoted_url = shlex.quote(url)
    quoted_destination = shlex.quote(destination)
    if has_curl:
        rc, stdout, stderr = ssh_run_fn(
            f"curl -fsSL --connect-timeout 15 --max-time 120 -o {quoted_destination} {quoted_url}",
            timeout,
        )
        if rc == 0:
            return True, ""
        errors.append(f"curl: {_summarize_error(stdout, stderr, 'download failed')}")
    if has_wget:
        rc, stdout, stderr = ssh_run_fn(
            f"wget -q --timeout=120 -O {quoted_destination} {quoted_url}",
            timeout,
        )
        if rc == 0:
            return True, ""
        errors.append(f"wget: {_summarize_error(stdout, stderr, 'download failed')}")
    return False, "; ".join(errors) or "download failed"


def _resolve_miniforge_release_tag(
    ssh_run_fn: SshRunFn,
    *,
    has_curl: bool,
    has_wget: bool,
    timeout: int,
) -> tuple[Optional[str], str]:
    payload, error = _download_text(
        ssh_run_fn,
        MINIFORGE_RELEASE_API_URL,
        has_curl=has_curl,
        has_wget=has_wget,
        timeout=timeout,
    )
    if payload is None:
        return None, error
    try:
        tag = str(json.loads(payload).get("tag_name") or "").strip()
    except Exception as exc:
        return None, f"invalid latest-release payload: {exc}"
    if not tag:
        return None, "tag_name missing in latest-release payload"
    if not _TAG_RE.match(tag):
        return None, f"invalid release tag: {tag}"
    return tag, ""


def _read_remote_file(ssh_run_fn: SshRunFn, path: str, timeout: int) -> tuple[Optional[str], str]:
    rc, stdout, stderr = ssh_run_fn(f"cat {shlex.quote(path)}", timeout)
    if rc != 0:
        return None, _summarize_error(stdout, stderr, "read failed")
    return stdout, ""


def _read_remote_file_size(ssh_run_fn: SshRunFn, path: str, timeout: int) -> tuple[Optional[int], str]:
    rc, stdout, stderr = ssh_run_fn(f"stat -c%s {shlex.quote(path)}", timeout)
    if rc != 0:
        return None, _summarize_error(stdout, stderr, "stat failed")
    try:
        return int(stdout.strip()), ""
    except Exception:
        return None, f"invalid stat output: {stdout.strip()[:100]}"


def _read_remote_shebang(ssh_run_fn: SshRunFn, path: str, timeout: int) -> tuple[Optional[str], str]:
    rc, stdout, stderr = ssh_run_fn(f"head -n 1 {shlex.quote(path)}", timeout)
    if rc != 0:
        return None, _summarize_error(stdout, stderr, "head failed")
    return stdout.strip(), ""


def _extract_sha256(contents: str) -> Optional[str]:
    match = _SHA256_RE.search(contents or "")
    if not match:
        return None
    return match.group(1).lower()


def _verify_remote_sha256(
    ssh_run_fn: SshRunFn,
    expected_sha256: str,
    path: str,
    timeout: int,
) -> tuple[bool, str]:
    rc, stdout, stderr = ssh_run_fn(
        f"printf '%s  %s\\n' {shlex.quote(expected_sha256)} {shlex.quote(path)} | sha256sum -c -",
        timeout,
    )
    if rc != 0:
        return False, _summarize_error(stdout, stderr, "sha256 verify failed")
    return True, ""


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
    """检测远端 H2OMeta 自管 conda 可执行文件（自动模式）。

    检测顺序：
    1. 固定路径 `~/.h2ometa/conda/bin/conda`
    2. NOT_FOUND

    Args:
        ssh_run_fn: SSH 命令执行回调 (cmd, timeout) -> (rc, stdout, stderr)
        timeout: 单次命令超时秒数

    Returns:
        CondaDetectResult
    """

    # Step 1: 固定自管路径检测
    try:
        result = _validate_conda(ssh_run_fn, H2O_CONDA_EXE, timeout)
        if result.status == CondaStatus.OK:
            logger.info("命中自管 conda: %s", result.executable)
            return result
    except Exception as e:
        logger.debug("检测自管 conda 失败: %s", e)

    # Step 2: 全部失败
    return CondaDetectResult(
        status=CondaStatus.NOT_FOUND,
        executable=None,
        version=None,
        message="未在远端检测到 H2OMeta 自管 conda，请先执行自动安装",
    )


def install_miniforge(
    ssh_run_fn: SshRunFn,
    caps: ServerCapabilities,
    timeout: int = 600,
) -> CondaDetectResult:
    """在远端安装 Miniforge3（固定路径 ~/.h2ometa/conda）。

    流程：
    1. 前置检查（架构、下载工具）
    2. 下载 Miniforge3 安装脚本
    3. 静默安装到 ~/.h2ometa/conda
    4. 清理安装脚本
    5. 写入受控 runtime condarc
    6. 验证安装

    Args:
        ssh_run_fn: SSH 命令执行回调
        timeout: 总超时秒数

    Returns:
        CondaDetectResult
    """
    arch = str(caps.arch or "").strip()
    if arch not in MINIFORGE_SUPPORTED_ARCHES:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"无法安装: 不支持的架构: {arch or '未知'}（仅支持 x86_64/aarch64）",
        )

    has_curl = bool(caps.has_curl)
    has_wget = bool(caps.has_wget)

    try:
        release_tag, resolve_error = _resolve_miniforge_release_tag(
            ssh_run_fn,
            has_curl=has_curl,
            has_wget=has_wget,
            timeout=min(timeout, 60),
        )
    except Exception as e:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"无法安装: 解析最新 Miniforge release 出错: {e}",
        )
    if not release_tag:
        return CondaDetectResult(
            status=CondaStatus.NOT_FOUND, executable=None, version=None,
            message=f"无法安装: 解析最新 Miniforge release 失败: {resolve_error}",
        )

    installer = ""
    checksum_file = ""
    download_failures: list[str] = []
    try:
        installer = _mktemp_remote(ssh_run_fn, "/tmp/miniforge_install.XXXXXX.sh", 15)
        checksum_file = _mktemp_remote(ssh_run_fn, "/tmp/miniforge_install.XXXXXX.sha256", 15)

        for candidate in build_miniforge_download_candidates(release_tag, arch):
            _cleanup_remote_files(ssh_run_fn, installer, checksum_file)
            ok, reason = _download_file(
                ssh_run_fn,
                candidate.installer_url,
                installer,
                has_curl=has_curl,
                has_wget=has_wget,
                timeout=timeout,
            )
            if not ok:
                download_failures.append(f"[{candidate.label}] installer download failed: {reason}")
                continue

            size, size_error = _read_remote_file_size(ssh_run_fn, installer, 15)
            if size is None:
                download_failures.append(f"[{candidate.label}] installer stat failed: {size_error}")
                continue
            if size < MINIFORGE_INSTALLER_MIN_BYTES:
                download_failures.append(
                    f"[{candidate.label}] installer too small: {size} bytes"
                )
                continue

            shebang, shebang_error = _read_remote_shebang(ssh_run_fn, installer, 15)
            if shebang is None:
                download_failures.append(f"[{candidate.label}] shebang read failed: {shebang_error}")
                continue
            if not shebang.startswith("#!"):
                download_failures.append(f"[{candidate.label}] installer shebang check failed: {shebang}")
                continue

            ok, reason = _download_file(
                ssh_run_fn,
                candidate.sha256_url,
                checksum_file,
                has_curl=has_curl,
                has_wget=has_wget,
                timeout=timeout,
            )
            if not ok:
                download_failures.append(f"[{candidate.label}] checksum download failed: {reason}")
                continue

            checksum_contents, checksum_error = _read_remote_file(ssh_run_fn, checksum_file, 15)
            if checksum_contents is None:
                download_failures.append(f"[{candidate.label}] checksum read failed: {checksum_error}")
                continue
            expected_sha256 = _extract_sha256(checksum_contents)
            if not expected_sha256:
                download_failures.append(f"[{candidate.label}] checksum parse failed")
                continue

            verified, verify_error = _verify_remote_sha256(ssh_run_fn, expected_sha256, installer, 30)
            if not verified:
                download_failures.append(f"[{candidate.label}] sha256 verify failed: {verify_error}")
                continue

            logger.info(
                "Miniforge installer verified: tag=%s source=%s url=%s",
                release_tag,
                candidate.label,
                candidate.installer_url,
            )
            break
        else:
            detail = " | ".join(download_failures) if download_failures else "no candidate sources available"
            return CondaDetectResult(
                status=CondaStatus.NOT_FOUND, executable=None, version=None,
                message=f"下载 Miniforge 失败: {detail}",
            )

        rc, _, stderr = ssh_run_fn(
            f"bash {shlex.quote(installer)} -b -p \"$(eval echo {H2O_CONDA_HOME})\"",
            timeout,
        )
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
    finally:
        _cleanup_remote_files(ssh_run_fn, installer, checksum_file)

    # 验证
    conda_exe = H2O_CONDA_EXE
    result = _validate_conda(ssh_run_fn, conda_exe, 15)
    if result.status == CondaStatus.OK:
        logger.info("Miniforge 安装成功: %s", result.executable)
        write_h2ometa_condarc(ssh_run_fn, timeout=30)
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
    """给定环境名返回统一工具环境路径（与 conda 根目录解耦）。"""
    _ = conda_executable  # 保持签名兼容，路径策略不再依赖 conda 根目录。
    return h2o_env_prefix(env_name)


def extract_env_name(install_cmd: str) -> str:
    """从 install_cmd 中提取 -n/--name 后的环境名。找不到返回空字符串。"""
    if any(op in install_cmd for op in ("&&", "||", "|", ";", ">", "<")):
        return ""
    try:
        tokens = shlex.split(install_cmd, posix=True)
    except Exception:
        return ""
    for i, tok in enumerate(tokens):
        if tok in ("-n", "--name") and i + 1 < len(tokens):
            return tokens[i + 1]
        if tok.startswith("--name="):
            return tok.split("=", 1)[1]
    return ""


def write_h2ometa_condarc(
    ssh_run_fn: SshRunFn,
    timeout: int = 15,
) -> None:
    """将受控 condarc 写到 H2OMeta runtime 目录。

    env_installer 在包装脚本中设置 CONDARC 指向此文件，确保：
    - channel 配置固定（conda-forge + bioconda, flexible priority）
    - 网络重试参数生效
    - 不受用户系统 ~/.condarc 干扰
    """
    try:
        ssh_run_fn("mkdir -p ~/.h2ometa/runtime", timeout)
        encoded = base64.b64encode(_CONDARC_TEMPLATE.encode()).decode()
        rc, _, stderr = ssh_run_fn(
            f"echo '{encoded}' | base64 -d > {H2O_CONDARC}",
            timeout,
        )
        if rc != 0:
            logger.warning("写入 condarc 失败: %s", stderr[:100])
        else:
            logger.info("已写入受控 condarc: %s", H2O_CONDARC)
    except Exception as e:
        logger.warning("write_h2ometa_condarc 出错: %s", e)


def pin_create_env_to_conda_root(
    install_cmd: str,
    conda_executable: str,
    override_prefix: str = "",
) -> str:
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

    env_path = override_prefix if override_prefix else f"{root}/envs/{env_name}"
    if tokens[name_idx] in ("-n", "--name"):
        tokens[name_idx:name_idx + 2] = ["-p", env_path]
    else:
        tokens[name_idx:name_idx + 1] = ["-p", env_path]

    return " ".join(shlex.quote(tok) for tok in tokens)
