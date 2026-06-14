from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    script = Path("scripts/remote_runner_soak_acceptance.py")
    spec = importlib.util.spec_from_file_location("remote_runner_soak_acceptance", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _entry(label: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"label": label, "payload": payload}


def _successful_steps() -> list[dict[str, Any]]:
    observability = {
        "schemaVersion": "execution-observability.v1",
        "sloOk": True,
        "sloStatus": "degraded",
        "alertCodes": ["SLOT_SATURATION"],
        "goldenSignals": {
            "errors": {"sqliteBusyErrors": 0},
            "saturation": {"queueBackpressure": {"resourceWaitJobs": 1}},
        },
    }
    return [
        {
            "name": "two-slot-stress-1",
            "iteration": 1,
            "exitCode": 0,
            "evidenceLabels": [
                "ACCEPTANCE_SUMMARY",
                "CONCURRENCY_EVIDENCE",
                "OBSERVABILITY_EVIDENCE",
                "POST_ACCEPTANCE_INVARIANTS",
                "RESOURCE_WAIT_EVIDENCE",
                "RESULT",
            ],
            "evidence": [
                _entry("CONCURRENCY_EVIDENCE", {"active": [{"runId": "run-a"}, {"runId": "run-b"}]}),
                _entry("RESOURCE_WAIT_EVIDENCE", {"runIds": ["run-c", "run-d"], "waiting": [{"runId": "run-d"}]}),
                _entry("OBSERVABILITY_EVIDENCE", observability),
                _entry(
                    "ACCEPTANCE_SUMMARY",
                    {
                        "twoSlotRunIds": ["run-a", "run-b"],
                        "resourceWaitRunIds": ["run-c", "run-d"],
                        "cancelledRunId": "run-a",
                        "postAcceptanceOk": True,
                    },
                ),
                _entry("POST_ACCEPTANCE_INVARIANTS", {"ok": True}),
                _entry("RESULT", {"ok": True}),
            ],
        },
        {
            "name": "worker-crash-restart-1",
            "iteration": 1,
            "exitCode": 0,
            "evidenceLabels": ["RECOVERY_EVIDENCE", "RESULT"],
            "evidence": [
                _entry(
                    "RECOVERY_EVIDENCE",
                    {
                        "runId": "run-e",
                        "oldWorkerPid": 101,
                        "newWorkerPid": 202,
                        "leaseGenerations": [1, 2],
                        "fenceEventCount": 1,
                    },
                ),
                _entry("RESULT", {"ok": True}),
            ],
        },
        {
            "name": "execution-policy-faults-1",
            "iteration": 1,
            "exitCode": 0,
            "evidenceLabels": [
                "OBSERVABILITY_EVIDENCE",
                "POLICY_ACCEPTANCE_SUMMARY",
                "POLICY_ATTEMPT_TIMEOUT_EVIDENCE",
                "POLICY_BACKOFF_EVIDENCE",
                "POLICY_QUEUE_TTL_EVIDENCE",
                "POST_POLICY_INVARIANTS",
                "RESULT",
            ],
            "evidence": [
                _entry("POLICY_BACKOFF_EVIDENCE", {"runId": "run-f", "backoffSeconds": 3}),
                _entry(
                    "POLICY_ATTEMPT_TIMEOUT_EVIDENCE",
                    {"runId": "run-g", "recovery": {"reasonCode": "ATTEMPT_TIMEOUT"}},
                ),
                _entry(
                    "POLICY_QUEUE_TTL_EVIDENCE",
                    {
                        "blockerRunId": "run-h",
                        "ttlRunId": "run-i",
                        "recovery": {"reasonCode": "QUEUE_TTL_EXCEEDED"},
                    },
                ),
                _entry("OBSERVABILITY_EVIDENCE", observability),
                _entry("POLICY_ACCEPTANCE_SUMMARY", {"postAcceptanceOk": True}),
                _entry("POST_POLICY_INVARIANTS", {"ok": True}),
                _entry("RESULT", {"ok": True}),
            ],
        },
    ]


def test_soak_requires_explicit_acknowledgements(capsys) -> None:
    soak = _load_module()

    assert soak.main([]) == 2

    captured = capsys.readouterr()
    assert "--allow-soak is required" in captured.out


def test_soak_builds_repeated_real_acceptance_steps() -> None:
    soak = _load_module()

    steps = soak.build_steps(iterations=2, allow_soak=True, allow_runner_kill=True)

    assert [step.name for step in steps] == [
        "two-slot-stress-1",
        "worker-crash-restart-1",
        "execution-policy-faults-1",
        "two-slot-stress-2",
        "worker-crash-restart-2",
        "execution-policy-faults-2",
    ]
    assert steps[0].command[-1] == "--allow-two-slot"
    assert "--allow-runner-kill" in steps[1].command
    assert steps[2].command[-1] == "--allow-policy-restart"


def test_soak_summary_requires_fault_and_observability_categories(monkeypatch) -> None:
    soak = _load_module()
    monkeypatch.setattr(soak, "_source_commit", lambda: "a" * 40)

    summary = soak.build_soak_summary(steps=_successful_steps(), iterations=1)
    observability = soak.build_soak_observability(summary)

    assert summary["ok"] is True
    assert summary["categories"]["workerCrashRestart"] is True
    assert summary["categories"]["leaseExpiryRecovery"] is True
    assert summary["categories"]["sqliteBackpressureObserved"] is True
    assert summary["failures"] == []
    assert observability["schemaVersion"] == "remote-runner-soak-observability.v1"
    assert observability["sloOk"] is True
    assert observability["alertCodes"] == ["SLOT_SATURATION"]


def test_soak_summary_rejects_missing_required_category(monkeypatch) -> None:
    soak = _load_module()
    monkeypatch.setattr(soak, "_source_commit", lambda: "a" * 40)
    steps = _successful_steps()
    steps[1]["evidence"] = []
    steps[1]["evidenceLabels"] = []

    summary = soak.build_soak_summary(steps=steps, iterations=1)

    assert summary["ok"] is False
    assert "missing required soak category: workerCrashRestart" in summary["failures"]
    assert "missing required soak category: leaseExpiryRecovery" in summary["failures"]


def test_soak_streams_child_evidence_and_writes_json(tmp_path, monkeypatch, capsys) -> None:
    soak = _load_module()
    evidence_path = tmp_path / "soak-evidence.json"

    class FakeStdout:
        def __iter__(self):
            return iter(
                [
                    'OBSERVABILITY_EVIDENCE: {"sloOk": true, "goldenSignals": '
                    '{"errors": {"sqliteBusyErrors": 0}, "saturation": '
                    '{"queueBackpressure": {"resourceWaitJobs": 1}}}}\n',
                    "RESULT: ok\n",
                ]
            )

    class FakeProcess:
        stdout = FakeStdout()

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(soak, "build_steps", lambda **kwargs: [soak.SoakStep("fake", 1, ["python", "fake.py"])])
    monkeypatch.setattr(
        soak,
        "build_soak_summary",
        lambda **kwargs: {"schemaVersion": "remote-runner-soak-acceptance.v1", "ok": True, "steps": []},
    )
    monkeypatch.setattr(
        soak,
        "build_soak_observability",
        lambda summary: {"schemaVersion": "remote-runner-soak-observability.v1", "ok": True},
    )

    exit_code = soak.main(
        [
            "--allow-soak",
            "--allow-runner-kill",
            "--evidence-json",
            str(evidence_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "remote-runner-soak-acceptance.v1"
    captured = capsys.readouterr()
    assert "SOAK_OBSERVABILITY_EVIDENCE" in captured.out
    assert "SOAK_ACCEPTANCE_SUMMARY" in captured.out
