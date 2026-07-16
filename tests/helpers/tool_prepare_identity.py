from __future__ import annotations

import os

from apps.remote_runner.tool_prepare_claims import ToolPrepareWorkerIdentity
from apps.remote_runner.tool_prepare_process_marker import ToolPrepareProcessMarker


def make_unverifiable_tool_prepare_worker_identity(
    worker_id: str,
    *,
    session_id: str,
    process_instance_id: str,
    hostname: str,
    process_pid: int | None = None,
) -> ToolPrepareWorkerIdentity:
    pid = int(os.getpid() if process_pid is None else process_pid)
    return ToolPrepareWorkerIdentity(
        worker_id=worker_id,
        session_id=session_id,
        process_instance_id=process_instance_id,
        process_pid=pid,
        hostname=hostname,
        process_marker=ToolPrepareProcessMarker.unsupported(
            process_instance_id=process_instance_id,
            process_pid=pid,
            hostname=hostname,
            platform_name="test",
        ),
    )


__all__ = ["make_unverifiable_tool_prepare_worker_identity"]
