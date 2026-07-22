"""Production activation gate for the not-yet-wired durable process launcher."""

from __future__ import annotations

from typing import NoReturn

from .agent_run_launch_gate import AgentRunLaunchGateError


def require_durable_agent_process_launcher() -> NoReturn:
    """Fail closed until Stage 9c2 replaces this gate with the real launcher."""

    raise AgentRunLaunchGateError("durable_process_launcher")


__all__ = ["require_durable_agent_process_launcher"]
