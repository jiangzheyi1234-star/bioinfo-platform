from __future__ import annotations

import concurrent.futures
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from apps.remote_runner.config import RemoteRunnerConfig
import apps.remote_runner.tool_contract_validation as validation


def test_tool_contract_snakemake_runs_are_serialized(tmp_path: Path) -> None:
    cfg = RemoteRunnerConfig(
        snakemake_command="snakemake",
        managed_conda_command="conda",
        workflow_profile_dir="",
    )
    active = 0
    max_active = 0
    active_lock = threading.Lock()
    start = threading.Barrier(3)
    original_run = validation.subprocess.run

    def fake_run(_cmd, **_kwargs):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.1)
        with active_lock:
            active -= 1
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    def run_snakemake(index: int) -> None:
        start.wait(timeout=5)
        validation._run_snakemake(
            cfg,
            snakefile=tmp_path / f"Snakefile.{index}",
            work_dir=tmp_path / f"work-{index}",
            config_path=tmp_path / f"config-{index}.json",
            dry_run=False,
            timeout=5,
        )

    try:
        validation.subprocess.run = fake_run
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_snakemake, index) for index in range(2)]
            start.wait(timeout=5)
            for future in futures:
                future.result(timeout=5)
    finally:
        validation.subprocess.run = original_run

    assert max_active == 1
