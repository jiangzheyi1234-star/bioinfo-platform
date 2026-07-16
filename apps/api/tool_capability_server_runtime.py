"""Bind capability-graph remote reads to one explicit runner identity."""

from __future__ import annotations

from typing import Any


_SERVER_BOUND_READS = frozenset(
    {
        "list_databases",
        "list_latest_tool_prepare_jobs",
        "list_tool_index",
        "list_tool_prepare_job_queue",
        "list_tools",
    }
)


class CapabilityGraphRuntimeBinding:
    def __init__(self, runtime: Any, server_id: str | None) -> None:
        self._runtime = runtime
        raw_server_id = "" if server_id is None else str(server_id)
        self.server_id = raw_server_id.strip()
        if server_id is not None and not self.server_id:
            raise ValueError("CAPABILITY_GRAPH_SERVER_ID_REQUIRED")

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._runtime, name)
        if not self.server_id or name not in _SERVER_BOUND_READS or not callable(attribute):
            return attribute

        def call_server_bound(*args: Any, **kwargs: Any) -> Any:
            if "server_id" in kwargs:
                raise TypeError(f"{name} received duplicate server_id binding")
            return attribute(*args, server_id=self.server_id, **kwargs)

        return call_server_bound


def bind_capability_graph_runtime(
    runtime: Any,
    server_id: str | None,
) -> CapabilityGraphRuntimeBinding:
    return CapabilityGraphRuntimeBinding(runtime, server_id)


__all__ = ["CapabilityGraphRuntimeBinding", "bind_capability_graph_runtime"]
