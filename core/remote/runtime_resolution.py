"""Remote Nextflow/Java resolution helpers for non-interactive SSH execution."""

from __future__ import annotations

import re
import shlex
from typing import Any

SHELL_TIMEOUT = 20

_COMMON_NEXTFLOW_PATHS = (
    "$HOME/.local/bin/nextflow",
    "/usr/local/bin/nextflow",
    "/opt/nextflow/nextflow",
)

_COMMON_CONDA_COMMANDS = (
    "conda run -n base nextflow",
    "$HOME/miniconda3/bin/conda run -n base nextflow",
    "$HOME/anaconda3/bin/conda run -n base nextflow",
    "$HOME/mambaforge/bin/conda run -n base nextflow",
    "$HOME/miniforge3/bin/conda run -n base nextflow",
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


def resolve_remote_java(ssh_run_fn: Any, timeout: int = SHELL_TIMEOUT) -> dict[str, Any]:
    candidates = (
        {"cmd": '$NXF_JAVA_HOME/bin/java', "home": "$NXF_JAVA_HOME", "source": "nxf_java_home"},
        {"cmd": '$JAVA_HOME/bin/java', "home": "$JAVA_HOME", "source": "java_home"},
        {"cmd": "java", "home": "", "source": "path"},
    )
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
        supported = major is not None and 17 <= major <= 25
        item = {
            "available": True,
            "usable": supported,
            "supported": supported,
            "version": version_line,
            "major": major,
            "path": cmd if cmd != "java" else "java",
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
    candidates: list[dict[str, str]] = [{"cmd": "nextflow", "path_expr": 'command -v nextflow', "source": "path"}]
    candidates.extend({"cmd": path, "path_expr": f'printf "%s\\n" {shlex.quote(path)}', "source": "fixed_path"} for path in _COMMON_NEXTFLOW_PATHS)
    candidates.extend({"cmd": cmd, "path_expr": f'printf "%s\\n" {shlex.quote(cmd)}', "source": "conda_fallback"} for cmd in _COMMON_CONDA_COMMANDS)

    first_found_failure: dict[str, Any] | None = None
    for candidate in candidates:
        command = candidate["cmd"]
        path_expr = candidate["path_expr"]
        rc_found, stdout_found, _stderr_found = _run_shell(
            ssh_run_fn,
            f'if {command} -version >/dev/null 2>&1; then {path_expr}; fi',
            timeout,
        )
        raw_path = str(stdout_found or "").strip()
        found = rc_found == 0 and bool(raw_path)
        if not found:
            continue
        rc_info, stdout_info, stderr_info = _run_shell(ssh_run_fn, f"{command} info", timeout)
        if rc_info == 0:
            rc_version, stdout_version, _stderr_version = _run_shell(
                ssh_run_fn,
                f"""{command} -version 2>/dev/null | awk '/version/ {{print $NF; exit}}'""",
                timeout,
            )
            version = str(stdout_version or "").strip() if rc_version == 0 else ""
            return {
                "available": True,
                "usable": True,
                "version": version,
                "path": raw_path,
                "command": command,
                "source": candidate["source"],
                "message": "已检测到 Nextflow，可直接使用",
            }
        detail = _extract_error(stdout_info, stderr_info, "Nextflow health check failed")
        if first_found_failure is None:
            first_found_failure = {
                "available": True,
                "usable": False,
                "version": "",
                "path": raw_path,
                "command": command,
                "source": candidate["source"],
                "message": f"已检测到 Nextflow，但当前不可正常调用：{detail}",
            }
    if first_found_failure is not None:
        return first_found_failure
    return {
        "available": False,
        "usable": False,
        "version": "",
        "path": "",
        "command": "",
        "source": "",
        "message": "未检测到 Nextflow",
    }


def build_runtime_env_exports(java_info: dict[str, Any]) -> str:
    home = str(java_info.get("home") or "").strip()
    if not home:
        return ""
    quoted_home = shlex.quote(home)
    return (
        f"export NXF_JAVA_HOME={quoted_home}\n"
        f"export JAVA_HOME={quoted_home}\n"
        'export PATH="$JAVA_HOME/bin:$PATH"\n'
    )
