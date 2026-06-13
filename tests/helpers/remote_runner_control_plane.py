from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.remote_runner.artifact import WorkflowRuntimeArtifact
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.manager import RemoteRunnerManager

_ORIGINAL_ENSURE_WORKFLOW_RUNTIME = RemoteRunnerManager._ensure_workflow_runtime


def _is_remote_bundle_cleanup(cmd: str) -> bool:
    return cmd.startswith("rm -f ") and cmd.endswith(".tar.gz")


def _is_remote_config_atomic_move(cmd: str) -> bool:
    return (
        cmd.startswith("test -s ")
        and (
            "/shared/config/runner.json.tmp" in cmd
            or "/shared/config/snakemake/default/profile.v9+.yaml.tmp" in cmd
        )
        and " mv -f " in cmd
        and (
            "/shared/config/runner.json" in cmd
            or "/shared/config/snakemake/default/profile.v9+.yaml" in cmd
        )
    )


def _is_remote_current_release_read(cmd: str) -> bool:
    return cmd.startswith("readlink -f ") and cmd.endswith("/.h2ometa/runner/current")


def _is_remote_current_release_switch(cmd: str) -> bool:
    return "current.tmp" in cmd and "mv -Tf" in cmd and "/.h2ometa/runner/current" in cmd


def _is_remote_runner_config_read(cmd: str) -> bool:
    return cmd.startswith("cat ") and cmd.endswith("/.h2ometa/runner/shared/config/runner.json")


def _runtime_state_json(port: int = 43127) -> str:
    return json.dumps(
        {
            "service": "h2ometa-remote",
            "version": REMOTE_RUNNER_VERSION,
            "pid": 123,
            "bindHost": "127.0.0.1",
            "bindPort": port,
            "startedAt": "2026-04-22T00:00:00Z",
        }
    )


def _fake_runtime_dir(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    bin_dir = runtime / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    python.chmod(0o755)
    return runtime


def _write_file_summary_pipeline(release_dir: Path) -> None:
    (release_dir / "snakemake_wrappers").mkdir(parents=True, exist_ok=True)
    pipeline_dir = release_dir / "pipelines" / "file-summary-v1"
    (pipeline_dir / "workflow" / "envs").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / ".test").mkdir(parents=True, exist_ok=True)
    (pipeline_dir / "pipeline.json").write_text(
        json.dumps(
            {
                "pipelineId": "file-summary-v1",
                "name": "File Summary",
                "version": "1.0.0",
                "category": "Sequence Utilities",
                "icon": "file-text",
                "tags": ["fastq", "summary"],
                "author": "H2OMeta",
                "license": "internal",
                "status": "installed",
                "enabled": True,
                "snakefile": "workflow/Snakefile",
                "inputsSchema": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["uploadId"],
                        "properties": {
                            "uploadId": {"type": "string", "minLength": 1},
                            "filename": {"type": "string"},
                            "role": {"type": "string"},
                        },
                    },
                },
                "paramsSchema": {
                    "type": "object",
                    "properties": {"threads": {"type": "integer", "minimum": 1, "maximum": 64}},
                    "additionalProperties": True,
                },
                "outputSchema": {
                    "artifacts": [
                        {
                            "key": "summary",
                            "name": "Summary",
                            "kind": "report",
                            "mimeType": "text/plain",
                        }
                    ]
                },
                "execution": {"outputs": {"summary": "done.txt"}},
                "uiSchema": {"inputs": {"widget": "file-upload"}},
            }
        ),
        encoding="utf-8",
    )
    (pipeline_dir / "workflow" / "Snakefile").write_text("rule all:\n  input: 'done.txt'\n", encoding="utf-8")
    (pipeline_dir / "workflow" / "envs" / "base.yaml").write_text(
        "channels: [conda-forge]\ndependencies: [python=3.12]\n",
        encoding="utf-8",
    )
    (pipeline_dir / ".test" / "run-config.json").write_text(
        json.dumps({"inputs": [], "outputs": {"summary": "done.txt"}}),
        encoding="utf-8",
    )


def _fake_workflow_artifact() -> WorkflowRuntimeArtifact:
    return WorkflowRuntimeArtifact(
        version="0.1.0",
        platform="linux-64",
        archive_path=Path(__file__),
        sha256="f" * 64,
        manifest={
            "service": "h2ometa-workflow-runtime",
            "version": "0.1.0",
            "platform": "linux-64",
            "provider": "conda-pack",
            "entrypoints": {
                "python": "workflow-env/bin/python",
                "conda": "workflow-env/bin/conda",
                "condaUnpack": "workflow-env/bin/conda-unpack",
                "snakemake": "workflow-env/bin/snakemake",
            },
            "packages": {"snakemake": "9.19.0"},
        },
        python_entrypoint="workflow-env/bin/python",
        conda_entrypoint="workflow-env/bin/conda",
        conda_unpack_entrypoint="workflow-env/bin/conda-unpack",
        snakemake_entrypoint="workflow-env/bin/snakemake",
    )


@pytest.fixture(autouse=True)
def _default_workflow_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.remote_runner.manager.WorkflowRuntimeArtifactProvider.resolve",
        lambda self, **kwargs: _fake_workflow_artifact(),
    )
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._ensure_workflow_runtime",
        lambda self, **kwargs: self._build_workflow_runtime_metadata(
            artifact=kwargs["artifact"],
            remote_dir=kwargs["remote_dir"],
        ),
    )
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._verify_remote_config_payload",
        classmethod(lambda cls, **kwargs: None),
    )
    def fake_bootstrap_canary(self, *, client, server_id, bootstrap_metadata):
        canary = {
                "ok": True,
                "status": "passed",
                "pipeline_id": "file-summary-v1",
                "request_id": "req_bootstrap_canary_test",
                "run_id": "run_bootstrap_canary_test",
                "artifact_count": 3,
                "result_id": "res_bootstrap_canary_test",
                "preview_kind": "table",
                "checked_at": "2026-05-06T00:00:00Z",
            }
        bootstrap_metadata["canary"] = canary
        return canary

    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._run_bootstrap_canary",
        fake_bootstrap_canary,
    )
