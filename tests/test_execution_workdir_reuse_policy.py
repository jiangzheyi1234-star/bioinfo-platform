from __future__ import annotations

from pathlib import Path

from apps.remote_runner.execution_workdir_reuse_policy import build_workdir_reuse_policy


def test_workdir_reuse_policy_allows_managed_attempt_workdir_without_exposing_path(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_dir = work_root / "attempts" / "att_1"
    work_dir.mkdir(parents=True)
    (work_dir / "run-config.json").write_text("{}", encoding="utf-8")
    (work_dir / ".snakemake").mkdir()

    policy = build_workdir_reuse_policy(
        attempts=[_attempt(work_dir)],
        managed_work_dir=work_root,
    )

    assert policy == {
        "schemaVersion": "run-workdir-reuse-policy.v1",
        "available": True,
        "workDirReusable": True,
        "pathExposed": False,
        "managedRoot": True,
        "directoryPresent": True,
        "runConfigPresent": True,
        "snakemakeMetadataPresent": True,
        "latestAttempt": {
            "attemptId": "att_1",
            "attemptNumber": 1,
            "leaseGeneration": 1,
            "state": "failed",
        },
        "reasonCode": "WORKDIR_REUSABLE",
        "blockedReasonCodes": [],
    }


def test_workdir_reuse_policy_blocks_missing_config_without_path_leak(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    work_dir = work_root / "attempts" / "att_1"
    work_dir.mkdir(parents=True)

    policy = build_workdir_reuse_policy(attempts=[_attempt(work_dir)], managed_work_dir=work_root)

    assert policy["available"] is True
    assert policy["workDirReusable"] is False
    assert policy["directoryPresent"] is True
    assert policy["runConfigPresent"] is False
    assert policy["pathExposed"] is False
    assert policy["reasonCode"] == "RUN_CONFIG_NOT_FOUND"
    assert str(work_dir) not in str(policy)


def test_workdir_reuse_policy_blocks_workdir_outside_managed_root(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    outside = tmp_path / "outside" / "att_1"
    outside.mkdir(parents=True)
    (outside / "run-config.json").write_text("{}", encoding="utf-8")

    policy = build_workdir_reuse_policy(attempts=[_attempt(outside)], managed_work_dir=work_root)

    assert policy["available"] is False
    assert policy["workDirReusable"] is False
    assert policy["managedRoot"] is False
    assert policy["pathExposed"] is False
    assert policy["reasonCode"] == "WORKDIR_OUTSIDE_MANAGED_ROOT"


def _attempt(work_dir: Path) -> dict[str, object]:
    return {
        "attemptId": "att_1",
        "attemptNumber": 1,
        "leaseGeneration": 1,
        "state": "failed",
        "updatedAt": "2099-06-07T10:00:03Z",
        "workDir": str(work_dir),
    }
