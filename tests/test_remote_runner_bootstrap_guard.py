from __future__ import annotations

import pytest

from core.remote_runner.bootstrap_guard import (
    UPGRADE_ACTIVE_LEASES_REASON,
    UPGRADE_DIAGNOSTICS_UNAVAILABLE_REASON,
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
        {
            "schemaVersion": "execution-diagnostics.v1",
            "activeLeases": [
                {
                    "runId": "run_active",
                    "attemptId": "attempt_active",
                    "leaseGeneration": 3,
                    "workerId": "worker-a",
                    "slotId": "slot-0",
                    "expiresAt": "2099-06-07T10:05:00Z",
                }
            ],
        }
    )

    with pytest.raises(RemoteRunnerManagerError) as raised:
        manager._guard_bootstrap_without_active_leases(
            server_id="srv_test",
            ssh_service=object(),
            server_record={"bootstrap_version": "phase1-test"},
            bootstrap_metadata=metadata,
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["reasonCode"] == UPGRADE_ACTIVE_LEASES_REASON
    assert raised.value.detail["activeLeaseCount"] == 1
    assert metadata["upgradeGuard"]["checked"] is True
    assert metadata["upgradeGuard"]["activeLeaseCount"] == 1


def test_bootstrap_guard_skips_new_install_without_prior_runner() -> None:
    metadata = {}
    manager = GuardHarness({"activeLeases": [{"runId": "run_active"}]})

    manager._guard_bootstrap_without_active_leases(
        server_id="srv_test",
        ssh_service=object(),
        server_record={},
        bootstrap_metadata=metadata,
    )

    assert manager.calls == 0
    assert metadata == {}


def test_bootstrap_guard_records_unavailable_diagnostics_without_blocking_repair() -> None:
    metadata = {}
    manager = GuardHarness(RemoteRunnerClientError("runner not reachable"))

    manager._guard_bootstrap_without_active_leases(
        server_id="srv_test",
        ssh_service=object(),
        server_record={"bootstrap_version": "phase1-test"},
        bootstrap_metadata=metadata,
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
        manager._guard_bootstrap_without_active_leases(
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
