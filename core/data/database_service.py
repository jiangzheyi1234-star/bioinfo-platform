"""数据库管理核心服务。

提供数据库 registry 加载、状态检测、安装命令生成、后台安装与日志/进度读取能力。
本模块属于 Core 层，不依赖 Qt。
"""

from __future__ import annotations

import base64
import re
import shlex
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from core.remote.server_capabilities import PreflightError, ServerCapabilities, SshRunFn


class DatabaseStatus(Enum):
    NOT_INSTALLED = "not_installed"
    INCOMPLETE = "incomplete"
    READY = "ready"
    INSTALLING = "installing"
    UNKNOWN = "unknown"


@dataclass
class DatabaseInfo:
    db_id: str
    name: str
    description: str
    category: str
    install_path: str
    size_mb: int
    tools: list[str] = field(default_factory=list)
    mirrors: list[dict[str, str]] = field(default_factory=list)
    integrity_check: dict[str, Any] = field(default_factory=dict)
    install_cmd: str = ""
    env_var: str = ""
    builtin: bool = False


@dataclass
class DatabaseCheckResult:
    db_id: str
    status: DatabaseStatus
    message: str = ""


def _expand_path(path: str) -> str:
    return path.replace("~", "$HOME", 1) if path.startswith("~") else path


def _quote(path: str) -> str:
    return shlex.quote(path)


def _normalize_relative_install_path(install_path: str) -> str:
    rel = str(install_path or "").strip().replace("\\", "/")
    if not rel:
        return ""
    rel_path = PurePosixPath(rel)
    if rel_path.is_absolute():
        return ""
    if any(part == ".." for part in rel_path.parts):
        return ""
    normalized = rel_path.as_posix().lstrip("./")
    if normalized.startswith("../") or normalized in {"", "."}:
        return ""
    return normalized


def _render_install_cmd(template: str, db_path: str) -> str:
    """Render install_cmd with a strict placeholder policy.

    We only allow `{{ db_path }}` replacement to avoid SSTI risks from
    untrusted YAML payloads.
    """
    rendered = re.sub(r"\{\{\s*db_path\s*\}\}", db_path, str(template or ""))
    if "{{" in rendered or "{%" in rendered or "{#" in rendered:
        raise ValueError("install_cmd 包含不受支持的模板语法，仅允许 {{ db_path }}")
    return rendered


class DatabaseService:
    INSTALL_BASE = "~/.h2ometa/db_installs"
    HEARTBEAT_STALE_SECONDS = 180

    def __init__(self, databases_yaml_path: str = ""):
        if databases_yaml_path:
            self._yaml_path = Path(databases_yaml_path)
        else:
            self._yaml_path = Path(__file__).resolve().parents[2] / "plugins" / "databases.yaml"
        self._registry: dict[str, DatabaseInfo] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        with open(self._yaml_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        databases = raw.get("databases", {})
        if not isinstance(databases, dict):
            return
        for db_id, node in databases.items():
            if not isinstance(node, dict):
                continue
            self._registry[db_id] = DatabaseInfo(
                db_id=str(db_id),
                name=str(node.get("name", db_id)),
                description=str(node.get("description", "")),
                category=str(node.get("category", "other")),
                install_path=str(node.get("install_path", "")),
                size_mb=int(node.get("size_mb", 0) or 0),
                tools=[str(v) for v in node.get("tools", []) if str(v).strip()],
                mirrors=[v for v in node.get("mirrors", []) if isinstance(v, dict)],
                integrity_check=node.get("integrity_check", {}) if isinstance(node.get("integrity_check", {}), dict) else {},
                install_cmd=str(node.get("install_cmd", "")),
                env_var=str(node.get("env_var", "")),
                builtin=bool(node.get("builtin", False)),
            )

    def list_all(self) -> list[DatabaseInfo]:
        return [db for db in self._registry.values() if not db.builtin]

    def list_by_category(self) -> dict[str, list[DatabaseInfo]]:
        grouped: dict[str, list[DatabaseInfo]] = {}
        for info in self.list_all():
            grouped.setdefault(info.category, []).append(info)
        return grouped

    def get_info(self, db_id: str) -> DatabaseInfo | None:
        return self._registry.get(db_id)

    @staticmethod
    def _normalized_override_path(overrides: dict[str, str] | None, db_id: str) -> str:
        if not isinstance(overrides, dict):
            return ""
        raw_value = str(overrides.get(db_id, "") or "").strip()
        if not raw_value:
            return ""
        normalized = PurePosixPath(raw_value.replace("\\", "/")).as_posix().strip()
        return normalized.rstrip("/") if normalized not in {"", "/"} else normalized

    def get_resolved_path(self, db_id: str, db_root: str) -> str:
        info = self.get_info(db_id)
        if info is None or info.builtin:
            return ""
        root = str(db_root or "").strip().rstrip("/")
        rel = _normalize_relative_install_path(info.install_path)
        if not root or not rel:
            return ""
        return f"{root}/{rel}"

    def resolve_effective_path(
        self,
        db_id: str,
        db_root: str,
        overrides: dict[str, str] | None = None,
    ) -> str:
        override_path = self._normalized_override_path(overrides, db_id)
        if override_path:
            return override_path
        return self.get_resolved_path(db_id, db_root)

    def is_installable(self, db_id: str) -> bool:
        info = self.get_info(db_id)
        return bool(info and not info.builtin and (info.install_cmd or info.mirrors))

    def check_status(
        self,
        ssh_run_fn: SshRunFn,
        db_id: str,
        db_root: str,
        overrides: dict[str, str] | None = None,
    ) -> DatabaseCheckResult:
        info = self.get_info(db_id)
        if info is None:
            return DatabaseCheckResult(db_id=db_id, status=DatabaseStatus.UNKNOWN, message="数据库未注册")
        db_path = self.resolve_effective_path(db_id, db_root, overrides=overrides)
        if not db_path:
            return DatabaseCheckResult(db_id=db_id, status=DatabaseStatus.NOT_INSTALLED, message="数据库路径未配置")
        return self.check_status_at_path(ssh_run_fn, db_id, db_path)

    def check_status_at_path(self, ssh_run_fn: SshRunFn, db_id: str, db_path: str) -> DatabaseCheckResult:
        info = self.get_info(db_id)
        if info is None:
            return DatabaseCheckResult(db_id=db_id, status=DatabaseStatus.UNKNOWN, message="数据库未注册")
        normalized_path = str(db_path or "").strip()
        if not normalized_path:
            return DatabaseCheckResult(db_id=db_id, status=DatabaseStatus.NOT_INSTALLED, message="数据库路径未配置")
        if not normalized_path.startswith("/"):
            return DatabaseCheckResult(db_id=db_id, status=DatabaseStatus.NOT_INSTALLED, message=f"数据库路径必须是绝对路径: {normalized_path}")

        qdb = _quote(normalized_path)
        rc, _, _ = ssh_run_fn(f"test -d {qdb}", 10)
        if rc != 0:
            return DatabaseCheckResult(db_id=db_id, status=DatabaseStatus.NOT_INSTALLED, message=f"目录不存在: {normalized_path}")

        return self._check_integrity_at_path(ssh_run_fn, info, normalized_path)

    def _check_integrity_at_path(
        self,
        ssh_run_fn: SshRunFn,
        info: DatabaseInfo,
        db_path: str,
    ) -> DatabaseCheckResult:
        qdb = _quote(db_path)
        status_file = info.integrity_check.get("status_file", ".install_ok")
        if status_file:
            rc, _, _ = ssh_run_fn(f"test -f {qdb}/{_quote(str(status_file))}", 10)
            if rc != 0:
                return DatabaseCheckResult(
                    db_id=info.db_id,
                    status=DatabaseStatus.NOT_INSTALLED,
                    message=f"缺少状态文件: {status_file}",
                )

        for kf in info.integrity_check.get("key_files", []):
            key = str(kf).strip()
            if not key:
                continue
            rc, _, _ = ssh_run_fn(f"test -e {qdb}/{_quote(key)}", 10)
            if rc != 0:
                return DatabaseCheckResult(db_id=info.db_id, status=DatabaseStatus.INCOMPLETE, message=f"缺少: {key}")

        min_size_mb = int(info.integrity_check.get("min_size_mb", 0) or 0)
        if min_size_mb > 0:
            rc, stdout, _ = ssh_run_fn(f"du -sm {qdb} 2>/dev/null | awk '{{print $1}}'", 15)
            try:
                actual_size_mb = int((stdout or "").strip()) if rc == 0 else 0
            except ValueError:
                actual_size_mb = 0
            if actual_size_mb < min_size_mb:
                return DatabaseCheckResult(
                    db_id=info.db_id,
                    status=DatabaseStatus.INCOMPLETE,
                    message=f"数据库大小不足: {actual_size_mb} MB < {min_size_mb} MB",
                )

        return DatabaseCheckResult(db_id=info.db_id, status=DatabaseStatus.READY)

    def check_all(
        self,
        ssh_run_fn: SshRunFn,
        db_root: str,
        overrides: dict[str, str] | None = None,
    ) -> list[DatabaseCheckResult]:
        return [self.check_status(ssh_run_fn, info.db_id, db_root, overrides=overrides) for info in self.list_all()]

    def generate_install_commands(
        self,
        caps: ServerCapabilities,
        db_id: str,
        db_root: str,
        mirror_index: int = 0,
    ) -> list[str]:
        info = self.get_info(db_id)
        if info is None:
            raise ValueError(f"未知数据库: {db_id}")
        if info.builtin:
            raise ValueError(f"builtin 数据库不支持安装: {db_id}")
        db_path = self.get_resolved_path(db_id, db_root)
        if not db_path:
            raise ValueError("db_root 未设置")

        commands = [f"mkdir -p {_quote(db_path)}"]

        if info.install_cmd:
            rendered = _render_install_cmd(info.install_cmd, db_path=db_path)
            commands.append(rendered)
        elif info.mirrors:
            idx = mirror_index if 0 <= mirror_index < len(info.mirrors) else 0
            url = str(info.mirrors[idx].get("url", "")).strip()
            if not url:
                raise ValueError(f"数据库 {db_id} 缺少可用镜像 URL")
            commands.append(f"cd {_quote(db_path)}")
            if caps.downloader == "curl":
                commands.append(
                    f"curl -fL --progress-bar {_quote(url)} -o archive.tar.gz"
                )
            else:
                commands.append(f"wget -c --progress=dot:giga {_quote(url)} -O archive.tar.gz")
            commands.append("tar xzf archive.tar.gz")
            commands.append("rm -f archive.tar.gz")
        else:
            raise ValueError(f"数据库 {db_id} 缺少 install_cmd 和镜像配置")

        commands.append(f"touch {_quote(db_path)}/.install_ok")
        return commands

    def submit_install(
        self,
        ssh_run_fn: SshRunFn,
        caps: ServerCapabilities,
        db_id: str,
        db_root: str,
        conda_exe: str = "",
        mirror_index: int = 0,
    ) -> dict[str, str]:
        del conda_exe  # 预留兼容参数
        failures = caps.failures()
        if failures:
            raise PreflightError(failures)

        commands = self.generate_install_commands(caps, db_id, db_root, mirror_index=mirror_index)
        task_dir = f"{self.INSTALL_BASE}/{db_id}"
        job_id = f"h2o_dbinstall_{db_id}"
        current = self.check_install_status(ssh_run_fn, task_dir)
        if current.get("status") == "RUNNING" and self.is_heartbeat_fresh(current.get("heartbeat", "")):
            return {"job_id": job_id, "task_dir": task_dir, "reused": "1"}

        expanded_task_dir = f'"$(eval echo {_quote(_expand_path(task_dir))})"'
        rc, _, stderr = ssh_run_fn(f"mkdir -p {expanded_task_dir}", 15)
        if rc != 0:
            raise RuntimeError(f"创建安装目录失败: {stderr[:200]}")

        commands_block = "\n".join(commands)
        wrapper = f"""#!/bin/bash
set -euo pipefail
TASK_DIR="$(eval echo {_quote(_expand_path(task_dir))})"
STATUS_FILE="$TASK_DIR/status.txt"
LOG_FILE="$TASK_DIR/task.log"
EXIT_CODE_FILE="$TASK_DIR/exit_code.txt"
HEARTBEAT_FILE="$TASK_DIR/heartbeat.txt"

echo "RUNNING" > "$STATUS_FILE"
_heartbeat() {{ while true; do date +%s > "$HEARTBEAT_FILE"; sleep 30; done; }}
_heartbeat &
HB_PID=$!

_cleanup() {{
    local ec=$?
    kill $HB_PID 2>/dev/null || true
    echo "$ec" > "$EXIT_CODE_FILE"
    if [ "$ec" -eq 0 ]; then
        echo "DONE" > "$STATUS_FILE"
    else
        echo "FAILED" > "$STATUS_FILE"
    fi
}}
trap _cleanup EXIT

exec > "$LOG_FILE" 2>&1

{commands_block}
"""

        script_path = f"{task_dir}/install.sh"
        expanded_script_path = f'"$(eval echo {_quote(_expand_path(script_path))})"'
        encoded = base64.b64encode(wrapper.encode("utf-8")).decode("ascii")
        rc, _, stderr = ssh_run_fn(f"echo {_quote(encoded)} | base64 -d > {expanded_script_path}", 15)
        if rc != 0:
            raise RuntimeError(f"写入安装脚本失败: {stderr[:200]}")

        ssh_run_fn(
            f"rm -f {expanded_task_dir}/status.txt {expanded_task_dir}/exit_code.txt {expanded_task_dir}/heartbeat.txt",
            10,
        )
        if current.get("screen_running"):
            ssh_run_fn(f"screen -S {_quote(job_id)} -X quit 2>/dev/null || true", 10)
        rc, _, stderr = ssh_run_fn(f"screen -dmS {_quote(job_id)} bash {expanded_script_path}", 15)
        if rc != 0:
            raise RuntimeError(f"启动安装任务失败: {stderr[:200]}")

        return {"job_id": job_id, "task_dir": task_dir}

    def check_install_status(self, ssh_run_fn: SshRunFn, task_dir: str) -> dict[str, str]:
        expanded_task_dir = f'"$(eval echo {_quote(_expand_path(task_dir))})"'
        rc, status_out, _ = ssh_run_fn(f"cat {expanded_task_dir}/status.txt 2>/dev/null", 10)
        status = status_out.strip() if rc == 0 else ""

        rc, exit_out, _ = ssh_run_fn(f"cat {expanded_task_dir}/exit_code.txt 2>/dev/null", 10)
        exit_code = exit_out.strip() if rc == 0 else ""

        rc, heartbeat_out, _ = ssh_run_fn(f"cat {expanded_task_dir}/heartbeat.txt 2>/dev/null", 10)
        heartbeat = heartbeat_out.strip() if rc == 0 else ""
        heartbeat_age_sec = self.heartbeat_age_seconds(heartbeat)

        if status == "DONE" or exit_code == "0":
            return {"status": "DONE", "exit_code": exit_code or "0", "heartbeat": heartbeat, "heartbeat_age_sec": str(heartbeat_age_sec or ""), "screen_running": ""}
        if status == "FAILED":
            return {"status": "FAILED", "exit_code": exit_code, "heartbeat": heartbeat, "heartbeat_age_sec": str(heartbeat_age_sec or ""), "screen_running": ""}
        if status == "RUNNING":
            rc_screen, _, _ = ssh_run_fn(f"screen -ls | grep -q {_quote(f'h2o_dbinstall_{Path(task_dir).name}')}", 10)
            return {
                "status": "RUNNING",
                "exit_code": exit_code,
                "heartbeat": heartbeat,
                "heartbeat_age_sec": str(heartbeat_age_sec or ""),
                "screen_running": "1" if rc_screen == 0 else "",
            }

        job_id = f"h2o_dbinstall_{Path(task_dir).name}"
        rc, _, _ = ssh_run_fn(f"screen -ls | grep -q {_quote(job_id)}", 10)
        if rc == 0:
            return {
                "status": "RUNNING",
                "exit_code": exit_code,
                "heartbeat": heartbeat,
                "heartbeat_age_sec": str(heartbeat_age_sec or ""),
                "screen_running": "1",
            }
        if exit_code and exit_code != "0":
            return {
                "status": "FAILED",
                "exit_code": exit_code,
                "heartbeat": heartbeat,
                "heartbeat_age_sec": str(heartbeat_age_sec or ""),
                "screen_running": "",
            }
        return {
            "status": "",
            "exit_code": exit_code,
            "heartbeat": heartbeat,
            "heartbeat_age_sec": str(heartbeat_age_sec or ""),
            "screen_running": "",
        }

    def read_install_log(self, ssh_run_fn: SshRunFn, task_dir: str, tail: int = 50) -> str:
        expanded_task_dir = f'"$(eval echo {_quote(_expand_path(task_dir))})"'
        rc, stdout, _ = ssh_run_fn(f"tail -n {int(tail)} {expanded_task_dir}/task.log 2>/dev/null", 10)
        return stdout if rc == 0 else ""

    def parse_progress(self, log_text: str) -> dict[str, Any]:
        matches = re.findall(r"(\d+)%\s+([\d.]+[KMG]?(?:/s)?)?\s*([\dhms]+)?", log_text or "")
        if not matches:
            return {}
        last = matches[-1]
        result: dict[str, Any] = {"percent": int(last[0])}
        if last[1]:
            speed = str(last[1]).strip()
            if speed and not speed.endswith("/s"):
                speed = f"{speed}/s"
            result["speed"] = speed
        if last[2]:
            result["eta"] = last[2]
        return result

    @classmethod
    def heartbeat_age_seconds(cls, heartbeat_value: str) -> int | None:
        try:
            return max(0, int(time.time()) - int(str(heartbeat_value or "").strip()))
        except Exception:
            return None

    @classmethod
    def is_heartbeat_fresh(cls, heartbeat_value: str, stale_seconds: int | None = None) -> bool:
        age = cls.heartbeat_age_seconds(heartbeat_value)
        if age is None:
            return False
        threshold = cls.HEARTBEAT_STALE_SECONDS if stale_seconds is None else int(stale_seconds)
        return age <= threshold

    def verify_integrity(
        self,
        ssh_run_fn: SshRunFn,
        db_id: str,
        db_root: str,
        overrides: dict[str, str] | None = None,
    ) -> DatabaseCheckResult:
        return self.check_status(ssh_run_fn, db_id, db_root, overrides=overrides)

    def verify_integrity_at_path(
        self,
        ssh_run_fn: SshRunFn,
        db_id: str,
        db_path: str,
    ) -> DatabaseCheckResult:
        return self.check_status_at_path(ssh_run_fn, db_id, db_path)
