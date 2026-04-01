from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSignal, pyqtSlot

from ui.workers.base_worker import BaseCancellableWorker

from core.environment import env_detector
from core.environment import miniforge_bootstrap
from core.environment.env_installer import EnvInstaller
from core.environment.env_batch_checker import check_all_envs, get_existing_env_paths
from core.remote.server_capabilities import ServerCapabilities

logger = logging.getLogger(__name__)
MINIFORGE_PROBE_COMMAND = "test -f ~/.h2ometa/conda/bin/conda && echo OK || echo MISSING"


def _format_rate(bps: float) -> str:
    if bps >= 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024 * 1024):.1f}GB/s"
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f}MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f}KB/s"
    return f"{max(bps, 0):.0f}B/s"


def _safe_emit(signal, *args) -> bool:
    try:
        signal.emit(*args)
        return True
    except RuntimeError:
        logger.debug("Skipped signal emit on deleted Qt object", exc_info=True)
        return False


def _normalize_env_paths(paths) -> set[str]:
    return {str(path).rstrip("/") for path in (paths or []) if str(path).strip()}


def _tool_env_exists_in_paths(tool: dict | None, existing_env_paths: set[str], conda_executable: str = "") -> bool:
    tool = tool or {}
    conda_env = str(tool.get("conda_env", "") or "").strip()
    if not conda_env:
        return True

    normalized_paths = _normalize_env_paths(existing_env_paths)
    env_names = {path.split("/")[-1] for path in normalized_paths}
    if conda_env in env_names:
        return True

    expected_path = env_detector.expected_env_path(conda_executable, conda_env)
    if expected_path and "~" not in expected_path:
        return expected_path.rstrip("/") in normalized_paths
    return False


class MiniforgeProbeWorker(BaseCancellableWorker):
    """在 QThread 中探测自管 Miniforge 是否已落盘。"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn

    @pyqtSlot()
    def run(self):
        try:
            rc, out, err = self._ssh_run_fn(MINIFORGE_PROBE_COMMAND, timeout=10)
            status = str(out or "").strip()
            if rc != 0 or status not in {"OK", "MISSING"}:
                raise RuntimeError(
                    f"Miniforge probe failed: rc={rc}, out={status!r}, err={str(err or '').strip()!r}"
                )
            self._emit(
                "finished",
                {
                    "command": MINIFORGE_PROBE_COMMAND,
                    "status": status,
                    "deployed": status == "OK",
                },
            )
        except Exception as e:
            if self._cancelled:
                return
            logger.exception("MiniforgeProbeWorker 出错")
            self._emit("error", str(e))


class MiniforgeBootstrapSubmitWorker(BaseCancellableWorker):
    """在 QThread 中提交 detached Miniforge 初始化任务。"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, caps: ServerCapabilities):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._caps = caps

    @pyqtSlot()
    def run(self):
        if self._cancelled:
            return
        try:
            result = miniforge_bootstrap.submit(self._caps, self._ssh_run_fn)
            if self._cancelled:
                return
            self._emit("finished", result)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("提交 Miniforge 后台任务失败")
            self._emit("error", str(exc))


class MiniforgePollWorker(BaseCancellableWorker):
    """后台探测 Miniforge 状态或读取失败日志，避免主线程同步 SSH。"""

    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, ssh_run_fn, task_dir: str, operation: str, reason: str = ""):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._task_dir = str(task_dir or miniforge_bootstrap.TASK_DIR)
        self._operation = str(operation or "").strip()
        self._reason = str(reason or "")

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._operation == "probe_status":
                status = miniforge_bootstrap.check_status(
                    self._ssh_run_fn,
                    task_dir=self._task_dir,
                    timeout=10,
                )
                alive = miniforge_bootstrap.is_session_alive(
                    self._ssh_run_fn,
                    job_id=miniforge_bootstrap.JOB_ID,
                    timeout=10,
                )
                payload = {
                    "operation": self._operation,
                    "task_dir": self._task_dir,
                    "status": str(status.get("status", "") or ""),
                    "exit_code": str(status.get("exit_code", "") or ""),
                    "heartbeat": str(status.get("heartbeat", "") or ""),
                    "session_alive": bool(alive),
                }
            elif self._operation == "read_failure_log":
                log_text = miniforge_bootstrap.read_log(
                    self._ssh_run_fn,
                    task_dir=self._task_dir,
                    tail_lines=40,
                    timeout=10,
                )
                payload = {
                    "operation": self._operation,
                    "task_dir": self._task_dir,
                    "reason": self._reason,
                    "log_text": str(log_text or ""),
                }
            else:
                raise RuntimeError(f"Unsupported Miniforge poll operation: {self._operation}")

            self._emit("finished", payload)
        except Exception as exc:
            logger.exception("MiniforgePollWorker 出错: operation=%s", self._operation)
            self._emit(
                "error",
                {
                    "operation": self._operation,
                    "task_dir": self._task_dir,
                    "reason": self._reason,
                    "error": str(exc),
                },
            )


class EnvBatchCheckWorker(BaseCancellableWorker):
    """SSH 批量检测工具 conda 环境是否就绪。"""

    tool_checked = pyqtSignal(str, str, bool)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, tools: list[dict], conda_executable: str = ""):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self.tools = tools
        self._conda_executable = conda_executable or "conda"

    @pyqtSlot()
    def run(self):
        try:
            results, conda_envs = check_all_envs(
                ssh_run_fn=self._ssh_run_fn,
                tools=self.tools,
                conda_executable=self._conda_executable,
            )

            for r in results:
                if not self._emit("tool_checked", r.tool_id, r.env_name, r.ok):
                    return

            self._emit("finished", conda_envs)

        except Exception as e:
            if self._cancelled:
                return
            logger.exception("EnvBatchCheckWorker 出错")
            self._emit("error", str(e))


class ToolInstallBatchPollWorker(BaseCancellableWorker):
    """批量轮询工具环境安装状态（后台线程）。"""

    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, ssh_run_fn, tool_ids: list[str]):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tool_ids = list(tool_ids)

    @pyqtSlot()
    def run(self) -> None:
        try:
            rows = EnvInstaller.batch_probe(
                self._ssh_run_fn,
                self._tool_ids,
                tail_lines=120,
                timeout=20,
            )
            if not self._cancelled:
                self._emit("finished", rows)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("ToolInstallBatchPollWorker 出错")
            self._emit("error", str(exc))


class ToolInstallSubmitWorker(BaseCancellableWorker):
    """后台提交工具环境安装任务。"""

    finished = pyqtSignal(str, dict)
    error = pyqtSignal(str, str)

    def __init__(self, ssh_run_fn, tool_id: str, install_cmd: str, conda_executable: str):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tool_id = str(tool_id or "").strip()
        self._install_cmd = str(install_cmd or "")
        self._conda_executable = str(conda_executable or "")

    @pyqtSlot()
    def run(self) -> None:
        if self._cancelled:
            return
        try:
            result = EnvInstaller.submit(
                self._ssh_run_fn,
                self._tool_id,
                self._install_cmd,
                self._conda_executable,
            )
            if not self._cancelled:
                self._emit("finished", self._tool_id, result)
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("ToolInstallSubmitWorker 出错: tool_id=%s", self._tool_id)
            self._emit("error", self._tool_id, str(exc))


class RecoverInstallsWorker(BaseCancellableWorker):
    """后台恢复/解析工具安装状态，避免主线程同步 SSH。"""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(
        self,
        ssh_run_fn,
        tools: list[dict],
        conda_executable: str = "",
        existing_env_paths=None,
    ):
        super().__init__()
        self._ssh_run_fn = ssh_run_fn
        self._tools = list(tools or [])
        self._conda_executable = str(conda_executable or "")
        self._existing_env_paths = None if existing_env_paths is None else _normalize_env_paths(existing_env_paths)

    def _load_existing_env_paths(self) -> set[str]:
        if self._existing_env_paths is not None:
            return set(self._existing_env_paths)
        return _normalize_env_paths(
            get_existing_env_paths(
                ssh_run_fn=self._ssh_run_fn,
                conda_executable=self._conda_executable,
            )
        )

    def _run_recover_scan(self, existing_env_paths: set[str], tool_map: dict[str, dict]) -> list[dict]:
        installs = EnvInstaller.scan_running(self._ssh_run_fn)
        rows: list[dict] = []
        for item in installs:
            if self._cancelled:
                return []
            tool_id = str(item.get("tool_id", "") or "").strip()
            status = str(item.get("status", "") or "").strip().upper()
            task_dir = str(item.get("task_dir", "") or "").strip()
            tool = tool_map.get(tool_id)
            env_exists = False
            session_alive = False
            cleanup_attempted = False

            if status == "RUNNING":
                env_exists = _tool_env_exists_in_paths(tool, existing_env_paths, self._conda_executable)
                if not env_exists:
                    session_alive = EnvInstaller.is_session_alive(
                        self._ssh_run_fn,
                        f"h2o_install_{tool_id}",
                        timeout=10,
                    )
                    if not session_alive:
                        cleanup_attempted = True
                        try:
                            EnvInstaller.cleanup(self._ssh_run_fn, task_dir)
                        except Exception:
                            logger.debug("恢复阶段清理任务目录失败: %s", task_dir, exc_info=True)
            elif status == "DONE":
                cleanup_attempted = True
                try:
                    EnvInstaller.cleanup(self._ssh_run_fn, task_dir)
                except Exception:
                    logger.debug("恢复阶段清理已完成任务失败: %s", task_dir, exc_info=True)

            rows.append(
                {
                    "tool_id": tool_id,
                    "task_dir": task_dir,
                    "status": status,
                    "env_exists": env_exists,
                    "session_alive": session_alive,
                    "cleanup_attempted": cleanup_attempted,
                }
            )
        return rows

    @pyqtSlot()
    def run(self) -> None:
        try:
            existing_env_paths = self._load_existing_env_paths()
            if self._cancelled:
                return

            tool_map = {str(tool.get("id", "") or "").strip(): dict(tool) for tool in self._tools}
            rows = self._run_recover_scan(existing_env_paths, tool_map)
            if self._cancelled:
                return

            self._emit(
                "finished",
                {
                    "rows": rows,
                    "existing_env_paths": sorted(existing_env_paths),
                },
            )
        except Exception as exc:
            if self._cancelled:
                return
            logger.exception("RecoverInstallsWorker 出错")
            self._emit("error", str(exc))
