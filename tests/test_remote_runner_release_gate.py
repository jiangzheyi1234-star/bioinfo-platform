from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from core.contracts.runner_protocol import RUNNER_PROTOCOL_VERSION
from core.contracts.runner_protocol_runtime import (
    CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
)


def _load_module() -> Any:
    script = Path("scripts/remote_runner_release_gate.py")
    spec = importlib.util.spec_from_file_location("remote_runner_release_gate", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_staging_module() -> Any:
    script = Path("scripts/deploy_remote_runner_staging_artifact.py")
    spec = importlib.util.spec_from_file_location(
        "deploy_remote_runner_staging_artifact",
        script,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_gate_requires_explicit_destructive_acknowledgements(capsys) -> None:
    gate = _load_module()

    assert gate.main([]) == 2

    captured = capsys.readouterr()
    assert "--allow-two-slot is required" in captured.out


def test_release_gate_builds_real_two_slot_crash_and_policy_steps() -> None:
    gate = _load_module()

    steps = gate.build_steps(allow_two_slot=True, allow_runner_kill=True)

    assert [step.name for step in steps] == [
        "real-snakemake-two-slot",
        "worker-crash-restart-recovery",
        "execution-policy-acceptance",
    ]
    assert steps[0].command[-2:] == ["remote_two_slot_acceptance.py", "--allow-two-slot"] or (
        steps[0].command[-1] == "--allow-two-slot"
        and steps[0].command[-2].endswith("remote_two_slot_acceptance.py")
    )
    assert "--allow-runner-kill" in steps[1].command
    assert "--restart-timeout" in steps[1].command
    assert "90" in steps[1].command
    assert any(part.endswith("remote_worker_crash_recovery_acceptance.py") for part in steps[1].command)
    assert steps[2].command[-1] == "--allow-policy-restart"
    assert steps[2].command[-2].endswith("remote_execution_policy_acceptance.py")


def test_release_gate_can_include_optional_soak_step() -> None:
    gate = _load_module()

    steps = gate.build_steps(
        allow_two_slot=True,
        allow_runner_kill=True,
        include_soak=True,
        allow_soak=True,
        soak_iterations=3,
    )

    assert [step.name for step in steps] == [
        "real-snakemake-two-slot",
        "worker-crash-restart-recovery",
        "execution-policy-acceptance",
        "soak-stress-fault-injection",
    ]
    assert any(part.endswith("remote_runner_soak_acceptance.py") for part in steps[-1].command)
    assert "--allow-soak" in steps[-1].command
    assert "--allow-runner-kill" in steps[-1].command
    assert steps[-1].command[-2:] == ["--iterations", "3"]


def test_release_gate_requires_explicit_soak_acknowledgement() -> None:
    gate = _load_module()

    try:
        gate.build_steps(
            allow_two_slot=True,
            allow_runner_kill=True,
            include_soak=True,
            allow_soak=False,
        )
    except ValueError as exc:
        assert "--include-soak requires --allow-soak" in str(exc)
    else:
        raise AssertionError("soak gate accepted missing --allow-soak")


def test_release_gate_streams_output_and_collects_evidence_labels(monkeypatch, capsys) -> None:
    gate = _load_module()

    class FakeStdout:
        def __iter__(self):
            return iter(
                [
                    'CONCURRENCY_EVIDENCE: {"active": []}\n',
                    'OBSERVABILITY_EVIDENCE: {"schemaVersion": "execution-observability.v1"}\n',
                    'POLICY_BACKOFF_EVIDENCE: {"backoffSeconds": 12}\n',
                    'POST_ACCEPTANCE_INVARIANTS: {"ok": true}\n',
                    'SOAK_ACCEPTANCE_SUMMARY: {"ok": true}\n',
                    "RESULT: ok\n",
                ]
            )

    class FakeProcess:
        stdout = FakeStdout()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    result = gate.run_step(gate.GateStep(name="fake", command=["python", "fake.py"]))

    assert result["exitCode"] == 0
    assert result["evidenceLabels"] == [
        "CONCURRENCY_EVIDENCE",
        "OBSERVABILITY_EVIDENCE",
        "POLICY_BACKOFF_EVIDENCE",
        "POST_ACCEPTANCE_INVARIANTS",
        "SOAK_ACCEPTANCE_SUMMARY",
        "RESULT",
    ]
    assert result["evidence"] == [
        {"label": "CONCURRENCY_EVIDENCE", "payload": {"active": []}},
        {"label": "OBSERVABILITY_EVIDENCE", "payload": {"schemaVersion": "execution-observability.v1"}},
        {"label": "POLICY_BACKOFF_EVIDENCE", "payload": {"backoffSeconds": 12}},
        {"label": "POST_ACCEPTANCE_INVARIANTS", "payload": {"ok": True}},
        {"label": "SOAK_ACCEPTANCE_SUMMARY", "payload": {"ok": True}},
        {"label": "RESULT", "payload": {"ok": True}},
    ]
    captured = capsys.readouterr()
    assert "RELEASE_GATE_STEP_DONE" in captured.out


def test_release_gate_writes_machine_readable_evidence_json(tmp_path, monkeypatch) -> None:
    gate = _load_module()
    evidence_path = tmp_path / "release-gate-evidence.json"

    def fake_run_step(step):
        return {
            "name": step.name,
            "exitCode": 0,
            "startedAt": "2099-06-07T10:00:00Z",
            "finishedAt": "2099-06-07T10:00:01Z",
            "elapsedSeconds": 1.0,
            "evidenceLabels": ["RESULT"],
            "evidence": [{"label": "RESULT", "payload": {"ok": True}}],
        }

    monkeypatch.setattr(gate, "run_step", fake_run_step)
    monkeypatch.setattr(gate, "_source_commit", lambda: "abc123")
    monkeypatch.setattr(
        gate,
        "_validate_release_bundle_env",
        lambda: {"path": str(tmp_path / "bundle.tar.gz"), "sha256": "1" * 64, "markers": ["marker"]},
    )

    exit_code = gate.main(
        [
            "--allow-two-slot",
            "--allow-runner-kill",
            "--evidence-json",
            str(evidence_path),
        ]
    )

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["schemaVersion"] == "remote-runner-release-gate.v1"
    assert payload["ok"] is True
    assert payload["sourceCommit"] == "abc123"
    assert payload["remoteRunnerBundle"]["sha256"] == "1" * 64
    assert [step["name"] for step in payload["steps"]] == [
        "real-snakemake-two-slot",
        "worker-crash-restart-recovery",
        "execution-policy-acceptance",
    ]
    assert payload["steps"][0]["evidence"][0]["payload"] == {"ok": True}


def test_release_gate_requires_explicit_bundle_env(monkeypatch, capsys) -> None:
    gate = _load_module()
    monkeypatch.delenv("H2OMETA_REMOTE_RUNNER_BUNDLE", raising=False)

    assert gate.main(["--allow-two-slot", "--allow-runner-kill"]) == 2

    captured = capsys.readouterr()
    assert "H2OMETA_REMOTE_RUNNER_BUNDLE must point" in captured.out


def test_release_gate_and_staging_deploy_require_protocol_bundle_markers() -> None:
    gate = _load_module()
    staging_source = Path("scripts/deploy_remote_runner_staging_artifact.py").read_text(encoding="utf-8")

    assert gate.REQUIRED_BUNDLE_MARKERS["remote_runner/execution_observability.py"] == "execution-observability.v1"
    assert "executionObservability" in staging_source
    assert "execution_observability.py" in staging_source
    assert "execution-observability.v1" in staging_source
    assert gate.REQUIRED_BUNDLE_MARKERS["remote_runner/process_owner.py"] == (
        "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE"
    )
    assert gate.REQUIRED_BUNDLE_MARKERS[
        "core/contracts/runner_process_owner.py"
    ] == "h2ometa.runner-process-owner.v1"
    assert gate.REQUIRED_BUNDLE_MARKERS["h2ometa-remote.service"] == (
        "RestartPreventExitStatus=73 74 75"
    )
    assert "processOwnerEvidence" in staging_source
    assert "processOwnerRestartPrevention" in staging_source
    assert "REMOTE_RUNNER_PROCESS_OWNER_UNAVAILABLE" in staging_source
    assert "h2ometa.runner-process-owner.v1" in staging_source
    assert "RestartPreventExitStatus=73 74 75" in staging_source


def test_staging_deploy_fails_closed_before_building_remote_mutation() -> None:
    staging = _load_staging_module()
    with pytest.raises(
        RuntimeError,
        match="STAGING_PROTOCOL_ACTIVATION_REQUIRED",
    ):
        staging._remote_deploy_script(
            remote_artifact="/tmp/runner.tar.gz",
            artifact_sha256="a" * 64,
            runner_protocol_version=RUNNER_PROTOCOL_VERSION,
            runner_protocol_fingerprint=CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
            version="owner-v5",
            nonce="123456789abc",
        )

    source = Path("scripts/deploy_remote_runner_staging_artifact.py").read_text(
        encoding="utf-8"
    )
    assert "ssh_connect" not in source
    assert "exec_command" not in source
    assert "systemctl" not in source


@pytest.mark.parametrize(
    "version",
    [
        None,
        "",
        " owner-v5",
        "owner-v5 ",
        ".",
        "..",
        "../owner-v5",
        "owner/v5",
        "$(touch injected)",
        "`touch injected`",
        'owner"v5',
        "owner\nv5",
        "v" * 129,
        "版本5",
    ],
)
def test_staging_deploy_rejects_unsafe_artifact_versions(version: object) -> None:
    staging = _load_staging_module()

    with pytest.raises(ValueError, match="artifact version is invalid"):
        staging._remote_deploy_script(
            remote_artifact="/tmp/runner.tar.gz",
            artifact_sha256="a" * 64,
            runner_protocol_version=RUNNER_PROTOCOL_VERSION,
            runner_protocol_fingerprint=CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
            version=version,
            nonce="123456789abc",
        )


@pytest.mark.parametrize(
    "nonce",
    [None, "", "123456789ab", "123456789abcd", "123456789ABc", "../123456789", "$(hostname)12"],
)
def test_staging_deploy_rejects_unsafe_nonces(nonce: object) -> None:
    staging = _load_staging_module()

    with pytest.raises(ValueError, match="staging deploy nonce is invalid"):
        staging._remote_deploy_script(
            remote_artifact="/tmp/runner.tar.gz",
            artifact_sha256="a" * 64,
            runner_protocol_version=RUNNER_PROTOCOL_VERSION,
            runner_protocol_fingerprint=CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
            version="owner-v5",
            nonce=nonce,
        )


@pytest.mark.parametrize("digest", [None, "A" * 64, "a" * 63, "a" * 65])
def test_staging_deploy_rejects_noncanonical_digests(digest: object) -> None:
    staging = _load_staging_module()

    with pytest.raises(ValueError, match="staging artifact sha256 is invalid"):
        staging._remote_deploy_script(
            remote_artifact="/tmp/runner.tar.gz",
            artifact_sha256=digest,
            runner_protocol_version=RUNNER_PROTOCOL_VERSION,
            runner_protocol_fingerprint=CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
            version="owner-v5",
            nonce="123456789abc",
        )


def test_staging_deploy_requires_the_exact_current_protocol() -> None:
    staging = _load_staging_module()

    with pytest.raises(ValueError, match="PROTOCOL_EXPECTATION_MISMATCH"):
        staging._remote_deploy_script(
            remote_artifact="/tmp/runner.tar.gz",
            artifact_sha256="a" * 64,
            runner_protocol_version="runner-protocol.v01",
            runner_protocol_fingerprint=CURRENT_RUNNER_PROTOCOL_FINGERPRINT,
            version="owner-v5",
            nonce="123456789abc",
        )


def test_release_gate_redacts_sensitive_evidence_payloads() -> None:
    gate = _load_module()

    parsed = gate._parse_evidence_line(
        'ACCEPTANCE_SUMMARY: {"token": "SECRET_TOKEN_CANARY", '
        '"authorization": "Bearer SECRET_AUTH_CANARY", '
        '"nested": {"keyFile": "C:/Users/Administrator/.ssh/SECRET_KEY_CANARY"}}\n'
    )

    serialized = json.dumps(parsed, sort_keys=True)
    assert "SECRET_TOKEN_CANARY" not in serialized
    assert "SECRET_AUTH_CANARY" not in serialized
    assert "SECRET_KEY_CANARY" not in serialized
    assert serialized.count("[REDACTED]") == 3
