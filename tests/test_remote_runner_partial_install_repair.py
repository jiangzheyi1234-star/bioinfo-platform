from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.remote_runner.artifact import WorkflowRuntimeArtifact
from core.remote_runner.bundle import REMOTE_RUNNER_VERSION
from core.remote_runner.manager import RemoteRunnerManager


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


def test_bootstrap_repairs_partial_install_with_existing_workflow_runtime() -> None:
    manager = RemoteRunnerManager(workflow_artifact_provider=SimpleNamespace(resolve=lambda **_kwargs: _fake_workflow_artifact()))
    executed: list[str] = []
    uploads: list[tuple[str, str]] = []
    uploaded_config: dict[str, object] = {}

    class FakeArtifact:
        archive_path = Path(__file__)
        platform = "linux-64"
        sha256 = "b" * 64

    class FakeTunnel:
        local_port = 18765

    class FakeSSH:
        def run(self, cmd: str, timeout: int = 10):
            executed.append(cmd)
            if 'printf "%s" "$HOME"' in cmd:
                return 0, "/home/zyserver", ""
            if 'printf "%s:%s" "$(uname -s)" "$(uname -m)"' in cmd:
                return 0, "Linux:x86_64", ""
            if "systemctl --user show-environment" in cmd:
                return 0, "background_process\n", ""
            if f"mkdir /home/zyserver/.h2ometa/runner/locks/install-{REMOTE_RUNNER_VERSION}.lock" in cmd:
                return 0, "acquired", ""
            if "readlink -f /home/zyserver/.h2ometa/runner/current" in cmd:
                return 1, "", "No such file"
            if "mkdir -p" in cmd:
                return 0, "", ""
            if "pkill -f '[r]emote_runner.run'" in cmd and "runner-state.json" in cmd:
                return 0, "", ""
            if f"tar -xzf /home/zyserver/.h2ometa/runner/bundle-{REMOTE_RUNNER_VERSION}.tar.gz" in cmd:
                return 0, "", ""
            if f"rm -f /home/zyserver/.h2ometa/runner/bundle-{REMOTE_RUNNER_VERSION}.tar.gz" in cmd:
                return 0, "", ""
            if "artifact.sha256" in cmd and f"/releases/{REMOTE_RUNNER_VERSION}/artifact.sha256" in cmd:
                return 0, "", ""
            if "cat /home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/artifact.sha256" in cmd:
                return 0, "f" * 64, ""
            if "cat /home/zyserver/.h2ometa/runner/shared/config/runner.json" in cmd:
                return 0, json.dumps(uploaded_config), ""
            if "workflow-env/bin/snakemake" in cmd and "--version" in cmd:
                return 0, "9.19.0\n", ""
            if "runtime/bin/python -c \"from remote_runner.config import load_remote_runner_config, ensure_runtime_layout; ensure_runtime_layout(load_remote_runner_config())\"" in cmd:
                return 0, "", ""
            if "rm -f /home/zyserver/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, "", ""
            if f"ln -sfn /home/zyserver/.h2ometa/runner/releases/{REMOTE_RUNNER_VERSION} /home/zyserver/.h2ometa/runner/current" in cmd:
                return 0, "", ""
            if "bash /home/zyserver/.h2ometa/runner/current/start_service.sh" in cmd:
                return 0, "", ""
            if "cat /home/zyserver/.h2ometa/runner/shared/runtime/runner-state.json" in cmd:
                return 0, _runtime_state_json(), ""
            if "kill -0 123" in cmd:
                return 0, "", ""
            if f"rm -rf /home/zyserver/.h2ometa/runner/locks/install-{REMOTE_RUNNER_VERSION}.lock" in cmd:
                return 0, "", ""
            if "runner.json.tmp" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if "profile.v9+.yaml.tmp" in cmd and "mv -f" in cmd:
                return 0, "", ""
            if "current.tmp" in cmd and "mv -Tf" in cmd:
                return 0, "", ""
            raise AssertionError(f"unexpected command: {cmd}")

        def upload(self, local: str, remote: str) -> None:
            uploads.append((local, remote))
            if remote in {"/home/zyserver/.h2ometa/runner/shared/config/runner.json", "/home/zyserver/.h2ometa/runner/shared/config/runner.json.tmp"}:
                uploaded_config.update(json.loads(Path(local).read_text(encoding="utf-8")))

        def ensure_local_tunnel(self, *args, **kwargs):
            assert kwargs["remote_port"] == 43127
            return FakeTunnel()

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def get_health(self) -> dict[str, object]:
            return {
                "startup": {"ok": True, "message": "Remote runner config loaded."},
                "live": {"ok": True, "message": "Remote runner process is alive."},
                "ready": {"ok": True, "message": "Remote runner control plane is ready."},
                "reasonCode": "",
                "checkedAt": "2026-04-22T00:00:00Z",
            }

    def fake_canary(**kwargs):
        kwargs["bootstrap_metadata"]["canary"] = {
            "ok": True,
            "status": "passed",
            "pipeline_id": "file-summary-v1",
            "run_id": "run_bootstrap_canary_test",
            "artifact_count": 3,
        }
        return kwargs["bootstrap_metadata"]["canary"]

    with patch.object(manager, "_artifact_provider", SimpleNamespace(resolve=lambda **_kwargs: FakeArtifact())), patch(
        "core.remote_runner.manager.RemoteRunnerHttpClient", FakeClient
    ), patch("core.remote_runner.manager.store_runner_token", lambda **_kwargs: "runner://srv_test"), patch.object(
        manager, "_run_bootstrap_canary", fake_canary
    ):
        result = manager.bootstrap(
            server_id="srv_test",
            server={"label": "demo"},
            ssh_service=FakeSSH(),
            server_record={},
        )

    assert result["service_port"] == 43127
    assert (str(FakeArtifact.archive_path), f"/home/zyserver/.h2ometa/runner/bundle-{REMOTE_RUNNER_VERSION}.tar.gz") in uploads
    assert any(f"rm -f /home/zyserver/.h2ometa/runner/bundle-{REMOTE_RUNNER_VERSION}.tar.gz" in cmd for cmd in executed)
    assert uploaded_config["workflow_runtime_provider"] == "conda-pack"
    assert uploaded_config["workflow_runtime_source"] == "artifact"
    assert uploaded_config["workflow_runtime_version"] == "0.1.0"
    assert uploaded_config["snakemake_command"] == (
        "/home/zyserver/.h2ometa/runner/tools/workflow-runtime-0.1.0-linux-64/workflow-env/bin/snakemake"
    )
    assert uploaded_config["snakemake_version"] == "9.19.0"
    assert any("shared/config/runner.json" in remote for _local, remote in uploads)
    assert any("current.tmp" in cmd and "mv -Tf" in cmd for cmd in executed)
    assert any("bash /home/zyserver/.h2ometa/runner/current/start_service.sh" in cmd for cmd in executed)
    assert any("shared/runtime/runner-state.json" in cmd for cmd in executed)
