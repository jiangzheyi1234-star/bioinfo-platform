from __future__ import annotations

import posixpath
import shlex
from typing import Callable

from config import get_config
from core.data.database_service import DatabaseCheckResult, DatabaseInfo, DatabaseStatus


class DatabaseRemoteOpsMixin:
    def _get_db_root(self) -> str:
        return str(self._db_root_value or "").strip()

    def _get_database_overrides(self) -> dict[str, str]:
        cfg = get_config()
        databases = cfg.get("databases", {})
        if not isinstance(databases, dict):
            return {}
        overrides = databases.get("overrides", {})
        if not isinstance(overrides, dict):
            return {}
        return {str(k): str(v) for k, v in overrides.items()}

    def _get_database_install_target_path(self, db_id: str) -> str:
        return self._database_service.resolve_binding_value(db_id, self._get_db_root())

    def _check_database_path_remote(self, info: DatabaseInfo, db_path: str) -> DatabaseCheckResult:
        if info.builtin:
            return DatabaseCheckResult(db_id=info.db_id, status=DatabaseStatus.UNKNOWN, message="builtin 数据库")

        expanded = self._normalize_remote_path(self._expand_remote_path(str(db_path or "").strip()) or str(db_path or "").strip())
        candidate = self._database_service.binding_value_from_storage_root(info.db_id, expanded)
        return self._database_service.verify_integrity_at_path(
            self._make_ssh_run_fn(),
            info.db_id,
            candidate,
            require_status_file=False,
        )

    def _check_database_status(self, info: DatabaseInfo) -> DatabaseCheckResult:
        return self._database_service.check_status(
            self._make_ssh_run_fn(),
            info.db_id,
            self._get_db_root(),
            overrides=self._get_database_overrides(),
        )

    def _run_ssh(self, cmd: str, timeout: int = 10) -> tuple[int, str, str]:
        return self._make_ssh_run_fn()(cmd, timeout)

    def _list_remote_directories(self, raw_path: str) -> tuple[bool, str, list[str], str]:
        resolved = self._expand_remote_path(raw_path)
        if not resolved:
            return False, "", [], f"无法解析远程路径: {raw_path}"
        if not resolved.startswith("/"):
            return False, "", [], f"目录必须是绝对路径: {resolved}"
        resolved = self._normalize_remote_path(resolved)
        qpath = shlex.quote(resolved)
        rc_exists, _, _ = self._run_ssh(f"test -d {qpath}", 10)
        if rc_exists != 0:
            return False, "", [], f"目录不存在: {resolved}"
        cmd = f"find {qpath} -mindepth 1 -maxdepth 1 -type d -printf '%f\\n' | LC_ALL=C sort"
        rc, stdout, stderr = self._run_ssh(cmd, 12)
        if rc != 0:
            return False, "", [], f"读取目录失败: {stderr.strip() or resolved}"
        dirs = [line.strip() for line in stdout.splitlines() if line.strip()]
        return True, resolved, dirs, ""

    def _list_remote_directories_async(self, raw_path: str, done_cb: Callable[[bool, str, list[str], str], None]) -> None:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            done_cb(False, "", [], "请先连接 SSH，再浏览远程目录。")
            return

        started = self._start_async_task(
            "db_list_dirs",
            lambda: self._list_remote_directories(raw_path),
            on_success=lambda payload: done_cb(*payload),
            on_error=lambda err: done_cb(False, "", [], f"读取目录失败: {err}"),
        )
        if not started:
            done_cb(False, "", [], "目录读取任务正在进行，请稍候重试。")

    def _collect_db_root_info(self, raw_path: str) -> dict[str, str]:
        if self._ssh_service is None or not getattr(self._ssh_service, "is_connected", False):
            return {"resolved": "--"}
        candidate = str(raw_path or "").strip() or "~"
        resolved = self._expand_remote_path(candidate)
        return {"resolved": resolved or "--"}

    def _expand_remote_path(self, raw_path: str) -> str:
        path = str(raw_path or "").strip()
        if not path:
            return ""
        qpath = shlex.quote(path)
        cmd = (
            f"p={qpath}; "
            'if [ "$p" = "~" ]; then printf "%s\\n" "$HOME"; '
            'elif [ "${p#~/}" != "$p" ]; then printf "%s\\n" "$HOME/${p#~/}"; '
            'else printf "%s\\n" "$p"; fi'
        )
        rc, stdout, _ = self._run_ssh(cmd, 10)
        expanded = stdout.strip() if rc == 0 else ""
        if expanded.startswith("~"):
            home = self._get_remote_home()
            if home:
                expanded = home if expanded == "~" else f"{home}/{expanded[2:]}"
        return expanded

    def _get_remote_home(self) -> str:
        rc, out, _ = self._run_ssh("printf '%s\\n' \"$HOME\"", 10)
        home = out.strip() if rc == 0 else ""
        return home if home.startswith("/") else ""

    def _normalize_remote_path(self, resolved: str) -> str:
        normalized = posixpath.normpath(str(resolved or "").strip())
        if not normalized.startswith("/"):
            return normalized
        return normalized if normalized == "/" else normalized.rstrip("/")

    def _validate_db_root_remote(self, raw_path: str, allow_create: bool = False) -> tuple[bool, str, str, bool]:
        path = str(raw_path or "").strip()
        if not path:
            return False, "", "数据库根目录不能为空。", False
        resolved = self._expand_remote_path(path)
        if not resolved:
            return False, "", f"无法解析远程路径: {path}", False
        if not resolved.startswith("/"):
            return False, "", f"数据库根目录必须是绝对路径，当前为: {resolved}", False
        resolved = self._normalize_remote_path(resolved)
        created = False
        qroot = shlex.quote(resolved)
        rc, _, _ = self._run_ssh(f"test -d {qroot}", 10)
        if rc != 0:
            if allow_create:
                rc_create, _, err_create = self._run_ssh(f"mkdir -p {qroot}", 15)
                if rc_create != 0:
                    return False, "", f"目录不存在且无法自动创建: {resolved}\n错误: {err_create.strip() or '权限不足'}", False
                created = True
            else:
                return False, "", f"目录不存在: {resolved}", False
        rc_exec, _, _ = self._run_ssh(f"test -x {qroot}", 10)
        if rc_exec != 0:
            return False, "", f"目录不可进入(-x): {resolved}", created
        rc_write, _, _ = self._run_ssh(f"test -w {qroot}", 10)
        if rc_write != 0:
            return False, "", self._build_permission_denied_message(resolved), created
        probe = f"{qroot}/.h2ometa_write_probe"
        rc_probe, _, err_probe = self._run_ssh(f"touch {probe} && rm -f {probe}", 10)
        if rc_probe != 0:
            return False, "", self._build_permission_denied_message(resolved, detail=err_probe.strip() or "写入探针失败"), created
        return True, resolved, "", created

    def _build_permission_denied_message(self, db_root: str, detail: str = "") -> str:
        user = "your_user"
        rc_user, stdout_user, _ = self._run_ssh("whoami", 10)
        if rc_user == 0 and stdout_user.strip():
            user = stdout_user.strip()
        lines = [
            f"当前 SSH 用户对目录无写权限: {db_root}",
            "建议改用: ~/databases",
            "如需继续使用该目录，请联系管理员执行：",
            f"mkdir -p {db_root}",
            f"chown {user}:{user} {db_root}",
            f"chmod 775 {db_root}",
        ]
        if detail:
            lines.append(f"详细错误: {detail}")
        return "\n".join(lines)

    def _make_ssh_run_fn(self):
        ssh = self._ssh_service
        if ssh is None:
            raise RuntimeError("SSH service is not connected")

        def _run(cmd: str, timeout: int = 15):
            return ssh.run(cmd, timeout=timeout)

        return _run
