"""Remote Nextflow/Java resolution helpers for non-interactive SSH execution."""

from __future__ import annotations

import re
import shlex
from typing import Any

SHELL_TIMEOUT = 20
MIN_RUNNABLE_NEXTFLOW_VERSION = (25, 4, 0)
RECOMMENDED_NEXTFLOW_VERSION = (26, 4, 0)

_COMMON_NEXTFLOW_PATHS = (
    "$HOME/.local/bin/nextflow",
    "/usr/local/bin/nextflow",
    "/opt/nextflow/nextflow",
)

_JAVA_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


def _run_shell(ssh_run_fn: Any, script: str, timeout: int = SHELL_TIMEOUT) -> tuple[int, str, str]:
    return ssh_run_fn(f"bash -lc {shlex.quote(script)}", timeout)


def _extract_error(stdout: str, stderr: str, fallback: str) -> str:
    text = (stderr or stdout or fallback).strip()
    return text[:200] if text else fallback


def _major_from_java_version(raw: str) -> int | None:
    match = _JAVA_VERSION_RE.search(str(raw or ""))
    if not match:
        return None
    major = match.group(1)
    if not major:
        return None
    value = int(major)
    if value == 1 and match.group(2):
        return int(match.group(2))
    return value


def _parse_nextflow_version(raw: str) -> tuple[int, int, int] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def _version_gte(left: tuple[int, int, int] | None, right: tuple[int, int, int]) -> bool:
    return left is not None and left >= right


def resolve_remote_java(ssh_run_fn: Any, timeout: int = SHELL_TIMEOUT) -> dict[str, Any]:
    candidates = ({"cmd": "java", "home": "", "source": "path"},)
    first_found_failure: dict[str, Any] | None = None
    for candidate in candidates:
        cmd = candidate["cmd"]
        rc, stdout, stderr = _run_shell(
            ssh_run_fn,
            f'if command -v {cmd} >/dev/null 2>&1; then {cmd} -version 2>&1 | awk "NR==1{{print $0; exit}}"; fi',
            timeout,
        )
        version_line = str(stdout or "").strip()
        if rc != 0 or not version_line:
            continue
        major = _major_from_java_version(version_line)
        home = str(candidate["home"] or "").strip()
        if not home and cmd == "java":
            rc_home, stdout_home, _stderr_home = _run_shell(
                ssh_run_fn,
                'JAVA_BIN="$(readlink -f "$(command -v java)")"; dirname "$(dirname "$JAVA_BIN")"',
                timeout,
            )
            if rc_home == 0 and stdout_home.strip():
                home = stdout_home.strip()
        path = cmd if cmd != "java" else "java"
        if cmd == "java":
            rc_path, stdout_path, _stderr_path = _run_shell(
                ssh_run_fn,
                'readlink -f "$(command -v java)"',
                timeout,
            )
            if rc_path == 0 and stdout_path.strip():
                path = stdout_path.strip()
        supported = major is not None and 17 <= major <= 25
        item = {
            "available": True,
            "usable": supported,
            "supported": supported,
            "version": version_line,
            "major": major,
            "path": path,
            "home": home,
            "source": candidate["source"],
            "message": "已检测到 Java，可用于运行 Nextflow"
            if supported
            else "已检测到 Java，但版本不满足 Nextflow 要求（需 17-25）",
        }
        if supported:
            return item
        if first_found_failure is None:
            first_found_failure = item
    if first_found_failure is not None:
        return first_found_failure
    return {
        "available": False,
        "usable": False,
        "supported": False,
        "version": "",
        "major": None,
        "path": "",
        "home": "",
        "source": "",
        "message": "未检测到 Java，无法运行 Nextflow",
    }


def resolve_remote_nextflow(ssh_run_fn: Any, timeout: int = SHELL_TIMEOUT) -> dict[str, Any]:
    candidate_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, str]] = [
        {
            "probe": 'NF_BIN="$(type -P nextflow 2>/dev/null || true)"; '
            'if [ -n "$NF_BIN" ] && [ -x "$NF_BIN" ]; then readlink -f "$NF_BIN" 2>/dev/null || printf "%s\\n" "$NF_BIN"; fi',
            "source": "path",
        }
    ]
    candidates.extend(
        {
            "probe": (
                f'NF_BIN="{path}"; '
                'if [ -x "$NF_BIN" ]; then readlink -f "$NF_BIN" 2>/dev/null || printf "%s\\n" "$NF_BIN"; fi'
            ),
            "source": "fixed_path",
        }
        for path in _COMMON_NEXTFLOW_PATHS
    )

    first_found_failure: dict[str, Any] | None = None
    for candidate in candidates:
        rc_found, stdout_found, _stderr_found = _run_shell(
            ssh_run_fn,
            candidate["probe"],
            timeout,
        )
        raw_path = str(stdout_found or "").strip()
        found = rc_found == 0 and bool(raw_path) and raw_path.startswith("/")
        if not found:
            continue
        quoted_path = shlex.quote(raw_path)
        rc_version, stdout_version, _stderr_version = _run_shell(
            ssh_run_fn,
            f"""{quoted_path} -version 2>/dev/null | awk '/version/ {{print $NF; exit}}'""",
            timeout,
        )
        version = str(stdout_version or "").strip() if rc_version == 0 else ""
        parsed_version = _parse_nextflow_version(version)
        meets_minimum = _version_gte(parsed_version, MIN_RUNNABLE_NEXTFLOW_VERSION)
        meets_recommended = _version_gte(parsed_version, RECOMMENDED_NEXTFLOW_VERSION)
        agent_mode_supported = meets_recommended
        rc_info, stdout_info, stderr_info = _run_shell(ssh_run_fn, f"{quoted_path} info", timeout)
        if rc_info == 0:
            if not meets_minimum:
                message = (
                    f"已解析 Nextflow 绝对路径，但版本 {version or '<unknown>'} 低于最低要求 25.04.0；请先显式升级后再继续"
                )
            elif meets_recommended:
                message = f"已解析 Nextflow 绝对路径，可通过 launcher 脚本执行：{raw_path}"
            else:
                message = (
                    f"已解析 Nextflow 绝对路径，可通过 launcher 脚本执行：{raw_path}；"
                    "当前版本可运行，但低于推荐的 26.04.0，NXF_AGENT_MODE 将保持关闭"
                )
            candidate_rows.append(
                {
                    "path": raw_path,
                    "command": raw_path,
                    "source": candidate["source"],
                    "version": version,
                    "usable": meets_minimum,
                    "meets_minimum": meets_minimum,
                    "recommended": meets_recommended,
                    "agent_mode_supported": agent_mode_supported,
                    "upgrade_recommended": meets_minimum and not meets_recommended,
                    "message": message,
                }
            )
            return {
                "available": True,
                "usable": meets_minimum,
                "version": version,
                "path": raw_path,
                "command": raw_path,
                "source": candidate["source"],
                "minimum_required": "25.04.0",
                "recommended_version": "26.04.0",
                "meets_minimum": meets_minimum,
                "recommended": meets_recommended,
                "upgrade_recommended": meets_minimum and not meets_recommended,
                "agent_mode_supported": agent_mode_supported,
                "candidates": candidate_rows,
                "message": message,
            }
        detail = _extract_error(stdout_info, stderr_info, "Nextflow health check failed")
        candidate_rows.append(
            {
                "path": raw_path,
                "command": raw_path,
                "source": candidate["source"],
                "version": version,
                "usable": False,
                "meets_minimum": meets_minimum,
                "recommended": meets_recommended,
                "agent_mode_supported": False,
                "upgrade_recommended": False,
                "message": f"已解析 Nextflow 绝对路径，但当前不可正常调用：{detail}",
            }
        )
        if first_found_failure is None:
            first_found_failure = {
                "available": True,
                "usable": False,
                "version": "",
                "path": raw_path,
                "command": raw_path,
                "source": candidate["source"],
                "minimum_required": "25.04.0",
                "recommended_version": "26.04.0",
                "meets_minimum": False,
                "recommended": False,
                "upgrade_recommended": False,
                "agent_mode_supported": False,
                "candidates": candidate_rows,
                "message": f"已解析 Nextflow 绝对路径，但当前不可正常调用：{detail}",
            }
    if first_found_failure is not None:
        first_found_failure["candidates"] = candidate_rows
        return first_found_failure
    return {
        "available": False,
        "usable": False,
        "version": "",
        "path": "",
        "command": "",
        "source": "",
        "minimum_required": "25.04.0",
        "recommended_version": "26.04.0",
        "meets_minimum": False,
        "recommended": False,
        "upgrade_recommended": False,
        "agent_mode_supported": False,
        "candidates": [],
        "message": "未检测到 Nextflow",
    }


def build_runtime_env_exports(java_info: dict[str, Any]) -> str:
    home = str(java_info.get("home") or "").strip()
    if not home:
        return ""
    quoted_home = shlex.quote(home)
    return f"export NXF_JAVA_HOME={quoted_home}\n"


def resolve_persisted_runtime_binding(
    ssh_run_fn: Any,
    resolved_runtime: dict[str, Any],
    timeout: int = SHELL_TIMEOUT,
) -> dict[str, Any]:
    verification_status = str(resolved_runtime.get("verification_status") or "").strip()
    if verification_status != "verified":
        raise RuntimeError("已保存的 Runtime 配置未完成验证；请先重新执行一键配置并完成复检")

    nextflow_path = str(resolved_runtime.get("nextflow_path") or "").strip()
    nextflow_command = str(resolved_runtime.get("nextflow_command") or nextflow_path).strip()
    java_home = str(resolved_runtime.get("java_home") or "").strip()
    java_path = str(resolved_runtime.get("java_path") or "").strip()
    if not nextflow_path.startswith("/"):
        raise RuntimeError("已保存的 Runtime 配置缺少固定 Nextflow 绝对路径；请重新检测并保存")
    if not java_home.startswith("/"):
        raise RuntimeError("已保存的 Runtime 配置缺少固定 Java HOME；请重新检测并保存")
    java_bin = java_path if java_path.startswith("/") else f"{java_home.rstrip('/')}/bin/java"
    if not java_bin.startswith("/"):
        raise RuntimeError("已保存的 Runtime 配置缺少固定 Java 可执行路径；请重新检测并保存")

    quoted_nextflow = shlex.quote(nextflow_path)
    rc_version, stdout_version, _stderr_version = _run_shell(
        ssh_run_fn,
        f"""{quoted_nextflow} -version 2>/dev/null | awk '/version/ {{print $NF; exit}}'""",
        timeout,
    )
    version = str(stdout_version or "").strip() if rc_version == 0 else ""
    parsed_version = _parse_nextflow_version(version)
    meets_minimum = _version_gte(parsed_version, MIN_RUNNABLE_NEXTFLOW_VERSION)
    meets_recommended = _version_gte(parsed_version, RECOMMENDED_NEXTFLOW_VERSION)
    rc_info, stdout_info, stderr_info = _run_shell(ssh_run_fn, f"{quoted_nextflow} info", timeout)
    if rc_info != 0:
        detail = _extract_error(stdout_info, stderr_info, "Nextflow health check failed")
        raise RuntimeError(f"已保存的 Nextflow 路径当前不可正常调用：{detail}")
    if not meets_minimum:
        raise RuntimeError(
            f"已保存的 Nextflow 版本 {version or '<unknown>'} 低于最低要求 25.04.0；请先显式升级并重新验证"
        )

    quoted_java = shlex.quote(java_bin)
    rc_java, stdout_java, stderr_java = _run_shell(
        ssh_run_fn,
        f'{quoted_java} -version 2>&1 | awk "NR==1{{print $0; exit}}"',
        timeout,
    )
    version_line = str(stdout_java or "").strip()
    if rc_java != 0 or not version_line:
        detail = _extract_error(stdout_java, stderr_java, "Java health check failed")
        raise RuntimeError(f"已保存的 Java 路径当前不可正常调用：{detail}")
    major = _major_from_java_version(version_line)
    if major is None or not 17 <= major <= 25:
        raise RuntimeError("已保存的 Java 版本不满足 Nextflow 要求（需 17-25）；请先修复并重新验证")

    return {
        "nextflow_path": nextflow_path,
        "nextflow_command": nextflow_command if nextflow_command.startswith("/") else nextflow_path,
        "nextflow_version": version,
        "java_home": java_home,
        "java_path": java_bin,
        "java_version": version_line,
        "agent_mode_supported": meets_recommended,
    }
