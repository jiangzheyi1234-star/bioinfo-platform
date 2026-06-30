from __future__ import annotations

import pytest

from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.release_prune import (
    RELEASE_PRUNE_ACTIVE_LEASES_REASON,
    RELEASE_PRUNE_BLOCKED_REASON,
    RELEASE_PRUNE_CONFIRMATION,
    RELEASE_PRUNE_PLAN_CHANGED_REASON,
    RemoteRunnerReleasePruneMixin,
)


class FakeSshService:
    def __init__(
        self,
        *,
        config_release: str = "/home/tester/.h2ometa/runner/releases/0.1.1-control-plane",
    ) -> None:
        self.deleted_command = ""
        self.config_release = config_release

    def run(self, command: str, timeout: int = 10):
        if command.startswith("readlink -f "):
            return 0, "/home/tester/.h2ometa/runner/releases/0.1.2-control-plane\n", ""
        if command.startswith("cat "):
            return 0, f'{{"release_dir":"{self.config_release}"}}', ""
        if "H2OMETA_LIST_RELEASES" in command:
            return (
                0,
                "\n".join(
                    [
                        ".staging\t/home/tester/.h2ometa/runner/releases/.staging\t99",
                        "0.1.0-control-plane\t/home/tester/.h2ometa/runner/releases/0.1.0-control-plane\t10",
                        "0.1.1-control-plane\t/home/tester/.h2ometa/runner/releases/0.1.1-control-plane\t20",
                        "0.1.2-control-plane\t/home/tester/.h2ometa/runner/releases/0.1.2-control-plane\t30",
                        "backup\t/home/tester/.h2ometa/runner/releases/backup\t99",
                    ]
                ),
                "",
            )
        if "H2OMETA_PRUNE_RELEASES" in command:
            self.deleted_command = command
            return 0, "", ""
        raise AssertionError(f"unexpected command: {command}")


class PruneHarness(RemoteRunnerReleasePruneMixin):
    _manager_error = RemoteRunnerManagerError

    def __init__(
        self,
        *,
        diagnostics: dict[str, object] | None = None,
        active_leases: list[dict[str, object]] | None = None,
    ) -> None:
        self.active_leases = active_leases or []
        self.diagnostics = diagnostics
        self.lock_events: list[str] = []

    def _resolve_remote_home(self, _ssh_service) -> str:
        return "/home/tester"

    def get_execution_diagnostics(self, **_kwargs):
        if self.diagnostics is not None:
            return self.diagnostics
        return _diagnostics(active_leases=self.active_leases)

    def _acquire_remote_install_lock(self, **_kwargs) -> None:
        self.lock_events.append("acquire")

    def _release_remote_install_lock(self, **_kwargs) -> None:
        self.lock_events.append("release")

    @classmethod
    def _run_checked(cls, ssh_service, cmd: str, *, step: str, timeout: int):
        exit_code, stdout, stderr = ssh_service.run(cmd, timeout=timeout)
        if exit_code != 0:
            raise RemoteRunnerManagerError(f"{step}: {stderr or stdout}")
        return exit_code, stdout, stderr


def _server_record() -> dict[str, object]:
    return {
        "bootstrap_metadata": {
            "release_switch": {
                "previous_release": "/home/tester/.h2ometa/runner/releases/0.1.1-control-plane",
            }
        }
    }


def _diagnostics(
    *,
    ok: bool = True,
    active_leases: list[dict[str, object]] | None = None,
    allocated_resources: list[dict[str, object]] | None = None,
    resource_waits: list[dict[str, object]] | None = None,
    claimed_jobs: int = 0,
    running_slots: int = 0,
) -> dict[str, object]:
    slots = [{"state": "running"} for _index in range(running_slots)]
    return {
        "schemaVersion": "execution-diagnostics.v1",
        "ok": ok,
        "activeLeases": active_leases or [],
        "allocatedResources": allocated_resources or [],
        "resourceWaits": resource_waits or [],
        "workerHealth": {
            "claimedJobs": claimed_jobs,
            "workers": [{"slots": slots}],
        },
        "queueMetrics": {"claimedJobs": claimed_jobs},
    }


def test_release_prune_preview_protects_current_previous_and_active_leases() -> None:
    manager = PruneHarness(active_leases=[{"runId": "run_active"}])
    plan = manager.preview_release_prune(
        server_id="srv_test",
        ssh_service=FakeSshService(),
        server_record=_server_record(),
    )

    by_name = {item["name"]: item for item in plan["releases"]}

    assert plan["schemaVersion"] == "h2ometa.remote-runner-release-prune.v1"
    assert plan["activeLeaseCount"] == 1
    assert plan["deletableReleaseCount"] == 0
    assert plan["blockReasons"] == ["active-workflow-leases"]
    assert "backup" not in by_name
    assert ".staging" not in by_name
    assert "active-workflow-leases" in by_name["0.1.0-control-plane"]["protectedReasons"]
    assert "rollback-protected-release" in by_name["0.1.1-control-plane"]["protectedReasons"]
    assert "current-release" in by_name["0.1.2-control-plane"]["protectedReasons"]


def test_release_prune_run_deletes_only_unprotected_release_with_matching_plan_hash() -> None:
    ssh = FakeSshService()
    manager = PruneHarness()
    plan = manager.preview_release_prune(
        server_id="srv_test",
        ssh_service=ssh,
        server_record=_server_record(),
    )

    result = manager.run_release_prune(
        server_id="srv_test",
        ssh_service=ssh,
        server_record=_server_record(),
        confirmation=RELEASE_PRUNE_CONFIRMATION,
        plan_hash=plan["planHash"],
    )

    assert result["deletedReleaseCount"] == 1
    assert manager.lock_events == ["acquire", "release"]
    assert result["deletedReleases"] == [
        {
            "name": "0.1.0-control-plane",
            "path": "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane",
        }
    ]
    assert "/home/tester/.h2ometa/runner/releases/0.1.0-control-plane" in ssh.deleted_command
    assert "/home/tester/.h2ometa/runner/releases/0.1.1-control-plane" not in ssh.deleted_command
    assert "/home/tester/.h2ometa/runner/releases/0.1.2-control-plane" not in ssh.deleted_command


def test_release_prune_fallback_keeps_newest_non_current_release_without_metadata() -> None:
    manager = PruneHarness()
    plan = manager.preview_release_prune(
        server_id="srv_test",
        ssh_service=FakeSshService(config_release=""),
        server_record={},
    )

    by_name = {item["name"]: item for item in plan["releases"]}

    assert by_name["0.1.0-control-plane"]["deletable"] is True
    assert by_name["0.1.1-control-plane"]["deletable"] is False
    assert "fallback-rollback-release" in by_name["0.1.1-control-plane"]["protectedReasons"]
    assert by_name["0.1.2-control-plane"]["deletable"] is False


def test_release_prune_blocks_when_execution_diagnostics_are_not_idle() -> None:
    manager = PruneHarness(
        diagnostics=_diagnostics(
            ok=False,
            allocated_resources=[{"runId": "run_allocated"}],
            claimed_jobs=1,
            running_slots=1,
        )
    )
    plan = manager.preview_release_prune(
        server_id="srv_test",
        ssh_service=FakeSshService(),
        server_record=_server_record(),
    )

    assert set(plan["blockReasons"]) == {
        "execution-diagnostics-not-ok",
        "allocated-resources",
        "claimed-jobs",
        "running-worker-slots",
    }
    assert plan["deletableReleaseCount"] == 0

    with pytest.raises(RemoteRunnerManagerError) as blocked:
        manager.run_release_prune(
            server_id="srv_test",
            ssh_service=FakeSshService(),
            server_record=_server_record(),
            confirmation=RELEASE_PRUNE_CONFIRMATION,
            plan_hash=plan["planHash"],
        )

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == RELEASE_PRUNE_BLOCKED_REASON
    assert blocked.value.detail["blockReasons"] == plan["blockReasons"]


def test_release_prune_run_rejects_active_leases_and_stale_plan_hash() -> None:
    with pytest.raises(RemoteRunnerManagerError) as active:
        PruneHarness(active_leases=[{"runId": "run_active"}]).run_release_prune(
            server_id="srv_test",
            ssh_service=FakeSshService(),
            server_record=_server_record(),
            confirmation=RELEASE_PRUNE_CONFIRMATION,
            plan_hash="0" * 64,
        )
    assert active.value.status_code == 409
    assert active.value.detail["reasonCode"] == RELEASE_PRUNE_ACTIVE_LEASES_REASON

    with pytest.raises(RemoteRunnerManagerError) as stale:
        PruneHarness().run_release_prune(
            server_id="srv_test",
            ssh_service=FakeSshService(),
            server_record=_server_record(),
            confirmation=RELEASE_PRUNE_CONFIRMATION,
            plan_hash="0" * 64,
        )
    assert stale.value.status_code == 409
    assert stale.value.detail["reasonCode"] == RELEASE_PRUNE_PLAN_CHANGED_REASON
