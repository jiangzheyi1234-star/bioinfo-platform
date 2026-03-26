"""Remote execution reconcile helpers for UI orchestration."""

from __future__ import annotations

import shlex
import time


class ExecutionReconcileService:
    """Collect reconcile actions by probing remote task status files/screen."""

    @classmethod
    def collect_actions(
        cls,
        ssh,
        remote_base: str,
        running_rows: list[tuple[str, str, str]],
        failed_rows: list[tuple[str, str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        actions: dict[str, list[dict[str, str]]] = {
            "relink_running": [],
            "mark_completed": [],
            "mark_failed": [],
        }
        now_ts = int(time.time())

        for execution_id, sample_id, tool_id in failed_rows:
            task_dir = f"{remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"
            status_text, _, heartbeat_text = cls.read_status_bundle(ssh, task_dir)
            if status_text != "RUNNING":
                continue

            heartbeat_ts = 0
            try:
                heartbeat_ts = int((heartbeat_text or "0").strip() or "0")
            except Exception:
                heartbeat_ts = 0

            if heartbeat_ts > 0 and (now_ts - heartbeat_ts) > 900:
                continue
            actions["relink_running"].append({"execution_id": execution_id})

        for execution_id, sample_id, tool_id in running_rows:
            task_dir = f"{remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"
            job_id = f"h2o_{execution_id}"
            status_text, exit_code, heartbeat_text = cls.read_status_bundle(ssh, task_dir)
            heartbeat_ts = 0
            try:
                heartbeat_ts = int((heartbeat_text or "0").strip() or "0")
            except Exception:
                heartbeat_ts = 0

            if exit_code == "0" or status_text == "DONE":
                actions["mark_completed"].append(
                    {
                        "execution_id": execution_id,
                        "sample_id": sample_id,
                        "tool_id": tool_id,
                        "output_dir": task_dir,
                    }
                )
                continue
            heartbeat_stale = heartbeat_ts > 0 and (now_ts - heartbeat_ts) > 900
            if heartbeat_stale:
                actions["mark_failed"].append(
                    {
                        "execution_id": execution_id,
                        "error": "Heartbeat stale for over 15 minutes",
                    }
                )
                continue

            try:
                rc_screen, _, _ = ssh.run(
                    f"screen -ls | grep -Fq -- {shlex.quote(job_id)}",
                    timeout=10,
                )
            except Exception:
                continue

            if rc_screen == 0 or status_text == "RUNNING":
                continue
            actions["mark_failed"].append(
                {
                    "execution_id": execution_id,
                    "error": f"remote status: {status_text}" if status_text else "Remote execution ended unexpectedly",
                }
            )
        return actions

    @classmethod
    def collect_resume_actions(
        cls,
        ssh,
        remote_base: str,
        running_rows: list[tuple[str, str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        """Collect startup recovery actions for running executions.

        DB is index, remote status is truth:
        - mark_completed: remote indicates DONE/exit=0
        - mark_failed: remote indicates FAILED/ended unexpectedly
        - resume_waiting: still running, should re-attach waiter
        """
        actions: dict[str, list[dict[str, str]]] = {
            "mark_completed": [],
            "mark_failed": [],
            "resume_waiting": [],
        }
        for execution_id, sample_id, tool_id in running_rows:
            task_dir = f"{remote_base}/intermediate/{sample_id}/{tool_id}_{execution_id}"
            job_id = f"h2o_{execution_id}"
            status_text, exit_code, _heartbeat = cls.read_status_bundle(ssh, task_dir)

            if exit_code == "0" or status_text == "DONE":
                actions["mark_completed"].append(
                    {
                        "execution_id": execution_id,
                        "sample_id": sample_id,
                        "tool_id": tool_id,
                        "output_dir": task_dir,
                    }
                )
                continue
            if status_text == "FAILED":
                actions["mark_failed"].append(
                    {
                        "execution_id": execution_id,
                        "error": "remote status: FAILED",
                    }
                )
                continue

            session_exists = False
            try:
                rc_screen, _, _ = ssh.run(
                    f"screen -ls | grep -Fq -- {shlex.quote(job_id)}",
                    timeout=10,
                )
                session_exists = rc_screen == 0
            except Exception:
                session_exists = False

            if status_text == "RUNNING" or session_exists:
                actions["resume_waiting"].append(
                    {
                        "execution_id": execution_id,
                        "sample_id": sample_id,
                        "tool_id": tool_id,
                        "task_dir": task_dir,
                        "job_id": job_id,
                    }
                )
                continue

            actions["mark_failed"].append(
                {
                    "execution_id": execution_id,
                    "error": f"remote status: {status_text}" if status_text else "Remote execution ended unexpectedly",
                }
            )
        return actions

    @classmethod
    def read_status_bundle(cls, ssh, task_dir: str) -> tuple[str, str, str]:
        status_cmd = (
            "{ "
            "echo __STATUS__; cat " + shlex.quote(f"{task_dir}/status.txt") + " 2>/dev/null || true; "
            "echo __EXIT__; cat " + shlex.quote(f"{task_dir}/exit_code.txt") + " 2>/dev/null || true; "
            "echo __HEARTBEAT__; cat " + shlex.quote(f"{task_dir}/heartbeat.txt") + " 2>/dev/null || true; "
            "}"
        )
        try:
            rc, out, _ = ssh.run(status_cmd, timeout=10)
            if rc == 0 and out:
                parsed = cls.parse_status_bundle(out)
                status_text = str(parsed.get("status", "")).strip().upper()
                exit_code = str(parsed.get("exit", "")).strip()
                heartbeat_text = str(parsed.get("heartbeat", "")).strip()
                if status_text or exit_code or heartbeat_text:
                    return status_text, exit_code, heartbeat_text
        except Exception:
            pass

        def _read_one(filename: str) -> str:
            try:
                rc_file, out_file, _ = ssh.run(
                    f"cat {shlex.quote(f'{task_dir}/{filename}')} 2>/dev/null",
                    timeout=10,
                )
                if rc_file == 0:
                    return (out_file or "").strip()
            except Exception:
                return ""
            return ""

        return _read_one("status.txt").upper(), _read_one("exit_code.txt"), _read_one("heartbeat.txt")

    @staticmethod
    def parse_status_bundle(output: str) -> dict[str, str]:
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
