"""Binding-first launch authorization for Agent-owned WorkflowRuns."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, NoReturn

from core.contracts.agent_workflow_runtime import (
    WorkflowRuntimeLockV2,
    workflow_runtime_lock_v2_hash,
)

from .agent_run_authorization_origin import (
    require_agent_run_authorization_origin_for_connection,
)
from .agent_run_authorization_storage import (
    fetch_agent_run_authorization_by_run_for_connection,
)
from .agent_run_input_materialization import (
    materialize_agent_run_input,
    read_agent_run_input_expectation_for_connection,
    record_agent_run_input_materialization,
)
from .agent_workflow_runtime import (
    require_passive_current_agent_workflow_runtime_lock,
)
from .config import RemoteRunnerConfig
from .execution_query_storage import fetch_run_for_connection
from .execution_lease_time import execution_lease_expiry_is_future
from .run_execution_state_machine import RunExecutionStateMachine
from .storage_core import get_connection
from .workflow_revision_storage import fetch_workflow_revision_for_connection
from .workflow_run_storage import StaleRunAttemptError


AGENT_RUN_LAUNCH_GATE_FAILED = "AGENT_RUN_LAUNCH_GATE_FAILED"


class AgentRunLaunchGateError(RuntimeError):
    """Stable, path-free failure raised before an Agent scientific process starts."""

    code = AGENT_RUN_LAUNCH_GATE_FAILED
    stage = "agent_launch_gate"
    scope = "agent_launch_gate"

    def __init__(self, component: str) -> None:
        self.component = component
        super().__init__(f"{self.code}: {component}")


@dataclass(frozen=True, slots=True)
class AgentRunLaunchAuthorization:
    """Verified Agent launch facts safe to pass to the in-process executor."""

    authorization_id: str
    run_spec: dict[str, Any]
    runtime_lock_hash: str
    runtime_proof_hash: str
    verified_inputs: tuple[dict[str, Any], ...]
    input_materialization_event_proof: dict[str, Any]

    def comparison_payload(self) -> dict[str, Any]:
        return deepcopy(
            {
                "authorizationId": self.authorization_id,
                "runSpec": self.run_spec,
                "runtimeLockHash": self.runtime_lock_hash,
                "runtimeProofHash": self.runtime_proof_hash,
                "verifiedInputs": self.verified_inputs,
                "inputMaterializationEventProof": self.input_materialization_event_proof,
            }
        )


@dataclass(frozen=True, slots=True)
class _BoundLaunchSnapshot:
    binding: dict[str, Any]
    origin: dict[str, Any]
    workflow_revision: dict[str, Any]
    run_spec: dict[str, Any]
    request_id: str
    state_version: int
    input_expectation: dict[str, Any]

    def comparison_payload(self) -> dict[str, Any]:
        return deepcopy(
            {
                "binding": self.binding,
                "origin": self.origin,
                "workflowRevision": self.workflow_revision,
                "runSpec": self.run_spec,
                "inputExpectation": self.input_expectation,
            }
        )


def require_agent_run_launch_authorization(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> AgentRunLaunchAuthorization | None:
    """Authorize one claimed run immediately before executor entry.

    A run is classified as Agent-owned only by its immutable authorization
    binding. Ordinary runs, including rows using a look-alike server id, remain
    on the existing execution path.
    """

    first = _read_bound_launch_snapshot(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    if first is None:
        return None

    try:
        observed_runtime = require_passive_current_agent_workflow_runtime_lock(
            cfg,
            deepcopy(first.workflow_revision["runtimeLock"]),
        )
    except Exception as exc:  # noqa: BLE001 - all runtime details cross one safe boundary.
        _fail("runtime", cause=exc)
    _require_runtime_binding(first, observed_runtime)
    try:
        verified_input = materialize_agent_run_input(
            cfg,
            run_id=run_id,
            expectation=deepcopy(first.input_expectation),
        )
        materialization_event = record_agent_run_input_materialization(
            cfg,
            run_id=run_id,
            request_id=first.request_id,
            state_version=first.state_version,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            expectation=deepcopy(first.input_expectation),
        )
    except StaleRunAttemptError:
        raise
    except Exception as exc:  # noqa: BLE001 - filesystem details stay private.
        _fail("input", cause=exc)

    second = _read_bound_launch_snapshot(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    if second is None or not _strict_json_equal(
        first.comparison_payload(),
        second.comparison_payload(),
    ):
        _fail("authority_changed")
    _require_runtime_binding(second, observed_runtime)
    return AgentRunLaunchAuthorization(
        authorization_id=str(second.binding["authorizationId"]),
        run_spec=deepcopy(second.run_spec),
        runtime_lock_hash=str(observed_runtime["runtimeLockHash"]),
        runtime_proof_hash=str(observed_runtime["runtimeProofHash"]),
        verified_inputs=(deepcopy(verified_input),),
        input_materialization_event_proof=deepcopy(materialization_event["eventProof"]),
    )


def revalidate_agent_run_launch_authorization(
    cfg: RemoteRunnerConfig,
    *,
    expected: AgentRunLaunchAuthorization,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> AgentRunLaunchAuthorization:
    """Revalidate the same launch authority at a later process boundary."""

    current = require_agent_run_launch_authorization(
        cfg,
        run_id=run_id,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    if current is None or not _strict_json_equal(
        expected.comparison_payload(),
        current.comparison_payload(),
    ):
        _fail("authority_changed")
    return current


def _read_bound_launch_snapshot(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> _BoundLaunchSnapshot | None:
    with get_connection(cfg) as connection:
        connection.execute("BEGIN")
        try:
            binding = fetch_agent_run_authorization_by_run_for_connection(
                connection,
                run_id,
            )
            if binding is None:
                return None
            origin = require_agent_run_authorization_origin_for_connection(
                connection,
                str(binding["authorizationId"]),
            )
            workflow_revision = fetch_workflow_revision_for_connection(
                connection,
                str(binding["workflowRevisionId"]),
            )
            run = fetch_run_for_connection(connection, run_id)
            if workflow_revision is None or run is None:
                _fail("authority")
            run_spec = run.get("runSpec")
            if not isinstance(run_spec, dict):
                _fail("run_spec")
            try:
                input_expectation = read_agent_run_input_expectation_for_connection(
                    connection,
                    binding=binding,
                    run_spec=run_spec,
                )
            except Exception as exc:  # noqa: BLE001 - authority details stay private.
                _fail("input_authority", cause=exc)
            _require_stored_runtime_binding(binding, workflow_revision)
            _require_current_attempt(
                connection,
                run_id=run_id,
                job_id=str(origin["jobId"]),
                attempt_id=attempt_id,
                lease_generation=lease_generation,
            )
            return _BoundLaunchSnapshot(
                binding=deepcopy(binding),
                origin=deepcopy(origin),
                workflow_revision=deepcopy(workflow_revision),
                run_spec=deepcopy(run_spec),
                request_id=str(run["requestId"]),
                state_version=int(run["stateVersion"]),
                input_expectation=deepcopy(input_expectation),
            )
        except StaleRunAttemptError:
            raise
        except AgentRunLaunchGateError:
            raise
        except Exception as exc:  # noqa: BLE001 - storage details must not escape.
            _fail("authority", cause=exc)
        finally:
            connection.rollback()


def _require_stored_runtime_binding(
    binding: dict[str, Any],
    workflow_revision: dict[str, Any],
) -> None:
    runtime_lock = workflow_revision.get("runtimeLock")
    try:
        normalized = WorkflowRuntimeLockV2.model_validate(runtime_lock)
        runtime_lock_hash = workflow_runtime_lock_v2_hash(normalized)
    except Exception as exc:  # noqa: BLE001 - normalize to a path-free component.
        _fail("stored_runtime", cause=exc)
    if runtime_lock_hash != binding.get(
        "runtimeLockHash"
    ) or normalized.runtimeProofHash != binding.get("runtimeProofHash"):
        _fail("stored_runtime")


def _require_runtime_binding(
    snapshot: _BoundLaunchSnapshot,
    observed_runtime: dict[str, Any],
) -> None:
    if not _strict_json_equal(
        {
            "runtimeLockHash": observed_runtime.get("runtimeLockHash"),
            "runtimeProofHash": observed_runtime.get("runtimeProofHash"),
        },
        {
            "runtimeLockHash": snapshot.binding.get("runtimeLockHash"),
            "runtimeProofHash": snapshot.binding.get("runtimeProofHash"),
        },
    ):
        _fail("runtime_binding")


def _require_current_attempt(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    job_id: str,
    attempt_id: str,
    lease_generation: int,
) -> None:
    attempt = connection.execute(
        "SELECT * FROM run_attempts WHERE attempt_id = ?",
        (attempt_id,),
    ).fetchone()
    lease = connection.execute(
        "SELECT * FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    job = connection.execute(
        "SELECT state FROM run_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    decision = RunExecutionStateMachine.current_lease_guard(
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        current_attempt_id=(str(lease["attempt_id"]) if lease is not None else None),
        current_lease_generation=(
            int(lease["lease_generation"]) if lease is not None else None
        ),
        current_lease_state=(str(lease["state"]) if lease is not None else None),
    )
    if (
        attempt is None
        or str(attempt["run_id"]) != run_id
        or str(attempt["job_id"]) != job_id
        or str(attempt["state"]) != "running"
        or job is None
        or str(job["state"]) != "claimed"
        or not decision.accepted
        or lease is None
        or not execution_lease_expiry_is_future(lease["expires_at"])
    ):
        raise StaleRunAttemptError("RUN_ATTEMPT_STALE")


def _strict_json_equal(left: Any, right: Any) -> bool:
    try:
        return json.dumps(
            left,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) == json.dumps(
            right,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return False


def _fail(component: str, *, cause: Exception | None = None) -> NoReturn:
    error = AgentRunLaunchGateError(component)
    if cause is not None:
        raise error from cause
    raise error


__all__ = [
    "AGENT_RUN_LAUNCH_GATE_FAILED",
    "AgentRunLaunchAuthorization",
    "AgentRunLaunchGateError",
    "revalidate_agent_run_launch_authorization",
    "require_agent_run_launch_authorization",
]
