from __future__ import annotations

import time

from ui.install_log_parser import extract_progress_and_speed


class InstallWorkflowStore:
    """In-memory store for install-domain snapshots."""

    def __init__(self) -> None:
        self._tool_snapshots: dict[str, dict] = {}

    def get_tool_snapshot(self, tool_id: str) -> dict:
        clean_tool_id = str(tool_id or "").strip()
        if not clean_tool_id:
            return {}
        return dict(self._tool_snapshots.get(clean_tool_id, {}))

    def update_tool_snapshot(self, tool_id: str, **updates) -> dict:
        clean_tool_id = str(tool_id or "").strip()
        if not clean_tool_id:
            return {}
        current = dict(self._tool_snapshots.get(clean_tool_id, {}))
        current.update({k: v for k, v in updates.items() if v is not None})
        current["tool_id"] = clean_tool_id
        current["updated_at"] = time.time()
        self._tool_snapshots[clean_tool_id] = current
        return dict(current)


class InstallWorkflowPresenter:
    """Build structured UI payloads for install-domain views."""

    @staticmethod
    def build_task_event(
        *,
        task_id: str,
        title: str,
        source: str,
        state: str,
        detail: str = "",
        message: str = "",
        progress_text: str = "",
        speed_text: str = "",
        location_hint: str = "",
    ) -> dict:
        detail_text = str(detail or "").strip()
        message_text = str(message or detail_text).strip()
        progress_label = str(progress_text or "").strip()
        speed_label = str(speed_text or "").strip()
        if not progress_label or not speed_label:
            parsed_progress, parsed_speed = extract_progress_and_speed(message_text or detail_text)
            progress_label = progress_label or parsed_progress
            speed_label = speed_label or parsed_speed

        progress_value = None
        if progress_label.endswith("%"):
            try:
                progress_value = int(float(progress_label[:-1]))
            except ValueError:
                progress_value = None

        return {
            "task_id": str(task_id or "").strip(),
            "title": str(title or "").strip(),
            "source": str(source or "").strip(),
            "state": str(state or "").strip().lower() or "running",
            "detail": detail_text,
            "message": message_text,
            "progress_value": progress_value,
            "progress_text": progress_label,
            "speed_text": speed_label,
            "location_hint": str(location_hint or "").strip(),
            "updated_at": time.time(),
        }

    @classmethod
    def build_bootstrap_task_event(cls, state: str, detail: str = "") -> dict:
        return cls.build_task_event(
            task_id="bootstrap:miniforge",
            title="运行环境初始化",
            source="bootstrap",
            state=state,
            detail=detail,
            message=detail,
            location_hint="settings",
        )

    @classmethod
    def build_tool_install_task_event(
        cls,
        tool_id: str,
        tool_name: str,
        state: str,
        detail: str = "",
        *,
        progress_text: str = "",
        speed_text: str = "",
    ) -> dict:
        return cls.build_task_event(
            task_id=f"tool_env:{tool_id}",
            title=f"工具环境安装 · {tool_name}",
            source="tool_env",
            state=state,
            detail=detail,
            message=detail,
            progress_text=progress_text,
            speed_text=speed_text,
            location_hint="settings",
        )
