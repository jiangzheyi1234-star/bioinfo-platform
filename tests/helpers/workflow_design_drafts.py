from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from core.remote_runner.protocol_manifest import build_runner_protocol_manifest_fields
from tests.generated_workflow_test_helpers import test_tool_revision_id
from tests.helpers.reference_database import make_remote_runner_config


def workflow_design_config(tmp_path: Path) -> RemoteRunnerConfig:
    cfg = make_remote_runner_config(tmp_path, token="workflow-design-token")
    release_dir = (tmp_path / "release" / "remote_runner").resolve()
    wrapper_dir = release_dir / "snakemake_wrappers"
    for profile in ("fastqc", "multiqc"):
        wrapper = wrapper_dir / "v9.8.0" / "bio" / profile / "wrapper.py"
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(f"# {profile} test wrapper\n", encoding="utf-8")
    (release_dir / "runtime-proof-fixture.py").write_text(
        "# deterministic release fixture\n",
        encoding="utf-8",
    )
    shutil.copytree(
        Path(__file__).resolve().parents[2]
        / "apps"
        / "remote_runner"
        / "pipelines"
        / "generated-tool-run-v1",
        release_dir / "pipelines" / "generated-tool-run-v1",
        dirs_exist_ok=True,
    )
    release_root = release_dir.parent
    (release_root / "bootstrap_manifest.json").write_text(
        json.dumps(
            {
                "service": "h2ometa-remote",
                "version": cfg.version,
                "platform": "linux-64",
                "runtime": {
                    "provider": "bundled",
                    "python": "runtime/bin/python",
                    "sqlite": {"minimumVersion": "3.51.3"},
                },
                **build_runner_protocol_manifest_fields(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (release_root / "artifact.sha256").write_text("a" * 64 + "\n", encoding="ascii")
    runtime_root = (tmp_path / "workflow-runtime").resolve()
    runtime_bin = runtime_root / "workflow-env" / "bin"
    runtime_bin.mkdir(parents=True, exist_ok=True)
    executable_suffix = Path(sys.executable).suffix
    entrypoints = {
        "python": f"workflow-env/bin/python{executable_suffix}",
        "conda": f"workflow-env/bin/conda{executable_suffix}",
        "condaUnpack": f"workflow-env/bin/conda-unpack{executable_suffix}",
        "snakemake": f"workflow-env/bin/snakemake{executable_suffix}",
    }
    for relative_path in entrypoints.values():
        shutil.copy2(Path(sys.executable).resolve(), runtime_root / relative_path)
    source_venv_config = Path(sys.prefix) / "pyvenv.cfg"
    if source_venv_config.is_file():
        shutil.copy2(
            source_venv_config,
            runtime_root / "workflow-env" / "pyvenv.cfg",
        )
    reported_version = f"Python {platform.python_version()}"
    (runtime_root / "bootstrap_manifest.json").write_text(
        json.dumps(
            {
                "service": "h2ometa-workflow-runtime",
                "version": "0.1.0",
                "platform": "linux-64",
                "provider": "conda-pack",
                "entrypoints": entrypoints,
                "packages": {"snakemake": reported_version},
                "build": {
                    "runtimeSource": "unit-test-stub",
                    "lockFile": "",
                    "lockSha256": "",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (runtime_root / "artifact.sha256").write_text("b" * 64 + "\n", encoding="ascii")
    (runtime_root / "micromamba-root").mkdir(exist_ok=True)
    cfg.release_dir = str(release_dir)
    cfg.snakemake_command = str((runtime_root / entrypoints["snakemake"]).resolve())
    cfg.snakemake_version = reported_version
    cfg.managed_conda_command = str((runtime_root / entrypoints["conda"]).resolve())
    cfg.managed_conda_root_prefix = str((runtime_root / "micromamba-root").resolve())
    cfg.workflow_runtime_provider = "conda-pack"
    cfg.workflow_runtime_source = "artifact"
    cfg.workflow_runtime_version = "0.1.0"
    ensure_runtime_layout(cfg)
    return cfg


def install_agent_runtime_proof_test_seam(monkeypatch: Any) -> None:
    """Make the cross-platform fixture explicit without weakening production."""

    monkeypatch.setattr(
        "apps.remote_runner.agent_workflow_runtime._require_startup_release_binding",
        lambda **_kwargs: None,
    )


def workflow_design_tool_manifest(tool_id: str = "bioconda::qc=1.0") -> dict[str, Any]:
    return {
        "id": tool_id,
        "name": "qc",
        "source": "bioconda",
        "version": "1.0",
        "packageSpec": tool_id,
        "summary": "QC fixture",
        "ruleTemplate": {
            "inputs": [
                {
                    "name": "reads",
                    "required": True,
                    "type": "file",
                    "kind": "sequence_reads",
                    "mimeType": "text/plain",
                    "data": "data_2044",
                    "format": "format_1930",
                }
            ],
            "outputs": [
                {
                    "name": "report",
                    "path": "qc-report.txt",
                    "kind": "report",
                    "mimeType": "text/plain",
                    "type": "file",
                    "data": "data_0006",
                    "format": "format_1915",
                }
            ],
            "params": {"min_len": {"type": "integer", "default": 50}},
            "commandTemplate": "printf 'qc {params.min_len}' > {output.report:q}",
        },
    }


def workflow_design_draft(tool_id: str = "bioconda::qc=1.0") -> dict[str, Any]:
    return {
        "contractVersion": "workflow-design-draft-v1",
        "engine": "snakemake",
        "metadata": {
            "name": "QC workflow",
            "description": "Saved workflow design fixture",
            "projectId": "proj_design",
            "tags": ["qc"],
        },
        "inputs": [
            {
                "id": "reads",
                "role": "input",
                "path": "inputs/reads.fastq",
                "mimeType": "text/plain",
                "metadata": {"lane": "L001"},
            }
        ],
        "nodes": [
            {
                "id": "qc",
                "toolRevisionId": test_tool_revision_id(tool_id),
                "inputs": {"reads": {"fromInput": "input"}},
                "params": {"min_len": 80},
                "runtime": {"threads": 2, "schedulerResources": {"mem_mb": 256}},
                "resources": {},
                "outputs": {
                    "report": {"expose": True, "metadata": {"panel": "summary"}}
                },
                "metadata": {"uiGroup": "qc"},
                "provenance": {"source": "builder"},
            }
        ],
        "edges": [],
        "resources": {"bindings": {}, "metadata": {"selectionMode": "manual"}},
        "outputs": [
            {
                "from": {"nodeId": "qc", "port": "report"},
                "as": "qc_report",
                "metadata": {"audience": "operator"},
            }
        ],
        "provenance": {"createdBy": "test"},
    }
