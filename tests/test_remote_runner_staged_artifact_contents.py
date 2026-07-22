from __future__ import annotations

from pathlib import Path
import tarfile

from core.remote_runner.artifact import RemoteRunnerArtifactProvider
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from tests.test_remote_runner_artifact import (
    _extract_normalized,
    _local_staged_release_artifact_or_skip,
    _normalized_tar_names,
)


def test_local_staged_remote_runner_artifact_contains_current_runtime_contract() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )
    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(
        REMOTE_RUNNER_VERSION,
        platform="linux-64",
    )

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        selected = {
            name: _extract_normalized(archive, name)
            for name in (
                "remote_runner/config.py",
                "remote_runner/workflow_runtime_config.py",
                "remote_runner/health_service.py",
                "remote_runner/health_routes.py",
                "remote_runner/control_service.py",
                "remote_runner/main.py",
                "remote_runner/executor.py",
                "remote_runner/workflow_engine_adapter.py",
            )
        }
        assert all(value is not None for value in selected.values())
        texts = {
            name: value.read().decode("utf-8")
            for name, value in selected.items()
            if value is not None
        }

    assert "remote_runner/workflow_runtime_config.py" in names
    assert "remote_runner/health_service.py" in names
    assert "remote_runner/health_routes.py" in names
    assert "remote_runner/control_service.py" in names
    assert "remote_runner/workflow_engine_adapter.py" in names
    assert "workflow_runtime_version" in texts["remote_runner/config.py"]
    assert "inspect_workflow_runtime" in texts["remote_runner/config.py"]
    assert (
        "def inspect_workflow_runtime"
        in texts["remote_runner/workflow_runtime_config.py"]
    )
    assert (
        "def build_workflow_runtime_environment"
        in texts["remote_runner/workflow_runtime_config.py"]
    )
    assert 'checks["workflow_runtime"]' in texts["remote_runner/health_service.py"]
    assert "sqliteRuntime" in texts["remote_runner/health_service.py"]
    assert "health_ready_from_request" in texts["remote_runner/health_routes.py"]
    assert "build_health_ready_payload" in texts["remote_runner/control_service.py"]
    assert "app.include_router(health_router)" in texts["remote_runner/main.py"]
    assert "SnakemakeEngineAdapter" in texts["remote_runner/executor.py"]
    assert (
        "build_workflow_runtime_environment"
        in texts["remote_runner/workflow_engine_adapter.py"]
    )


def test_local_staged_remote_runner_artifact_matches_storage_core_source() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )
    with tarfile.open(bundle, "r:gz") as archive:
        storage_core = _extract_normalized(archive, "remote_runner/storage_core.py")
        assert storage_core is not None
        packaged_text = storage_core.read().decode("utf-8")

    source_text = (repo_root / "apps" / "remote_runner" / "storage_core.py").read_text(
        encoding="utf-8"
    )
    assert packaged_text == source_text


def test_local_staged_remote_runner_artifact_contains_workflow_design_contract_dependency() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )
    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(
        REMOTE_RUNNER_VERSION,
        platform="linux-64",
    )

    assert resolved.archive_path == bundle
    required_members = {
        "remote_runner/workflow_design_compiler.py",
        "remote_runner/workflow_design_planner.py",
        "remote_runner/workflow_design_routes.py",
        "remote_runner/workflow_design_storage.py",
        "remote_runner/workflow_design_submission.py",
    }
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        main = _extract_normalized(archive, "remote_runner/main.py")
        assert main is not None
        main_text = main.read().decode("utf-8")

    assert required_members.issubset(names)
    assert {
        "core/__init__.py",
        "core/async_boundary.py",
        "core/api_payloads.py",
        "core/api_responses.py",
        "core/contracts/__init__.py",
        "core/contracts/workflow_design.py",
        "core/problem_responses.py",
        "core/problem_status.py",
    }.issubset(names) or "remote_runner/workflow_design_contract.py" in names
    assert "workflow_design_router" in main_text
    assert "app.include_router(workflow_design_router)" in main_text


def test_local_staged_remote_runner_artifact_contains_tool_prepare_endpoint() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _local_staged_release_artifact_or_skip(
        repo_root,
        f"h2ometa-remote-runner-{REMOTE_RUNNER_VERSION}-linux-64.tar.gz",
    )
    resolved = RemoteRunnerArtifactProvider(repo_root=repo_root).resolve(
        REMOTE_RUNNER_VERSION,
        platform="linux-64",
    )

    assert resolved.archive_path == bundle
    with tarfile.open(bundle, "r:gz") as archive:
        names = _normalized_tar_names(archive)
        routes = _extract_normalized(archive, "remote_runner/tool_routes.py")
        service = _extract_normalized(archive, "remote_runner/tool_service.py")
        prepare_jobs = _extract_normalized(
            archive,
            "remote_runner/tool_prepare_jobs.py",
        )
        assert routes is not None
        assert service is not None
        assert prepare_jobs is not None
        routes_text = routes.read().decode("utf-8")
        service_text = service.read().decode("utf-8")
        prepare_jobs_text = prepare_jobs.read().decode("utf-8")

    assert {
        "remote_runner/tool_preparation.py",
        "remote_runner/tool_prepare_job_storage.py",
        "remote_runner/tool_prepare_jobs.py",
        "remote_runner/tool_revisions.py",
        "remote_runner/tool_service.py",
    }.issubset(names)
    assert "operation_id=REMOTE_ENDPOINTS[TOOL_INDEX_READ].operation_id" in routes_text
    assert (
        "operation_id=REMOTE_ENDPOINTS[TOOL_PREPARE_JOB_CREATE].operation_id"
        in routes_text
    )
    assert "list_tool_index_from_request" in service_text
    assert "create_tool_prepare_job_response_from_request" in service_text
    assert "run_tool_prepare_job" not in service_text
    assert "def run_tool_prepare_job" in prepare_jobs_text
