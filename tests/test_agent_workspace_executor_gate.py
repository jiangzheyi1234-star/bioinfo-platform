from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from apps.remote_runner import agent_process_launcher_gate as launcher_gate_module
from apps.remote_runner import executor as executor_module
from apps.remote_runner import run_worker as run_worker_module
from apps.remote_runner.agent_workspace_manifest import scan_agent_generation_bundle
from apps.remote_runner.run_worker import process_next_run_job
from apps.remote_runner.storage import fetch_run, update_run_state
from apps.remote_runner.storage_core import get_connection
from apps.remote_runner.workflow_runtime_config import resolve_default_conda_prefix
from tests.test_agent_run_launch_gate import _authorize


pytest_plugins = ("tests.test_agent_fastq_qc_execution_candidate",)


@pytest.fixture(autouse=True)
def exercise_dormant_executor_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep deep workspace defenses covered behind the production hard gate."""

    monkeypatch.setattr(
        launcher_gate_module,
        "require_durable_agent_process_launcher",
        lambda: None,
    )


class _SuccessfulProcess:
    returncode = 0
    stdout = "ok"
    stderr = ""


@pytest.fixture
def workspace_candidate(candidate_case: dict[str, Any]):
    yield candidate_case
    _restore_writable(Path(candidate_case["cfg"].work_dir))


def _complete_artifact_collection(
    cfg: Any,
    run_id: str,
    *,
    request_id: str,
    attempt_id: str,
    lease_generation: int,
    result_dir: str,
    **_kwargs: Any,
) -> list[Any]:
    update_run_state(
        cfg,
        run_id=run_id,
        status="completed",
        stage="finalize",
        message="Agent workspace executor test completed.",
        request_id=request_id,
        result_dir=result_dir,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
    )
    return []


def test_agent_generated_bundle_is_sealed_before_both_snakemake_boundaries(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    claim: dict[str, Any] = {}
    observed_hashes: list[str] = []
    process_conda_prefixes: list[Path] = []
    process_workdirs: list[Path] = []
    shared_conda_prefix = resolve_default_conda_prefix(cfg)
    shared_marker = shared_conda_prefix / "forged-shared-env" / ".env_setup_done"
    shared_marker.parent.mkdir()
    shared_marker.write_text("forged\n", encoding="utf-8")

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        workdir = Path(claim["attempt"]["workDir"])
        process_workdir = Path(command[command.index("--directory") + 1])
        process_conda_prefix = Path(command[command.index("--conda-prefix") + 1])
        process_workdirs.append(process_workdir)
        process_conda_prefixes.append(process_conda_prefix)
        assert command.count("--conda-prefix") == 1
        assert command[command.index("--profile") + 1] == "none"
        snakefile = Path(command[command.index("--snakefile") + 1])
        cli_config = Path(command[command.index("--configfile") + 1])
        assert cli_config.is_absolute()
        assert cli_config.is_file()
        assert "configfile:" not in snakefile.read_text(encoding="utf-8")
        if not observed_hashes:
            assert not (process_workdir / "run-config.json").exists()
        observed = scan_agent_generation_bundle(workdir, require_sealed=True)
        observed_hashes.append(observed.manifest_hash)
        if len(observed_hashes) == 1:
            forged_env = process_conda_prefix / "forged-env"
            forged_env.mkdir(parents=True)
            (forged_env / ".env_setup_done").write_text("forged\n", encoding="utf-8")
        else:
            assert not (workdir / ".snakemake").exists()
            assert list(process_conda_prefix.iterdir()) == []
        assert shared_marker.read_text(encoding="utf-8") == "forged\n"
        return _SuccessfulProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        executor_module, "_collect_artifacts", _complete_artifact_collection
    )

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-success-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=lambda value: claim.update(value),
    )

    assert result["executionError"] == ""
    assert result["attemptCompletion"]["state"] == "succeeded"
    assert len(observed_hashes) == 2
    assert observed_hashes[0] == observed_hashes[1]
    workdir = Path(claim["attempt"]["workDir"])
    assert process_workdirs == [
        Path(cfg.work_dir)
        / "dry-runs"
        / result["attemptId"]
        / f"generation-{result['leaseGeneration']}",
        workdir,
    ]
    assert process_conda_prefixes == [
        Path(cfg.work_dir)
        / "conda-prefixes"
        / f"{result['attemptId']}.generation-{result['leaseGeneration']}.dry-run",
        Path(cfg.work_dir)
        / "conda-prefixes"
        / f"{result['attemptId']}.generation-{result['leaseGeneration']}.real-run",
    ]
    assert process_conda_prefixes[0] != process_conda_prefixes[1]
    assert all(prefix != shared_conda_prefix for prefix in process_conda_prefixes)
    assert not (process_conda_prefixes[1] / "forged-env").exists()
    assert workdir == Path(cfg.work_dir) / "attempts" / result["attemptId"]
    assert fetch_run(cfg, run_id)["status"] == "completed"


def test_post_seal_tamper_is_rejected_before_dry_run_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    process_calls: list[list[str]] = []
    original_seed = executor_module.seed_run_rules_from_config

    def seed_then_tamper(*args: Any, **kwargs: Any) -> Any:
        result = original_seed(*args, **kwargs)
        config_path = Path(kwargs["config_path"])
        config_path.chmod(stat.S_IMODE(config_path.stat().st_mode) | stat.S_IWUSR)
        config_path.write_text('{"tampered": true}\n', encoding="utf-8")
        return result

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(executor_module, "seed_run_rules_from_config", seed_then_tamper)
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-pre-dry-tamper-worker",
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert process_calls == []
    _assert_path_free_workspace_failure(cfg, run_id)


def test_preplanted_snakemake_state_is_rejected_before_dry_run_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    process_calls: list[list[str]] = []
    original_seed = executor_module.seed_run_rules_from_config

    def seed_then_preplant_runtime(*args: Any, **kwargs: Any) -> Any:
        result = original_seed(*args, **kwargs)
        workdir = Path(kwargs["config_path"]).parent
        (workdir / ".snakemake" / "conda" / "forged-env").mkdir(parents=True)
        return result

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(
        executor_module,
        "seed_run_rules_from_config",
        seed_then_preplant_runtime,
    )
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-preplanted-snakemake-worker",
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert process_calls == []
    _assert_path_free_workspace_failure(cfg, run_id)


def test_preplanted_dry_run_scratch_is_rejected_before_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    process_calls: list[list[str]] = []
    original_seed = executor_module.seed_run_rules_from_config

    def seed_then_preplant_scratch(*args: Any, **kwargs: Any) -> Any:
        result = original_seed(*args, **kwargs)
        scratch = (
            Path(cfg.work_dir)
            / "dry-runs"
            / str(kwargs["attempt_id"])
            / f"generation-{kwargs['lease_generation']}"
        )
        (scratch / ".snakemake").mkdir()
        return result

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(
        executor_module,
        "seed_run_rules_from_config",
        seed_then_preplant_scratch,
    )
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-preplanted-dry-run-worker",
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert process_calls == []
    _assert_path_free_workspace_failure(cfg, run_id)


def test_cancel_probe_tamper_is_rejected_by_final_spawn_guard(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    claim: dict[str, Any] = {}
    cancel_checks = 0
    process_calls: list[list[str]] = []
    original_cancel_check = run_worker_module.run_attempt_cancel_requested

    def tamper_on_second_cancel_check(*args: Any, **kwargs: Any) -> bool:
        nonlocal cancel_checks
        cancel_checks += 1
        if cancel_checks == 2:
            config_path = Path(claim["attempt"]["workDir"]) / "run-config.json"
            config_path.chmod(stat.S_IMODE(config_path.stat().st_mode) | stat.S_IWUSR)
            config_path.write_text('{"tampered": true}\n', encoding="utf-8")
        return original_cancel_check(*args, **kwargs)

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(
        run_worker_module,
        "run_attempt_cancel_requested",
        tamper_on_second_cancel_check,
    )
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-cancel-window-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=lambda value: claim.update(value),
    )

    assert cancel_checks == 2
    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert process_calls == []
    _assert_path_free_workspace_failure(cfg, run_id)


def test_post_dry_run_tamper_is_rejected_before_run_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    claim: dict[str, Any] = {}
    process_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        if len(process_calls) == 1:
            config_path = Path(claim["attempt"]["workDir"]) / "run-config.json"
            config_path.chmod(stat.S_IMODE(config_path.stat().st_mode) | stat.S_IWUSR)
            config_path.write_text('{"tampered": true}\n', encoding="utf-8")
        return _SuccessfulProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-pre-run-tamper-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=lambda value: claim.update(value),
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert len(process_calls) == 1
    _assert_path_free_workspace_failure(cfg, run_id)


def test_dry_run_state_is_isolated_and_real_workdir_injection_is_rejected(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    claim: dict[str, Any] = {}
    process_calls: list[list[str]] = []
    original_mark_running = executor_module.mark_run_rules_running

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        if len(process_calls) == 1:
            dry_run_prefix = Path(command[command.index("--conda-prefix") + 1])
            forged_env = dry_run_prefix / "forged-env"
            forged_env.mkdir(parents=True)
            (forged_env / ".env_setup_done").write_text("forged\n", encoding="utf-8")
        return _SuccessfulProcess()

    def mark_running_then_inject(*args: Any, **kwargs: Any) -> Any:
        result = original_mark_running(*args, **kwargs)
        runtime = Path(claim["attempt"]["workDir"]) / ".snakemake"
        (runtime / "conda" / "forged-env").mkdir(parents=True)
        return result

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        executor_module,
        "mark_run_rules_running",
        mark_running_then_inject,
    )

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-dry-run-isolation-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=lambda value: claim.update(value),
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert len(process_calls) == 1
    _assert_path_free_workspace_failure(cfg, run_id)


def test_dry_run_cannot_seed_real_run_conda_prefix(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    claim: dict[str, Any] = {}
    process_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        if len(process_calls) == 1:
            generation = int(claim["leaseGeneration"])
            real_prefix = (
                Path(cfg.work_dir)
                / "conda-prefixes"
                / (f"{claim['attemptId']}.generation-{generation}.real-run")
            )
            (real_prefix / "forged-env").mkdir()
        return _SuccessfulProcess()

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-conda-cross-phase-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=lambda value: claim.update(value),
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert len(process_calls) == 1
    _assert_path_free_workspace_failure(cfg, run_id)


def test_expired_active_lease_is_rejected_before_dry_run_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    _authorize(workspace_candidate)
    process_calls: list[list[str]] = []
    original_seed = executor_module.seed_run_rules_from_config

    def seed_then_expire(*args: Any, **kwargs: Any) -> Any:
        result = original_seed(*args, **kwargs)
        with get_connection(cfg) as connection:
            connection.execute(
                "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z'"
            )
            connection.commit()
        return result

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(executor_module, "seed_run_rules_from_config", seed_then_expire)
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-expired-lease-worker",
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "RUN_ATTEMPT_STALE"
    assert result["attemptCompletion"] == {
        "accepted": False,
        "reason": "lease_expired",
    }
    assert process_calls == []


def test_lease_expiring_during_workspace_scan_is_rejected_before_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    _authorize(workspace_candidate)
    process_calls: list[list[str]] = []
    original_revalidate = (
        executor_module.AgentWorkspaceLaunchGuard.revalidate_before_process
    )
    expired = False

    def revalidate_then_expire(
        guard: executor_module.AgentWorkspaceLaunchGuard,
    ) -> Any:
        nonlocal expired
        observed = original_revalidate(guard)
        if not expired:
            expired = True
            with get_connection(cfg) as connection:
                connection.execute(
                    "UPDATE run_leases SET expires_at = '2000-01-01T00:00:00Z'"
                )
                connection.commit()
        return observed

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(
        executor_module.AgentWorkspaceLaunchGuard,
        "revalidate_before_process",
        revalidate_then_expire,
    )
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-expire-during-scan-worker",
        heartbeat_interval_seconds=0,
    )

    assert expired is True
    assert result["executionError"] == "RUN_ATTEMPT_STALE"
    assert result["attemptCompletion"] == {
        "accepted": False,
        "reason": "lease_expired",
    }
    assert process_calls == []


def test_injected_result_is_rejected_before_dry_run_process(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    _authorize(workspace_candidate)
    process_calls: list[list[str]] = []
    original_seed = executor_module.seed_run_rules_from_config

    def seed_then_inject(*args: Any, **kwargs: Any) -> Any:
        result = original_seed(*args, **kwargs)
        attempt_id = str(kwargs["attempt_id"])
        generation = int(kwargs["lease_generation"])
        result_dir = (
            Path(cfg.results_dir) / "attempts" / attempt_id / f"generation-{generation}"
        )
        (result_dir / "fastq-qc-summary.json").write_text(
            '{"injected": true}\n', encoding="utf-8"
        )
        return result

    def fake_run(command: list[str], **_kwargs: Any) -> _SuccessfulProcess:
        process_calls.append(command)
        return _SuccessfulProcess()

    monkeypatch.setattr(executor_module, "seed_run_rules_from_config", seed_then_inject)
    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)

    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-result-injection-worker",
        heartbeat_interval_seconds=0,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert process_calls == []


def test_tampered_claimed_workdir_is_rejected_before_generation(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    outside = tmp_path / "outside-workdir"
    outside.mkdir()
    marker = outside / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")

    def tamper_claim(claim: dict[str, Any]) -> None:
        claim["attempt"]["workDir"] = str(outside)

    monkeypatch.setattr(
        executor_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("no process may start"),
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-path-tamper-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=tamper_claim,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert marker.read_text(encoding="utf-8") == "unchanged"
    assert str(outside) not in json.dumps(result)
    _assert_path_free_workspace_failure(cfg, run_id)


def test_preplanted_attempt_directory_is_rejected_without_modification(
    workspace_candidate: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = workspace_candidate["cfg"]
    authorization = _authorize(workspace_candidate)
    run_id = authorization["run"]["runId"]
    marker: Path | None = None

    def preplant(claim: dict[str, Any]) -> None:
        nonlocal marker
        workdir = Path(claim["attempt"]["workDir"])
        workdir.mkdir(parents=True)
        marker = workdir / "marker.txt"
        marker.write_text("unchanged", encoding="utf-8")

    monkeypatch.setattr(
        executor_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("no process may start"),
    )
    result = process_next_run_job(
        cfg,
        worker_id="agent-workspace-preplant-worker",
        heartbeat_interval_seconds=0,
        on_attempt_claimed=preplant,
    )

    assert result["executionError"] == "AGENT_RUN_LAUNCH_GATE_FAILED: workspace"
    assert marker is not None
    assert marker.read_text(encoding="utf-8") == "unchanged"
    _assert_path_free_workspace_failure(cfg, run_id)


def _assert_path_free_workspace_failure(cfg: Any, run_id: str) -> None:
    run = fetch_run(cfg, run_id)
    assert run is not None
    assert run["status"] == "failed"
    assert run["stage"] == "agent_launch_gate"
    assert run["lastError"] == {
        "code": "AGENT_RUN_LAUNCH_GATE_FAILED",
        "message": "AGENT_RUN_LAUNCH_GATE_FAILED: workspace",
        "scope": "agent_launch_gate",
        "stage": "agent_launch_gate",
    }
    assert str(cfg.work_dir) not in json.dumps(run["lastError"])


def _restore_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            mode = stat.S_IMODE(path.lstat().st_mode)
            path.chmod(mode | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0))
        except OSError:
            pass
