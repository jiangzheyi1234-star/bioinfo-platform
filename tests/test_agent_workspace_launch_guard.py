from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from apps.remote_runner import agent_workspace_launch_guard as launch_guard_module
from apps.remote_runner.agent_run_launch_gate import AgentRunLaunchGateError
from apps.remote_runner.agent_workspace_launch_guard import AgentWorkspaceLaunchGuard
from apps.remote_runner.agent_workspace_manifest import seal_agent_generation_bundle


_ATTEMPT_ID = "att_0123456789ab"


@pytest.fixture
def guard_case(tmp_path: Path):
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    root.mkdir()
    results_root.mkdir()
    workdir = root / "attempts" / _ATTEMPT_ID
    result_dir = results_root / "attempts" / _ATTEMPT_ID / "generation-1"
    guard = AgentWorkspaceLaunchGuard(
        managed_work_root=root,
        managed_results_root=results_root,
        attempt_id=_ATTEMPT_ID,
        lease_generation=1,
        claimed_workdir=workdir,
        result_dir=result_dir,
    )
    yield root, workdir, results_root, result_dir, guard
    _restore_writable(root)
    _restore_writable(results_root)


def _write_bundle(workdir: Path) -> None:
    workflow = workdir / "workflow"
    workflow.mkdir()
    (workdir / "run-config.json").write_text('{"cores": 2}\n', encoding="utf-8")
    (workflow / "Snakefile").write_text("rule all:\n    input: []\n", encoding="utf-8")


def test_constructor_creates_only_the_exact_empty_fresh_attempt_directory(
    guard_case,
) -> None:
    root, workdir, _results_root, result_dir, guard = guard_case

    assert workdir.is_dir()
    assert list(workdir.iterdir()) == []
    assert workdir == root / "attempts" / _ATTEMPT_ID
    assert result_dir.is_dir()
    assert guard.dry_run_workdir == (
        root / "dry-runs" / _ATTEMPT_ID / "generation-1"
    )
    assert list(guard.dry_run_workdir.iterdir()) == []
    assert guard.dry_run_conda_prefix == (
        root / "conda-prefixes" / f"{_ATTEMPT_ID}.generation-1.dry-run"
    )
    assert guard.run_conda_prefix == (
        root / "conda-prefixes" / f"{_ATTEMPT_ID}.generation-1.real-run"
    )
    assert list(guard.dry_run_conda_prefix.iterdir()) == []
    assert list(guard.run_conda_prefix.iterdir()) == []
    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate()


@pytest.mark.parametrize(
    ("attempt_id", "claimed_suffix"),
    [
        ("../escape", "att_0123456789ab"),
        (_ATTEMPT_ID, "att_ffffffffffff"),
    ],
)
def test_constructor_rejects_unbound_or_nonportable_claimed_workdir(
    tmp_path: Path,
    attempt_id: str,
    claimed_suffix: str,
) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    root.mkdir()
    results_root.mkdir()
    claimed = tmp_path / "outside" / claimed_suffix

    with pytest.raises(AgentRunLaunchGateError) as raised:
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=attempt_id,
            lease_generation=1,
            claimed_workdir=claimed,
            result_dir=(results_root / "attempts" / _ATTEMPT_ID / "generation-1"),
        )

    assert str(raised.value) == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert not claimed.exists()


def test_constructor_rejects_a_preplanted_attempt_directory(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    workdir = root / "attempts" / _ATTEMPT_ID
    workdir.mkdir(parents=True)
    results_root.mkdir()
    marker = workdir / "outside-control.txt"
    marker.write_text("do not modify", encoding="utf-8")

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=_ATTEMPT_ID,
            lease_generation=1,
            claimed_workdir=workdir,
            result_dir=(results_root / "attempts" / _ATTEMPT_ID / "generation-1"),
        )

    assert marker.read_text(encoding="utf-8") == "do not modify"


def test_constructor_rejects_a_preplanted_conda_prefix_without_modifying_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    prefix = (
        root / "conda-prefixes" / f"{_ATTEMPT_ID}.generation-1.dry-run"
    )
    prefix.mkdir(parents=True)
    results_root.mkdir()
    marker = prefix / "outside-control.txt"
    marker.write_text("do not modify", encoding="utf-8")

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=_ATTEMPT_ID,
            lease_generation=1,
            claimed_workdir=root / "attempts" / _ATTEMPT_ID,
            result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
        )

    assert marker.read_text(encoding="utf-8") == "do not modify"
    assert not (root / "attempts" / _ATTEMPT_ID).exists()


def test_constructor_rolls_back_a_leaf_when_its_final_scan_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    root.mkdir()
    results_root.mkdir()
    target = (
        root / "conda-prefixes" / f"{_ATTEMPT_ID}.generation-1.dry-run"
    )
    original_scandir = launch_guard_module.os.scandir
    failed = False

    def fail_target_once(path):
        nonlocal failed
        if Path(path) == target and not failed:
            failed = True
            raise OSError("injected final scan failure")
        return original_scandir(path)

    monkeypatch.setattr(launch_guard_module.os, "scandir", fail_target_once)

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=_ATTEMPT_ID,
            lease_generation=1,
            claimed_workdir=root / "attempts" / _ATTEMPT_ID,
            result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
        )

    assert failed is True
    assert not target.exists()
    assert not (root / "attempts" / _ATTEMPT_ID).exists()

    retry = AgentWorkspaceLaunchGuard(
        managed_work_root=root,
        managed_results_root=results_root,
        attempt_id=_ATTEMPT_ID,
        lease_generation=1,
        claimed_workdir=root / "attempts" / _ATTEMPT_ID,
        result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
    )
    assert retry.dry_run_conda_prefix == target


def test_constructor_journals_a_leaf_before_post_mkdir_chain_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    root.mkdir()
    results_root.mkdir()
    target = (
        root / "conda-prefixes" / f"{_ATTEMPT_ID}.generation-1.dry-run"
    )
    original_chain_check = launch_guard_module._require_real_directory_chain
    failed = False

    def fail_target_once(path: Path) -> None:
        nonlocal failed
        if Path(path) == target and target.exists() and not failed:
            failed = True
            raise OSError("injected post-mkdir chain failure")
        original_chain_check(path)

    monkeypatch.setattr(
        launch_guard_module,
        "_require_real_directory_chain",
        fail_target_once,
    )

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=_ATTEMPT_ID,
            lease_generation=1,
            claimed_workdir=root / "attempts" / _ATTEMPT_ID,
            result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
        )

    assert failed is True
    assert not target.exists()
    assert not (root / "attempts" / _ATTEMPT_ID).exists()

    retry = AgentWorkspaceLaunchGuard(
        managed_work_root=root,
        managed_results_root=results_root,
        attempt_id=_ATTEMPT_ID,
        lease_generation=1,
        claimed_workdir=root / "attempts" / _ATTEMPT_ID,
        result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
    )
    assert retry.dry_run_conda_prefix == target


def test_constructor_recovers_when_initial_leaf_identity_read_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    root.mkdir()
    results_root.mkdir()
    target = (
        root / "conda-prefixes" / f"{_ATTEMPT_ID}.generation-1.dry-run"
    )
    original_identity = launch_guard_module._directory_identity
    failed = False

    def fail_target_once(path: Path):
        nonlocal failed
        if Path(path) == target and target.exists() and not failed:
            failed = True
            raise OSError("injected initial identity failure")
        return original_identity(path)

    monkeypatch.setattr(
        launch_guard_module,
        "_directory_identity",
        fail_target_once,
    )

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=_ATTEMPT_ID,
            lease_generation=1,
            claimed_workdir=root / "attempts" / _ATTEMPT_ID,
            result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
        )

    assert failed is True
    assert not target.exists()
    assert not (root / "attempts" / _ATTEMPT_ID).exists()

    retry = AgentWorkspaceLaunchGuard(
        managed_work_root=root,
        managed_results_root=results_root,
        attempt_id=_ATTEMPT_ID,
        lease_generation=1,
        claimed_workdir=root / "attempts" / _ATTEMPT_ID,
        result_dir=results_root / "attempts" / _ATTEMPT_ID / "generation-1",
    )
    assert retry.dry_run_conda_prefix == target


def test_seal_returns_a_path_free_manifest_and_revalidates(guard_case) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)

    sealed = guard.seal()
    observed = guard.revalidate()

    assert observed == sealed == guard.sealed_manifest
    assert str(workdir) not in json.dumps(sealed.runtime_payload())
    assert [entry.relativePath for entry in sealed.entries] == [
        "run-config.json",
        "workflow/Snakefile",
    ]


def test_seal_rejects_preplanted_snakemake_runtime_state(guard_case) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    (workdir / ".snakemake" / "conda" / "forged-env").mkdir(parents=True)

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.seal()


def test_pre_dry_run_boundary_rejects_runtime_state_added_after_seal(
    guard_case,
) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    (workdir / ".snakemake" / "conda" / "forged-env").mkdir(parents=True)

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate_before_process()


def test_dry_run_runtime_state_is_isolated_from_the_real_workdir(
    guard_case,
) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    sealed = guard.seal()

    assert guard.revalidate_before_process() == sealed
    forged_env = guard.dry_run_conda_prefix / "forged-env"
    forged_env.mkdir(parents=True)
    (forged_env / ".env_setup_done").write_text("forged\n", encoding="utf-8")
    (guard.dry_run_workdir / ".snakemake").mkdir()
    assert guard.mark_dry_run_completed() == sealed
    assert list(guard.run_conda_prefix.iterdir()) == []
    assert guard.revalidate_before_process() == sealed
    assert {path.name for path in workdir.iterdir()} == {"run-config.json", "workflow"}

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate_before_process()


def test_pre_dry_run_boundary_requires_the_scratch_directory_to_remain_empty(
    guard_case,
) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    (guard.dry_run_workdir / ".snakemake").mkdir()

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate_before_process()


def test_post_dry_run_boundary_rejects_unknown_real_workdir_state(guard_case) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    guard.revalidate_before_process()
    (guard.dry_run_workdir / ".snakemake").mkdir()
    guard.mark_dry_run_completed()
    (workdir / "unexpected-runtime-state").write_text("forged\n", encoding="utf-8")

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate_before_process()


def test_dry_run_cannot_seed_the_real_run_conda_prefix(guard_case) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    guard.revalidate_before_process()
    (guard.run_conda_prefix / "forged-env").mkdir()

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.mark_dry_run_completed()


def test_pre_run_boundary_rejects_snakemake_state_in_the_real_workdir(
    guard_case,
) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    guard.revalidate_before_process()
    (guard.dry_run_workdir / ".snakemake").mkdir()
    guard.mark_dry_run_completed()
    (workdir / ".snakemake" / "conda" / "forged-env").mkdir(parents=True)

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate_before_process()


def test_revalidation_rejects_post_seal_bundle_mutation(guard_case) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    snakefile = workdir / "workflow" / "Snakefile"
    snakefile.chmod(stat.S_IMODE(snakefile.stat().st_mode) | stat.S_IWUSR)
    snakefile.write_text("rule changed:\n    input: []\n", encoding="utf-8")

    with pytest.raises(AgentRunLaunchGateError) as raised:
        guard.revalidate()

    assert str(raised.value) == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert str(workdir) not in str(raised.value)


def test_bundle_can_only_be_sealed_once(guard_case) -> None:
    _root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.seal()


def test_revalidation_rejects_whole_workdir_replacement(guard_case) -> None:
    root, workdir, _results_root, _result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    _restore_writable(workdir)
    workdir.rename(root / "replaced-attempt")
    workdir.mkdir()
    _write_bundle(workdir)
    seal_agent_generation_bundle(workdir)

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate()


def test_revalidation_rejects_whole_result_directory_replacement(guard_case) -> None:
    _root, workdir, results_root, result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    result_dir.rename(results_root / "replaced-result")
    result_dir.mkdir()

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate()


def test_revalidation_rejects_content_injected_into_bound_result_directory(
    guard_case,
) -> None:
    _root, workdir, _results_root, result_dir, guard = guard_case
    _write_bundle(workdir)
    guard.seal()
    (result_dir / "declared-output.txt").write_text("injected\n", encoding="utf-8")

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        guard.revalidate()


def test_constructor_rejects_preplanted_result_generation(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    results_root = tmp_path / "results"
    result_dir = results_root / "attempts" / _ATTEMPT_ID / "generation-1"
    root.mkdir()
    result_dir.mkdir(parents=True)
    marker = result_dir / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")

    with pytest.raises(AgentRunLaunchGateError, match="workspace"):
        AgentWorkspaceLaunchGuard(
            managed_work_root=root,
            managed_results_root=results_root,
            attempt_id=_ATTEMPT_ID,
            lease_generation=1,
            claimed_workdir=root / "attempts" / _ATTEMPT_ID,
            result_dir=result_dir,
        )

    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert not (root / "attempts" / _ATTEMPT_ID).exists()


def _restore_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            mode = stat.S_IMODE(path.lstat().st_mode)
            path.chmod(mode | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))
        except OSError:
            pass
