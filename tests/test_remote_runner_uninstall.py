from __future__ import annotations

import pytest

from core.remote_runner.errors import RemoteRunnerManagerError
from core.remote_runner.uninstall import (
    RUNNER_UNINSTALL_ACTIVE_LEASES_REASON,
    RUNNER_UNINSTALL_BLOCKED_REASON,
    RUNNER_UNINSTALL_CONFIRMATION,
    RUNNER_UNINSTALL_PLAN_CHANGED_REASON,
    RUNNER_UNINSTALL_SCHEMA_VERSION,
    RemoteRunnerUninstallMixin,
)


class FakeSshService:
    def __init__(self) -> None:
        self.uninstall_command = ""

    def run(self, command: str, timeout: int = 10):
        if "H2OMETA_LIST_UNINSTALL_TARGETS" in command:
            return (
                0,
                "\n".join(
                    [
                        "current-symlink\t/home/tester/.h2ometa/runner/current\tsymlink\t/home/tester/.h2ometa/runner/releases/0.1.2",
                        "releases-dir\t/home/tester/.h2ometa/runner/releases\tdirectory\t/home/tester/.h2ometa/runner/releases",
                        "runner-config\t/home/tester/.h2ometa/runner/shared/config/runner.json\tfile\t/home/tester/.h2ometa/runner/shared/config/runner.json",
                        "runtime-state\t/home/tester/.h2ometa/runner/shared/runtime/runner-state.json\tfile\t/home/tester/.h2ometa/runner/shared/runtime/runner-state.json",
                        "workflow-profile\t/home/tester/.h2ometa/runner/shared/config/snakemake/default/profile.v9+.yaml\tfile\t/home/tester/.h2ometa/runner/shared/config/snakemake/default/profile.v9+.yaml",
                        "systemd-user-unit\t/home/tester/.config/systemd/user/h2ometa-remote.service\tsystemd-unit\t/home/tester/.config/systemd/user/h2ometa-remote.service",
                        "runner-bundle\t/home/tester/.h2ometa/runner/bundle-0.1.2.tar.gz\tfile\t/home/tester/.h2ometa/runner/bundle-0.1.2.tar.gz",
                    ]
                ),
                "",
            )
        if "H2OMETA_UNINSTALL_RUNNER" in command:
            self.uninstall_command = command
            return (
                0,
                '[{"kind":"symlink","name":"current-symlink","path":"/home/tester/.h2ometa/runner/current"}]\n',
                "",
            )
        if "H2OMETA_CLEAR_UNINSTALL_GUARD" in command:
            return 0, '{"reason":"released","released":true}\n', ""
        raise AssertionError(f"unexpected command: {command}")


class UninstallHarness(RemoteRunnerUninstallMixin):
    _manager_error = RemoteRunnerManagerError

    def __init__(
        self,
        *,
        diagnostics: dict[str, object] | None = None,
        guard_payload: dict[str, object] | None = None,
    ) -> None:
        self.diagnostics = diagnostics or _diagnostics()
        self.guard_payload = guard_payload
        self.lock_events: list[str] = []
        self.lifecycle_requests: list[dict[str, object]] = []

    def _resolve_remote_home(self, _ssh_service) -> str:
        return "/home/tester"

    def get_execution_diagnostics(self, **_kwargs):
        return self.diagnostics

    def request_execution_lifecycle_guard(self, **kwargs):
        self.lifecycle_requests.append(dict(kwargs))
        payload = self.guard_payload or _lifecycle_guard_payload(
            action=str(kwargs["action"]),
            owner=str(kwargs["owner"]),
        )
        if payload.get("blockReasons"):
            raise RemoteRunnerManagerError(
                "remote runner execution lifecycle guard blocked",
                status_code=409,
                detail=payload,
            )
        return payload

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


def _diagnostics(
    *,
    ok: bool = True,
    active_leases: list[dict[str, object]] | None = None,
    allocated_resources: list[dict[str, object]] | None = None,
    claimed_jobs: int = 0,
    running_slots: int = 0,
) -> dict[str, object]:
    return {
        "schemaVersion": "execution-diagnostics.v1",
        "ok": ok,
        "activeLeases": active_leases or [],
        "allocatedResources": allocated_resources or [],
        "resourceWaits": [],
        "workerHealth": {
            "claimedJobs": claimed_jobs,
            "workers": [{"slots": [{"state": "running"} for _index in range(running_slots)]}],
        },
        "queueMetrics": {"claimedJobs": claimed_jobs},
    }


def test_uninstall_preview_lists_control_plane_targets_and_preserves_shared_state() -> None:
    plan = UninstallHarness().preview_uninstall(
        server_id="srv_test",
        ssh_service=FakeSshService(),
        server_record={"bootstrap_version": "0.1.2"},
    )

    by_name = {item["name"]: item for item in plan["uninstallTargets"]}
    preserved = {item["path"] for item in plan["preservedPaths"]}

    assert plan["schemaVersion"] == RUNNER_UNINSTALL_SCHEMA_VERSION
    assert plan["controlPlaneOnly"] is True
    assert plan["blockReasons"] == []
    assert plan["targetCount"] == 7
    assert by_name["current-symlink"]["kind"] == "symlink"
    assert by_name["releases-dir"]["kind"] == "directory"
    assert by_name["systemd-user-unit"]["kind"] == "systemd-unit"
    assert "/home/tester/.h2ometa/runner/shared/data" in preserved
    assert "/home/tester/.h2ometa/runner/shared/results" in preserved
    assert "/home/tester/.h2ometa/runner/tools" in preserved
    assert len(plan["planHash"]) == 64


def test_uninstall_run_stops_and_removes_only_control_plane_targets_with_matching_plan_hash() -> None:
    ssh = FakeSshService()
    manager = UninstallHarness()
    plan = manager.preview_uninstall(
        server_id="srv_test",
        ssh_service=ssh,
        server_record={"bootstrap_version": "0.1.2"},
    )

    result = manager.run_uninstall(
        server_id="srv_test",
        ssh_service=ssh,
        server_record={"bootstrap_version": "0.1.2"},
        confirmation=RUNNER_UNINSTALL_CONFIRMATION,
        plan_hash=plan["planHash"],
    )

    assert manager.lock_events == ["acquire", "release"]
    assert manager.lifecycle_requests == [
        {
            "server_id": "srv_test",
            "ssh_service": ssh,
            "server_record": {"bootstrap_version": "0.1.2"},
            "action": "uninstall",
            "owner": "srv_test:uninstall:lifecycle",
            "ttl_seconds": 600,
            "timeout": 30,
        }
    ]
    assert result["removedTargetCount"] == 1
    assert result["removedTargets"][0]["name"] == "current-symlink"
    assert result["executionLifecycleGuard"]["action"] == "uninstall"
    assert result["executionLifecycleGuardRelease"]["released"] is True
    assert "systemctl --user stop h2ometa-remote.service" in ssh.uninstall_command
    assert "shared/data" not in ssh.uninstall_command
    assert "shared/results" not in ssh.uninstall_command


def test_uninstall_blocks_when_execution_state_is_not_idle() -> None:
    manager = UninstallHarness(
        diagnostics=_diagnostics(
            ok=False,
            allocated_resources=[{"runId": "run_allocated"}],
            claimed_jobs=1,
            running_slots=1,
        )
    )
    plan = manager.preview_uninstall(
        server_id="srv_test",
        ssh_service=FakeSshService(),
        server_record={"bootstrap_version": "0.1.2"},
    )

    assert set(plan["blockReasons"]) == {
        "execution-diagnostics-not-ok",
        "allocated-resources",
        "claimed-jobs",
        "running-worker-slots",
    }

    with pytest.raises(RemoteRunnerManagerError) as blocked:
        manager.run_uninstall(
            server_id="srv_test",
            ssh_service=FakeSshService(),
            server_record={"bootstrap_version": "0.1.2"},
            confirmation=RUNNER_UNINSTALL_CONFIRMATION,
            plan_hash=plan["planHash"],
        )

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == RUNNER_UNINSTALL_BLOCKED_REASON
    assert blocked.value.detail["blockReasons"] == plan["blockReasons"]
    assert manager.lifecycle_requests == []


def test_uninstall_run_rechecks_lifecycle_guard_before_destructive_uninstall() -> None:
    ssh = FakeSshService()
    manager = UninstallHarness(
        guard_payload=_lifecycle_guard_payload(
            active_leases=[{"runId": "run_raced"}],
            block_reasons=["active-workflow-leases"],
        )
    )
    plan = manager.preview_uninstall(
        server_id="srv_test",
        ssh_service=ssh,
        server_record={"bootstrap_version": "0.1.2"},
    )

    with pytest.raises(RemoteRunnerManagerError) as blocked:
        manager.run_uninstall(
            server_id="srv_test",
            ssh_service=ssh,
            server_record={"bootstrap_version": "0.1.2"},
            confirmation=RUNNER_UNINSTALL_CONFIRMATION,
            plan_hash=plan["planHash"],
        )

    assert blocked.value.status_code == 409
    assert blocked.value.detail["reasonCode"] == RUNNER_UNINSTALL_ACTIVE_LEASES_REASON
    assert manager.lifecycle_requests[0]["action"] == "uninstall"
    assert ssh.uninstall_command == ""


def test_uninstall_run_rejects_active_leases_and_stale_plan_hash() -> None:
    with pytest.raises(RemoteRunnerManagerError) as active:
        UninstallHarness(diagnostics=_diagnostics(active_leases=[{"runId": "run_active"}])).run_uninstall(
            server_id="srv_test",
            ssh_service=FakeSshService(),
            server_record={"bootstrap_version": "0.1.2"},
            confirmation=RUNNER_UNINSTALL_CONFIRMATION,
            plan_hash="0" * 64,
        )
    assert active.value.status_code == 409
    assert active.value.detail["reasonCode"] == RUNNER_UNINSTALL_ACTIVE_LEASES_REASON

    with pytest.raises(RemoteRunnerManagerError) as stale:
        stale_manager = UninstallHarness()
        stale_manager.run_uninstall(
            server_id="srv_test",
            ssh_service=FakeSshService(),
            server_record={"bootstrap_version": "0.1.2"},
            confirmation=RUNNER_UNINSTALL_CONFIRMATION,
            plan_hash="0" * 64,
        )
    assert stale.value.status_code == 409
    assert stale.value.detail["reasonCode"] == RUNNER_UNINSTALL_PLAN_CHANGED_REASON
    assert stale_manager.lifecycle_requests == []


def _lifecycle_guard_payload(
    *,
    action: str = "uninstall",
    owner: str = "srv_test:uninstall:lifecycle",
    active_leases: list[dict[str, object]] | None = None,
    block_reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schemaVersion": "h2ometa.execution-lifecycle-guard.v1",
        "action": action,
        "owner": owner,
        "idle": not block_reasons,
        "maintenanceActive": True,
        "requestedAt": "2099-06-07T10:00:00Z",
        "expiresAt": "2099-06-07T10:10:00Z",
        "activeWorkerCount": 1,
        "drainRequestedWorkerCount": 1,
        "activeLeaseCount": len(active_leases or []),
        "allocatedResourceCount": 0,
        "resourceWaitCount": 0,
        "queuedJobCount": 0,
        "claimedJobCount": 0,
        "runningSlotCount": 0,
        "blockReasons": block_reasons or [],
        "activeLeases": active_leases or [],
    }
