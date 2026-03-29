"""安装任务聚合器（UI 内存态）。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class InstallTask:
    task_id: str
    title: str
    source: str
    state: str  # running | success | failed
    message: str
    progress_text: str
    speed_text: str
    location_hint: str
    updated_at: float


class InstallTaskController(QObject):
    """聚合安装域任务状态，供状态栏与面板消费。"""

    changed = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._tasks: dict[str, InstallTask] = {}

    def ingest_event(self, payload: dict) -> None:
        task_id = str(payload.get("task_id", "") or "").strip()
        if not task_id:
            return
        title = str(payload.get("title", "") or task_id).strip()
        source = str(payload.get("source", "") or "").strip()
        state = self._normalize_state(payload.get("state", "running"))
        if "detail" in payload:
            raise ValueError("Legacy install_task_event.detail is no longer supported")
        message = self._clean_text(payload.get("message", ""))
        progress_text = self._clean_text(payload.get("progress_text", ""))
        speed_text = self._clean_text(payload.get("speed_text", ""))
        location_hint = self._clean_text(payload.get("location_hint", ""))
        self._tasks[task_id] = InstallTask(
            task_id=task_id,
            title=title,
            source=source,
            state=state,
            message=message,
            progress_text=progress_text,
            speed_text=speed_text,
            location_hint=location_hint,
            updated_at=time.time(),
        )
        self.changed.emit()

    def start(
        self,
        *,
        task_id: str,
        title: str,
        source: str,
        message: str = "",
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "",
    ) -> None:
        self.ingest_event(
            {
                "task_id": task_id,
                "title": title,
                "source": source,
                "state": "running",
                "message": message,
                "progress_text": progress_text,
                "speed_text": speed_text,
                "location_hint": location_hint,
            }
        )

    def update(
        self,
        *,
        task_id: str,
        title: str,
        source: str,
        message: str = "",
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "",
    ) -> None:
        self.start(
            task_id=task_id,
            title=title,
            source=source,
            message=message,
            progress_text=progress_text,
            speed_text=speed_text,
            location_hint=location_hint,
        )

    def success(
        self,
        *,
        task_id: str,
        title: str,
        source: str,
        message: str = "",
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "",
    ) -> None:
        self.ingest_event(
            {
                "task_id": task_id,
                "title": title,
                "source": source,
                "state": "success",
                "message": message,
                "progress_text": progress_text,
                "speed_text": speed_text,
                "location_hint": location_hint,
            }
        )

    def fail(
        self,
        *,
        task_id: str,
        title: str,
        source: str,
        message: str = "",
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "",
    ) -> None:
        self.ingest_event(
            {
                "task_id": task_id,
                "title": title,
                "source": source,
                "state": "failed",
                "message": message,
                "progress_text": progress_text,
                "speed_text": speed_text,
                "location_hint": location_hint,
            }
        )

    def snapshot(self) -> list[dict]:
        rows = sorted(self._tasks.values(), key=lambda item: item.updated_at, reverse=True)
        return [asdict(item) for item in rows]

    def summary(self) -> dict[str, object]:
        rows = self.snapshot()
        running = [row for row in rows if row["state"] == "running"]
        failed = [row for row in rows if row["state"] == "failed"]
        succeeded = [row for row in rows if row["state"] == "success"]

        if running:
            current = running[0]
            running_text = self._build_running_text(current)
            return {
                "level": "running",
                "text": running_text,
                "running": len(running),
                "failed": len(failed),
                "success": len(succeeded),
                "total": len(rows),
            }
        if failed:
            latest = failed[0]
            short_title = self._compact_title(str(latest.get("title", "") or "安装任务"))
            return {
                "level": "error",
                "text": f"安装: {short_title} 失败",
                "running": 0,
                "failed": len(failed),
                "success": len(succeeded),
                "total": len(rows),
            }
        if succeeded:
            latest = succeeded[0]
            return {
                "level": "success",
                "text": f"安装: {self._compact_title(str(latest.get('title', '') or '安装任务'))} 完成",
                "running": 0,
                "failed": 0,
                "success": len(succeeded),
                "total": len(rows),
            }
        return {
            "level": "idle",
            "text": "安装: 空闲",
            "running": 0,
            "failed": 0,
            "success": 0,
            "total": 0,
        }

    @staticmethod
    def _normalize_state(value: object) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"success", "succeeded", "done", "completed"}:
            return "success"
        if raw in {"failed", "error", "fail"}:
            return "failed"
        return "running"

    @staticmethod
    def _build_running_text(current: dict) -> str:
        title = InstallTaskController._compact_title(str(current.get("title", "") or "安装任务").strip())
        progress = InstallTaskController._clean_text(current.get("progress_text", ""))
        speed = InstallTaskController._clean_text(current.get("speed_text", ""))

        parts = []
        if progress:
            parts.append(progress)
        if speed:
            parts.append(speed)
        if parts:
            return f"安装: {title} {' '.join(parts)}"
        return f"安装: {title}"

    @staticmethod
    def _compact_title(title: str) -> str:
        raw = str(title or "").strip()
        if not raw:
            return "安装任务"
        if "·" in raw:
            raw = raw.split("·")[-1].strip()
        return raw or "安装任务"

    @staticmethod
    def _clean_text(value: object) -> str:
        return str(value or "").strip()
