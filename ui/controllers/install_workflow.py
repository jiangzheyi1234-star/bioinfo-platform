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


def _progress_value(progress_text: str) -> int | None:
    progress_label = str(progress_text or "").strip()
    if not progress_label.endswith("%"):
        return None
    try:
        return int(float(progress_label[:-1]))
    except ValueError:
        return None


def build_task_event(
    *,
    task_id: str,
    title: str,
    source: str,
    state: str,
    message: str = "",
    progress_text: str = "",
    speed_text: str = "",
    location_hint: str = "",
) -> dict:
    message_text = str(message or "").strip()
    progress_label = str(progress_text or "").strip()
    speed_label = str(speed_text or "").strip()
    if not progress_label or not speed_label:
        parsed_progress, parsed_speed = extract_progress_and_speed(message_text)
        progress_label = progress_label or parsed_progress
        speed_label = speed_label or parsed_speed

    return {
        "task_id": str(task_id or "").strip(),
        "title": str(title or "").strip(),
        "source": str(source or "").strip(),
        "state": str(state or "").strip().lower() or "running",
        "message": message_text,
        "progress_value": _progress_value(progress_label),
        "progress_text": progress_label,
        "speed_text": speed_label,
        "location_hint": str(location_hint or "").strip(),
        "updated_at": time.time(),
    }


def build_bootstrap_task_event(state: str, message: str = "") -> dict:
    return build_task_event(
        task_id="bootstrap:miniforge",
        title="运行环境初始化",
        source="bootstrap",
        state=state,
        message=message,
        location_hint="settings",
    )


def build_tool_install_task_event(
    tool_id: str,
    tool_name: str,
    state: str,
    message: str = "",
    *,
    progress_text: str = "",
    speed_text: str = "",
) -> dict:
    return build_task_event(
        task_id=f"tool_env:{tool_id}",
        title=f"工具环境安装 · {tool_name}",
        source="tool_env",
        state=state,
        message=message,
        progress_text=progress_text,
        speed_text=speed_text,
        location_hint="settings",
    )
