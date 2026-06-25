from __future__ import annotations

from typing import Any

from .config import RemoteRunnerConfig
from .result_package_trigger_provenance import fetch_run_trigger_provenance


RUN_TRIGGER_PROVENANCE_READ_SCHEMA = "run-trigger-provenance-read.v1"


def attach_run_trigger_provenance(cfg: RemoteRunnerConfig, run: dict[str, Any]) -> dict[str, Any]:
    trigger = run.get("trigger")
    if not isinstance(trigger, dict):
        return run
    run_id = str(run.get("runId") or "").strip()
    if not run_id:
        return run
    try:
        provenance = fetch_run_trigger_provenance(cfg, run_id)
    except ValueError as exc:
        return {
            **run,
            "trigger": {
                **trigger,
                "provenance": _unavailable_provenance(
                    run_id=run_id,
                    trigger=trigger,
                    reason_code=str(exc) or "RUN_TRIGGER_PROVENANCE_UNAVAILABLE",
                ),
            },
        }
    if provenance is None:
        return run
    return {**run, "trigger": {**trigger, "provenance": _available_provenance(provenance)}}


def _available_provenance(provenance: dict[str, Any]) -> dict[str, Any]:
    return {
        **provenance,
        "schemaVersion": RUN_TRIGGER_PROVENANCE_READ_SCHEMA,
        "available": True,
    }


def _unavailable_provenance(
    *,
    run_id: str,
    trigger: dict[str, Any],
    reason_code: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": RUN_TRIGGER_PROVENANCE_READ_SCHEMA,
        "available": False,
        "reasonCode": reason_code,
        "runId": run_id,
        "triggerId": str(trigger.get("triggerId") or ""),
        "triggerEventId": str(trigger.get("triggerEventId") or ""),
        "source": str(trigger.get("source") or ""),
        "cursor": str(trigger.get("cursor") or ""),
    }
