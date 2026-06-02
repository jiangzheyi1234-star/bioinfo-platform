from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_remote_clean_runner():
    path = Path(__file__).resolve().parents[1] / "skills" / "h2ometa-remote-smoke-test" / "scripts" / "remote_clean_runner.py"
    spec = importlib.util.spec_from_file_location("remote_clean_runner_under_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_runner_release_cleanup_is_default_and_preserves_runtime_and_test_data() -> None:
    module = _load_remote_clean_runner()

    plan = module.build_cleanup_plan(
        runner_version="0.1.1-control-plane",
        workflow_runtime_version="0.1.0",
        clean_runner_release=True,
        clean_workflow_runtime=False,
        clean_test_data=False,
    )

    assert "systemctl --user stop h2ometa-remote.service" in plan.command
    assert "$HOME/.h2ometa/runner/releases/0.1.1-control-plane" in plan.command
    assert "$HOME/.h2ometa/runner/current" in plan.command
    assert "rm -rf \"$HOME/.h2ometa/runner/current\"" not in plan.command
    assert "test -L \"$HOME/.h2ometa/runner/current\"" in plan.command
    assert "rm -f \"$HOME/.h2ometa/runner/current\"" in plan.command
    assert "workflow-runtime-0.1.0-linux-64" not in plan.command
    assert "database-mvp" not in plan.command
    assert plan.metadata["removed_runner_release"] == "~/.h2ometa/runner/releases/0.1.1-control-plane"
    assert plan.metadata["removed_workflow_runtime"] == ""
    assert plan.metadata["removed_test_data"] == []


def test_workflow_runtime_cleanup_is_explicit() -> None:
    module = _load_remote_clean_runner()

    plan = module.build_cleanup_plan(
        runner_version="0.1.1-control-plane",
        workflow_runtime_version="0.1.0",
        clean_runner_release=False,
        clean_workflow_runtime=True,
        clean_test_data=False,
    )

    assert "systemctl --user stop h2ometa-remote.service" in plan.command
    assert "$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64" in plan.command
    assert "$HOME/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64.tar.gz" in plan.command
    assert "$HOME/.h2ometa/runner/releases/0.1.1-control-plane" not in plan.command
    assert plan.metadata["removed_runner_release"] == ""
    assert plan.metadata["removed_workflow_runtime"] == "~/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64"


def test_test_data_cleanup_is_explicit_and_does_not_stop_runner() -> None:
    module = _load_remote_clean_runner()

    plan = module.build_cleanup_plan(
        runner_version="0.1.1-control-plane",
        workflow_runtime_version="0.1.0",
        clean_runner_release=False,
        clean_workflow_runtime=False,
        clean_test_data=True,
    )

    assert "systemctl --user stop" not in plan.command
    assert "$HOME/.h2ometa/runner/shared/data/database-mvp" in plan.command
    assert "$HOME/.h2ometa/runner/releases/0.1.1-control-plane" not in plan.command
    assert plan.metadata["removed_test_data"]
