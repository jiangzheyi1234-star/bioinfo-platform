from __future__ import annotations

import pytest

from core.remote_runner.bootstrap_guard import (
    BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON,
    UPGRADE_ACTIVE_LEASES_REASON,
    UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON,
    UPGRADE_EXECUTION_BUSY_REASON,
    RemoteRunnerBootstrapGuardMixin,
)
from core.remote_runner.client import RemoteRunnerClientError
from core.remote_runner.errors import RemoteRunnerManagerError


class GuardHarness(RemoteRunnerBootstrapGuardMixin):
    _manager_error = RemoteRunnerManagerError

    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        self.calls = 0

    def get_execution_diagnostics(self, **_kwargs):
        self.calls += 1
        if isinstance(self.diagnostics, Exception):
            raise self.diagnostics
        return self.diagnostics


def test_bootstrap_guard_blocks_active_leases_before_destructive_upgrade() -> None:
    metadata = {}
    manager = GuardHarness(
        _diagnostics(
            active_leases=[
                {
                    "runId": "run_active",
                    "attemptId": "attempt_active",
                    "leaseGeneration": 3,
                    "workerId": "worker-a",
                    "slotId": "slot-0",
                    "expiresAt": "2099-06-07T10:05:00Z",
                }
            ],
        )
    )

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_when_execution_idle(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == UPGRADE_ACTIVE_LEASES_REASON
    assert raised.value.detail["activeLeaseCount"] == 1
    assert raised.value.detail["blockReasons"] == ["active-workflow-leases"]
    assert metadata["upgradeGuard"]["checked"] is True
    assert metadata["upgradeGuard"]["idle"] is False
    assert metadata["upgradeGuard"]["activeLeaseCount"] == 1
    assert metadata["upgradeGuard"]["blockReasons"] == ["active-workflow-leases"]


def test_bootstrap_guard_skips_new_install_without_prior_runner() -> None:
    metadata = {}
    manager = GuardHarness({"activeLeases": [{"runId": "run_active"}]})

    manager._guard_bootstrap_when_execution_idle(
        server_id="srv_test",
        ssh_service=object(),
        server_record={},
        bootstrap_metadata=metadata,
    )

    assert manager.calls == 0
    assert metadata == {}


def test_bootstrap_guard_allows_idle_prepared_runner_before_upgrade() -> None:
    metadata = {}
    manager = GuardHarness(_diagnostics())

    manager._guard_bootstrap_when_execution_idle(
        server_id="srv_test",
        ssh_service=object(),
        server_record={"bootstrap_version": "phase1-test"},
        bootstrap_metadata=metadata,
        bootstrap_action="upgrade",
    )

    assert metadata["upgradeGuard"] == {
        "schemaVersion": "h2ometa.remote-runner-upgrade-guard.v1",
        "checked": True,
        "idle": True,
        "activeLeaseCount": 0,
        "allocatedResourceCount": 0,
        "resourceWaitCount": 0,
        "claimedJobCount": 0,
        "runningSlotCount": 0,
        "blockReasons": [],
        "protectedLeases": [],
    }


def test_bootstrap_guard_blocks_upgrade_when_execution_state_is_not_idle() -> None:
    metadata = {}
    manager = GuardHarness(
        _diagnostics(
            ok=False,
            allocated_resources=[{"runId": "run_allocated"}],
            resource_waits=[{"runId": "run_waiting"}],
            claimed_jobs=2,
            running_slots=1,
        )
    )

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_when_execution_idle(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
            bootstrap_action="upgrade",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == UPGRADE_EXECUTION_BUSY_REASON
    assert raised.value.detail["nextAction"] == "WAIT_FOR_RUNS_OR_CANCEL_BEFORE_UPGRADE"
    assert raised.value.detail["claimedJobCount"] == 2
    assert raised.value.detail["runningSlotCount"] == 1
    assert set(raised.value.detail["blockReasons"]) == {
        "execution-diagnostics-not-ok",
        "allocated-resources",
        "queued-resource-waits",
        "claimed-jobs",
        "running-worker-slots",
    }
    assert metadata["upgradeGuard"]["idle"] is False
    assert metadata["upgradeGuard"]["allocatedResourceCount"] == 1
    assert metadata["upgradeGuard"]["resourceWaitCount"] == 1
    assert metadata["upgradeGuard"]["claimedJobCount"] == 2
    assert metadata["upgradeGuard"]["runningSlotCount"] == 1


def test_bootstrap_guard_blocks_prepared_repair_when_diagnostics_are_unavailable() -> None:
    metadata = {}
    manager = GuardHarness(RemoteRunnerClientError("runner not reachable"))

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_when_execution_idle(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == BOOTSTRAP_DIAGNOSTICS_UNAVAILABLE_REASON
    assert raised.value.detail["nextAction"] == "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_BOOTSTRAP"
    assert metadata["upgradeGuard"] == {
        "schemaVersion": "h2ometa.remote-runner-upgrade-guard.v1",
        "checked": False,
        "reason": "execution-diagnostics-unavailable",
        "message": "runner not reachable",
    }


def test_bootstrap_guard_allows_manual_stopped_runner_start_when_diagnostics_are_unavailable() -> None:
    metadata = {}
    manager = GuardHarness(RemoteRunnerClientError("runner not reachable"))

    manager._guard_bootstrap_when_execution_idle(
        server_id="srv_test",
        ssh_service=object(),
        server_record={
            "bootstrap_version": "phase1-test",
            "last_health_snapshot": {"reasonCode": "RUNNER_STOPPED"},
        },
        bootstrap_metadata=metadata,
        bootstrap_action="start",
    )

    assert metadata["upgradeGuard"] == {
        "schemaVersion": "h2ometa.remote-runner-upgrade-guard.v1",
        "checked": False,
        "reason": "execution-diagnostics-unavailable",
        "message": "runner not reachable",
    }


def test_bootstrap_guard_blocks_upgrade_when_diagnostics_are_unavailable() -> None:
    metadata = {}
    manager = GuardHarness(RemoteRunnerClientError("runner not reachable"))

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_when_execution_idle(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
            bootstrap_action="upgrade",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON
    assert raised.value.detail["nextAction"] == "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_UPGRADE"
    assert metadata["upgradeGuard"] == {
        "schemaVersion": "h2ometa.remote-runner-upgrade-guard.v1",
        "checked": False,
        "reason": "execution-diagnostics-unavailable",
        "message": "runner not reachable",
    }


def test_bootstrap_guard_blocks_upgrade_when_execution_diagnostics_schema_is_invalid() -> None:
    metadata = {}
    manager = GuardHarness({"schemaVersion": "execution-diagnostics.v1", "activeLeases": []})

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_when_execution_idle(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
            bootstrap_action="upgrade",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON
    assert raised.value.detail["nextAction"] == "REPAIR_RUNNER_DIAGNOSTICS_BEFORE_UPGRADE"
    assert metadata["upgradeGuard"]["checked"] is False
    assert metadata["upgradeGuard"]["reason"] == "execution-diagnostics-invalid"


def test_bootstrap_guard_blocks_upgrade_when_active_lease_shape_is_invalid() -> None:
    metadata = {}
    manager = GuardHarness(_diagnostics(active_leases=["not-an-object"]))

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_when_execution_idle(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
            bootstrap_action="upgrade",
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON
    assert metadata["upgradeGuard"]["reason"] == "execution-diagnostics-invalid"


def _diagnostics(
    *,
    ok: bool = True,
    active_leases: list[object] | None = None,
    allocated_resources: list[dict[str, object]] | None = None,
    resource_waits: list[dict[str, object]] | None = None,
    claimed_jobs: int = 0,
    running_slots: int = 0,
) -> dict[str, object]:
    return {
        "schemaVersion": "execution-diagnostics.v1",
        "ok": ok,
        "activeLeases": active_leases or [],
        "allocatedResources": allocated_resources or [],
        "resourceWaits": resource_waits or [],
        "workerHealth": {
            "claimedJobs": claimed_jobs,
            "summary": {"runningSlots": running_slots},
            "workers": [],
        },
        "queueMetrics": {
            "claimedJobs": claimed_jobs,
            "resourceWaitJobs": len(resource_waits or []),
        },
    }
