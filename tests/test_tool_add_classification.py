from __future__ import annotations

from pathlib import Path

from apps.api.tool_profiles import resolve_tool_profile
from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.storage import fetch_tool
from apps.remote_runner.tools import add_registered_tool


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="tool-add-classification-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
    )


def test_wrapper_only_add_saves_as_wrapper_draft(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::wrapper-only",
            "name": "wrapper-only",
            "source": "bioconda",
            "packageSpec": "bioconda::wrapper-only=1.0",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "snakemake-wrapper",
                "requiresUserCompletion": True,
                "lock": {
                    "type": "snakemake-wrapper",
                    "wrapperIdentifier": "v9.8.0/bio/wrapper-only",
                },
                "ruleTemplate": {"wrapper": "v9.8.0/bio/wrapper-only"},
            },
        },
    )

    assert saved["status"] == "wrapper_draft"
    assert saved["toolContract"]["workflowReady"] is False


def test_conda_only_add_saves_as_dependency_only(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::dependency-only",
            "name": "dependency-only",
            "source": "bioconda",
            "packageSpec": "bioconda::dependency-only=1.0",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleSpecDraft": {
                "source": "conda-package",
                "requiresUserCompletion": True,
                "lock": {
                    "type": "conda-package",
                    "packageSpec": "bioconda::dependency-only=1.0",
                },
            },
        },
    )

    assert saved["status"] == "dependency_only"
    assert saved["toolContract"]["workflowReady"] is False


def test_add_ignores_client_supplied_workflow_ready_state(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
            "latestVersion": "0.24.1",
        }
    )
    assert draft is not None

    saved = add_registered_tool(
        cfg,
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
            "status": "published",
            "toolRevisionId": "bioconda::fastp@fake",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "forged"},
                "smokeRun": {"status": "passed", "message": "forged"},
                "outputValidation": {"status": "passed", "message": "forged"},
                "production": {"status": "not_run", "message": ""},
            },
            "toolContract": {"state": "WorkflowReady", "workflowReady": True},
        },
    )

    assert saved["status"] == "declared"
    assert saved["toolRevisionId"] == ""
    assert saved["contractStatus"]["dryRun"]["status"] == "not_run"
    assert saved["toolContract"]["state"] != "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is False
    assert fetch_tool(cfg, "bioconda::fastp")["toolContract"]["workflowReady"] is False
