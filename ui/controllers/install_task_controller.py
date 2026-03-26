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
    detail: str
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
        detail = str(payload.get("detail", "") or "").strip()
        state = self._normalize_state(payload.get("state", "running"))
        self._tasks[task_id] = InstallTask(
            task_id=task_id,
            title=title,
            source=source,
            state=state,
            detail=detail,
            updated_at=time.time(),
        )
        self.changed.emit()

    def start(self, *, task_id: str, title: str, source: str, detail: str = "") -> None:
        self.ingest_event(
            {
                "task_id": task_id,
                "title": title,
                "source": source,
                "state": "running",
                "detail": detail,
            }
        )

    def update(self, *, task_id: str, title: str, source: str, detail: str = "") -> None:
        self.start(task_id=task_id, title=title, source=source, detail=detail)

    def success(self, *, task_id: str, title: str, source: str, detail: str = "") -> None:
        self.ingest_event(
            {
                "task_id": task_id,
                "title": title,
                "source": source,
                "state": "success",
                "detail": detail,
            }
        )

    def fail(self, *, task_id: str, title: str, source: str, detail: str = "") -> None:
        self.ingest_event(
            {
                "task_id": task_id,
                "title": title,
                "source": source,
                "state": "failed",
                "detail": detail,
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
            return {
                "level": "error",
                "text": f"安装: ❌ {len(failed)} 项失败",
                "running": 0,
                "failed": len(failed),
                "success": len(succeeded),
                "total": len(rows),
            }
        if succeeded:
            latest = succeeded[0]
            return {
                "level": "success",
                "text": f"安装: ✅ 最近完成 {latest['title']}",
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
        title = str(current.get("title", "") or "安装任务").strip()
        detail = str(current.get("detail", "") or "").strip()
        progress, speed = InstallTaskController._extract_progress_and_speed(detail)

        parts = []
        if progress:
            parts.append(progress)
        if speed:
            parts.append(speed)
        if parts:
            return f"安装: ⏳ 正在安装 {title} · {' · '.join(parts)}"
        return f"安装: ⏳ 正在安装 {title}..."

    @staticmethod
    def _extract_progress_and_speed(detail: str) -> tuple[str, str]:
        progress = ""
        speed = ""
        text = str(detail or "").strip()
        if not text:
            return progress, speed

        segments = [seg.strip() for seg in text.split("·") if seg.strip()]
        for seg in segments:
            if not progress and seg.endswith("%"):
                progress = seg
            if seg.startswith("速度 "):
                speed = seg[len("速度 ") :].strip()
            elif any(unit in seg for unit in ("KB/s", "MB/s", "GB/s", "B/s")):
                speed = seg.replace("速度", "").strip()
        return progress, speed
