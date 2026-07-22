from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.contracts.linux_process_incarnation import (
    build_linux_process_incarnation,
)
from core.contracts.runner_protocol_runtime import (
    build_runner_protocol_runtime_self_attestation,
)
from core.contracts.runner_process_owner import (
    build_runner_process_owner_reference,
)
from core.remote_runner.artifact import WorkflowRuntimeArtifact
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.manager import RemoteRunnerManager
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields
from core.remote_runner.readiness import (
    REMOTE_PROCESS_INCARNATION_PROBE_SENTINEL,
)

_ORIGINAL_ENSURE_WORKFLOW_RUNTIME = RemoteRunnerManager._ensure_workflow_runtime
_TEST_BOOT_ID = "11111111-2222-3333-4444-555555555555"
_TEST_PROC_START_TICKS = 777
_TEST_PROCESS_OWNER_LAUNCH_ID = "1" * 32
_TEST_PROCESS_OWNER_FINGERPRINT = "sha256:" + "a" * 64


def _is_remote_bundle_cleanup(cmd: str) -> bool:
    return cmd.startswith("rm -f ") and cmd.endswith(".tar.gz")


def _is_remote_config_atomic_move(cmd: str) -> bool:
    if (
        cmd.startswith("printf %s ")
        and "/artifact.sha256.tmp" in cmd
        and " mv -f " in cmd
    ):
        return True
    if cmd.startswith("rm -f ") and cmd.endswith(
        "/shared/config/runner.json.candidate"
    ):
        return True
    return (
        cmd.startswith("test -s ")
        and (
            "/shared/config/runner.json.tmp" in cmd
            or "/shared/config/runner.json.candidate" in cmd
            or "/shared/config/snakemake/default/profile.v9+.yaml.tmp" in cmd
        )
        and " mv -f " in cmd
        and (
            "/shared/config/runner.json" in cmd
            or "/shared/config/snakemake/default/profile.v9+.yaml" in cmd
        )
    )


def _is_remote_runner_config_read(cmd: str) -> bool:
    return cmd.startswith("cat ") and "/shared/config/runner.json" in cmd


def _is_remote_current_release_read(cmd: str) -> bool:
    return cmd.startswith("readlink -f ") and cmd.endswith("/.h2ometa/runner/current")


def _is_remote_current_release_switch(cmd: str) -> bool:
    return (
        "current.tmp" in cmd and "mv -Tf" in cmd and "/.h2ometa/runner/current" in cmd
    )


def _is_remote_runner_config_read(cmd: str) -> bool:
    return cmd.startswith("cat ") and cmd.endswith(
        "/.h2ometa/runner/shared/config/runner.json"
    )


def _is_remote_process_incarnation_probe(cmd: str) -> bool:
    return REMOTE_PROCESS_INCARNATION_PROBE_SENTINEL in cmd


def _process_incarnation_probe_output(
    *,
    boot_id: str = _TEST_BOOT_ID,
    pid: int = 123,
    start_ticks: int = _TEST_PROC_START_TICKS,
    comm: str = "remote runner ) worker",
) -> str:
    stat_fields = ["S", *("0" for _ in range(18)), str(start_ticks)]
    return f"{boot_id}\n{pid} ({comm}) {' '.join(stat_fields)}\n"


def _runtime_state_json(
    port: int = 43127,
    *,
    version: str = REMOTE_RUNNER_VERSION,
    pid: int = 123,
    boot_id: str = _TEST_BOOT_ID,
    start_ticks: int = _TEST_PROC_START_TICKS,
) -> str:
    return json.dumps(
        {
            "service": "h2ometa-remote",
            "version": version,
            "pid": pid,
            "bindHost": "127.0.0.1",
            "bindPort": port,
            "startedAt": "2026-04-22T00:00:00Z",
            "processIncarnation": build_linux_process_incarnation(
                boot_id=boot_id,
                pid=pid,
                proc_start_ticks=start_ticks,
            ),
            "runnerProtocol": build_runner_protocol_runtime_self_attestation(),
            "processOwner": build_runner_process_owner_reference(
                launch_id=_TEST_PROCESS_OWNER_LAUNCH_ID,
                owner_fingerprint=_TEST_PROCESS_OWNER_FINGERPRINT,
            ),
        }
    )


def _remote_runner_manifest(
    *,
    version: str = REMOTE_RUNNER_VERSION,
    platform: str = "linux-64",
) -> dict[str, object]:
    return {
        "service": "h2ometa-remote",
        "version": version,
        "platform": platform,
        "runtime": {
            "provider": "bundled",
            "python": "runtime/bin/python",
            "sqlite": {"minimumVersion": "3.51.3"},
        },
        **build_runner_protocol_manifest_fields(),
    }


def _remote_runner_protocol_config(
    *,
    version: str = REMOTE_RUNNER_VERSION,
    release: str | None = None,
) -> dict[str, str]:
    manifest = _remote_runner_manifest(version=version)
    descriptor = manifest["runnerProtocol"]
    assert isinstance(descriptor, dict)
    release_root = release or f"/home/tester/.h2ometa/runner/releases/{version}"
    return {
        "service_name": "h2ometa-remote",
        "version": version,
        "release_dir": f"{release_root}/remote_runner",
        "runner_python": f"{release_root}/runtime/bin/python",
        "runner_protocol_version": str(descriptor["protocolVersion"]),
        "runner_protocol_fingerprint": str(manifest["runnerProtocolFingerprint"]),
    }


def safe_remote_runner_sqlite_runtime_evidence() -> dict[str, object]:
    return {
        "minimumVersion": "3.51.3",
        "loadedVersion": "3.53.0",
        "sqlVersion": "3.53.0",
        "ok": True,
    }


def packaged_remote_runner_sqlite_evidence() -> dict[str, object]:
    return {
        "evidenceKind": "packaged-conda-metadata",
        "minimumVersion": "3.51.3",
        "packageName": "libsqlite",
        "packagedVersion": "3.53.0",
        "build": "hf4e2dac_0",
        "metadataMember": "runtime/conda-meta/libsqlite-3.53.0-hf4e2dac_0.json",
    }


def _health_endpoint_json(
    path: str, accepted_statuses: set[int] | None = None
) -> dict[str, object] | None:
    if path == "/health/startup":
        assert accepted_statuses == {200, 503}
        return {
            "status": "ok",
            "runnerProtocol": build_runner_protocol_runtime_self_attestation(),
            "sqliteRuntime": safe_remote_runner_sqlite_runtime_evidence(),
        }
    if path == "/health/live":
        assert accepted_statuses == {200}
        return {
            "status": "ok",
            "service": "h2ometa-remote",
            "runnerProtocol": build_runner_protocol_runtime_self_attestation(),
            "sqliteRuntime": safe_remote_runner_sqlite_runtime_evidence(),
        }
    if path == "/health/ready":
        assert accepted_statuses == {200, 503}
        return {
            "status": "ok",
            "runnerProtocol": build_runner_protocol_runtime_self_attestation(),
            "sqliteRuntime": safe_remote_runner_sqlite_runtime_evidence(),
        }
    return None


def _fake_runtime_dir(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime"
    bin_dir = runtime / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python = bin_dir / "python"
    python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
    python.chmod(0o755)
    conda_meta = runtime / "conda-meta"
    conda_meta.mkdir()
    (conda_meta / "libsqlite-3.53.0-hf4e2dac_0.json").write_text(
        json.dumps({"name": "libsqlite", "version": "3.53.0", "build": "hf4e2dac_0"}),
        encoding="utf-8",
    )
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
                    "properties": {
                        "threads": {"type": "integer", "minimum": 1, "maximum": 64}
                    },
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
    (pipeline_dir / "workflow" / "Snakefile").write_text(
        "rule all:\n  input: 'done.txt'\n", encoding="utf-8"
    )
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
        "core.remote_runner.manager.RemoteRunnerManager._require_local_service_runtime_artifact",
        lambda self, artifact: str(getattr(artifact, "sha256", "") or "a" * 64),
    )
    monkeypatch.setattr(
        "core.remote_runner.manager.RemoteRunnerManager._verify_and_publish_bundle_command",
        lambda self, **_kwargs: "mkdir -p /tmp/h2ometa-test-bundle-publish",
    )
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
