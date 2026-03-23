"""Helpers for querying and caching remote execution status."""

from __future__ import annotations

import shlex
import time
from typing import Any


class ExecutionStatusService:
    """Query remote execution status with short-lived local caching."""

    def __init__(self) -> None:
        self.cache: dict[str, dict[str, Any]] = {}

    def get_execution_remote_status(self, execution_id: str, pm, ssh) -> dict[str, Any]:
        row = pm.db.execute(
            """
            SELECT execution_id, sample_id, tool_id, status, created_at, completed_at, error
            FROM executions
            WHERE execution_id = ? AND archived_at IS NULL
            LIMIT 1
            """,
            (execution_id,),
        ).fetchone()
        if row is None:
            return {"status": "error", "message": "未找到该任务记录"}

        sample_id = row["sample_id"]
        tool_id = row["tool_id"]
        remote_base = str(pm.current_project.remote_base or "").strip()
        if not remote_base:
            remote_base = f"~/.h2ometa/projects/{pm.current_project.project_id}"
        task_dir = f"{remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"
        job_id = f"h2o_{execution_id}"

        data = {
            "execution_id": execution_id,
            "tool_id": tool_id,
            "sample_id": sample_id,
            "local_status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "local_error": row["error"] or "",
            "task_dir": task_dir,
            "ssh_connected": False,
            "screen_running": None,
            "remote_status": "",
            "exit_code": "",
            "heartbeat": "",
            "heartbeat_age_sec": None,
            "log_tail": "",
        }
        cache_key = str(execution_id or "").strip()
        cached = self._get_cached_remote_status(cache_key, data["local_status"])
        if cached is not None:
            return {"status": "ok", "data": cached, "message": "使用最近缓存状态"}

        if ssh is None or not getattr(ssh, "is_connected", False):
            return {"status": "ok", "data": data, "message": "SSH 未连接，仅显示本地状态"}

        data["ssh_connected"] = True
        status_cmd = (
            "{ "
            "echo __STATUS__; cat " + shlex.quote(f"{task_dir}/status.txt") + " 2>/dev/null || true; "
            "echo __EXIT__; cat " + shlex.quote(f"{task_dir}/exit_code.txt") + " 2>/dev/null || true; "
            "echo __HEARTBEAT__; cat " + shlex.quote(f"{task_dir}/heartbeat.txt") + " 2>/dev/null || true; "
            "}"
        )
        try:
            rc, out, _ = ssh.run(status_cmd, timeout=10)
            if rc == 0:
                parsed = self.parse_remote_status_block(out)
                data["remote_status"] = parsed.get("status", "")
                data["exit_code"] = parsed.get("exit", "")
                data["heartbeat"] = parsed.get("heartbeat", "")
        except Exception:
            pass

        if data["heartbeat"]:
            try:
                hb = int(data["heartbeat"])
                data["heartbeat_age_sec"] = max(0, int(time.time()) - hb)
            except Exception:
                data["heartbeat_age_sec"] = None

        try:
            rc, _, _ = ssh.run(
                f"screen -ls | grep -Fq -- {shlex.quote(job_id)}",
                timeout=10,
            )
            data["screen_running"] = rc == 0
        except Exception:
            pass

        try:
            rc, out, _ = ssh.run(
                f"tail -n 20 {shlex.quote(f'{task_dir}/task.log')} 2>/dev/null",
                timeout=10,
            )
            if rc == 0:
                data["log_tail"] = out
        except Exception:
            pass

        self._set_cached_remote_status(cache_key, data)
        return {"status": "ok", "data": data}

    def _get_cached_remote_status(self, execution_id: str, local_status: str) -> dict[str, Any] | None:
        if not execution_id:
            return None
        cached = self.cache.get(execution_id)
        if not cached:
            return None
        ts = float(cached.get("_cached_at", 0.0) or 0.0)
        if ts <= 0:
            return None
        ttl_sec = 5.0 if local_status in {"pending", "running", "retrying"} else 30.0
        if (time.time() - ts) > ttl_sec:
            return None
        data = dict(cached.get("data") or {})
        return data if data else None

    def _set_cached_remote_status(self, execution_id: str, data: dict[str, Any]) -> None:
        if not execution_id:
            return
        self.cache[execution_id] = {
            "_cached_at": time.time(),
            "data": dict(data),
        }

    @staticmethod
    def parse_remote_status_block(output: str) -> dict[str, str]:
        result = {"status": "", "exit": "", "heartbeat": ""}
        current = ""
        bucket: dict[str, list[str]] = {"status": [], "exit": [], "heartbeat": []}
        marker_map = {
            "__STATUS__": "status",
            "__EXIT__": "exit",
            "__HEARTBEAT__": "heartbeat",
        }
        for raw in (output or "").splitlines():
            line = raw.strip("\r\n")
            marker = marker_map.get(line.strip())
            if marker is not None:
                current = marker
                continue
            if current:
                bucket[current].append(line)
        for key in ("status", "exit", "heartbeat"):
            text = "\n".join(bucket[key]).strip()
            if text:
                result[key] = text.splitlines()[0].strip()
        return result

