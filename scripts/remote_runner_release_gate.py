#!/usr/bin/env python3
"""Run the destructive remote-runner release acceptance gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.remote_runner.artifact_io import read_expected_sha256, sha256_file  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


EVIDENCE_LABELS = {
    "ACCEPTANCE_SUMMARY",
    "CONCURRENCY_EVIDENCE",
    "OBSERVABILITY_EVIDENCE",
    "POLICY_ACCEPTANCE_SUMMARY",
    "POLICY_ATTEMPT_TIMEOUT_EVIDENCE",
    "POLICY_BACKOFF_EVIDENCE",
    "POLICY_PREFLIGHT",
    "POLICY_QUEUE_TTL_EVIDENCE",
    "POST_ACCEPTANCE_INVARIANTS",
    "POST_POLICY_INVARIANTS",
    "RECOVERY_EVIDENCE",
    "RESOURCE_WAIT_EVIDENCE",
    "RESULT",
    "RUNNER_READY",
    "SERVER_READY_PREFLIGHT",
    "SOAK_ACCEPTANCE_SUMMARY",
    "SOAK_OBSERVABILITY_EVIDENCE",
}

REQUIRED_BUNDLE_MARKERS = {
    "remote_runner/worker_resource_config.py": "",
    "remote_runner/executor_outcomes.py": "RUN_CANCELLED",
    "remote_runner/execution_observability.py": "execution-observability.v1",
    "remote_runner/execution_policy.py": "attempt_start_to_close_exceeded",
    "remote_runner/worker_supervisor.py": "H2OMETA_REMOTE_ENABLE_MULTI_SLOT",
    "remote_runner/reconciler_actions.py": "expire_queued_jobs_over_ttl",
}


@dataclass(frozen=True)
class GateStep:
    name: str
    command: list[str]


def build_steps(
    *,
    allow_two_slot: bool,
    allow_runner_kill: bool,
    include_soak: bool = False,
    allow_soak: bool = False,
    soak_iterations: int = 1,
) -> list[GateStep]:
    steps = [
        GateStep(
            name="real-snakemake-two-slot",
            command=[
                sys.executable,
                str(REPO_ROOT / "scripts" / "remote_two_slot_acceptance.py"),
                "--allow-two-slot",
            ],
        ),
        GateStep(
            name="worker-crash-restart-recovery",
            command=[
                sys.executable,
                str(REPO_ROOT / "scripts" / "remote_worker_crash_recovery_acceptance.py"),
                "--allow-runner-kill",
                "--restart-timeout",
                "90",
            ],
        ),
        GateStep(
            name="execution-policy-acceptance",
            command=[
                sys.executable,
                str(REPO_ROOT / "scripts" / "remote_execution_policy_acceptance.py"),
                "--allow-policy-restart",
            ],
        ),
    ]
    if not allow_two_slot:
        raise ValueError("--allow-two-slot is required for the real 2-slot acceptance gate")
    if not allow_runner_kill:
        raise ValueError("--allow-runner-kill is required for the crash-recovery acceptance gate")
    if include_soak:
        if not allow_soak:
            raise ValueError("--include-soak requires --allow-soak")
        if soak_iterations < 1:
            raise ValueError("--soak-iterations must be at least 1")
        steps.append(
            GateStep(
                name="soak-stress-fault-injection",
                command=[
                    sys.executable,
                    str(REPO_ROOT / "scripts" / "remote_runner_soak_acceptance.py"),
                    "--allow-soak",
                    "--allow-runner-kill",
                    "--iterations",
                    str(soak_iterations),
                ],
            )
        )
    return steps


def _collect_label(line: str) -> str | None:
    label = line.split(":", 1)[0].strip()
    if label in EVIDENCE_LABELS:
        return label
    if line.strip() == "RESULT: ok":
        return "RESULT"
    return None


def _parse_evidence_line(line: str) -> dict[str, object] | None:
    label = _collect_label(line)
    if label is None:
        return None
    payload_text = line.split(":", 1)[1].strip() if ":" in line else ""
    if label == "RESULT" and payload_text == "ok":
        payload: object = {"ok": True}
    elif payload_text:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {"raw": payload_text}
    else:
        payload = {}
    return {"label": label, "payload": _redact_sensitive(payload)}


def run_step(step: GateStep) -> dict[str, object]:
    started = time.monotonic()
    started_at = _utc_now()
    print(f"RELEASE_GATE_STEP_START: {json.dumps({'name': step.name}, sort_keys=True)}", flush=True)
    process = subprocess.Popen(
        step.command,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    labels: list[str] = []
    evidence: list[dict[str, object]] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        entry = _parse_evidence_line(line)
        if entry is None:
            continue
        label = str(entry["label"])
        evidence.append(entry)
        if label not in labels:
            labels.append(label)
    exit_code = process.wait()
    elapsed_seconds = round(time.monotonic() - started, 3)
    payload = {
        "name": step.name,
        "exitCode": exit_code,
        "startedAt": started_at,
        "finishedAt": _utc_now(),
        "elapsedSeconds": elapsed_seconds,
        "evidenceLabels": labels,
        "evidence": evidence,
    }
    print(f"RELEASE_GATE_STEP_DONE: {json.dumps(payload, sort_keys=True)}", flush=True)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-two-slot",
        action="store_true",
        help="Required acknowledgement that the remote runner will temporarily run with 2 worker slots.",
    )
    parser.add_argument(
        "--allow-runner-kill",
        action="store_true",
        help="Required acknowledgement that the gate sends SIGSTOP and SIGKILL to the remote runner service.",
    )
    parser.add_argument(
        "--evidence-json",
        type=Path,
        help="Optional path for a machine-readable release gate evidence JSON file.",
    )
    parser.add_argument(
        "--include-soak",
        action="store_true",
        help="Also run the repeatable soak/stress/fault-injection acceptance harness.",
    )
    parser.add_argument(
        "--allow-soak",
        action="store_true",
        help="Required with --include-soak; acknowledges repeated real remote acceptance.",
    )
    parser.add_argument(
        "--soak-iterations",
        type=int,
        default=1,
        help="Full two-slot/crash/policy acceptance cycles to run when --include-soak is set.",
    )
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        steps = build_steps(
            allow_two_slot=args.allow_two_slot,
            allow_runner_kill=args.allow_runner_kill,
            include_soak=args.include_soak,
            allow_soak=args.allow_soak,
            soak_iterations=args.soak_iterations,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    try:
        _validate_release_bundle_env()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    results = []
    for step in steps:
        result = run_step(step)
        results.append(result)
        if int(result["exitCode"]) != 0:
            summary = _build_gate_summary(ok=False, steps=results, failed_step=step.name)
            _write_evidence_json(args.evidence_json, summary)
            print("RELEASE_GATE_SUMMARY: " + json.dumps(summary, sort_keys=True), flush=True)
            return int(result["exitCode"]) or 1

    summary = _build_gate_summary(ok=True, steps=results)
    _write_evidence_json(args.evidence_json, summary)
    print("RELEASE_GATE_SUMMARY: " + json.dumps(summary, sort_keys=True), flush=True)
    print("RESULT: ok", flush=True)
    return 0


def _build_gate_summary(
    *,
    ok: bool,
    steps: list[dict[str, object]],
    failed_step: str | None = None,
) -> dict[str, object]:
    summary: dict[str, object] = {
        "schemaVersion": "remote-runner-release-gate.v1",
        "ok": ok,
        "generatedAt": _utc_now(),
        "sourceCommit": _source_commit(),
        "steps": steps,
    }
    if failed_step:
        summary["failedStep"] = failed_step
    return _redact_sensitive(summary)


def _write_evidence_json(path: Path | None, summary: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_release_bundle_env() -> Path:
    raw = str(os.environ.get("H2OMETA_REMOTE_RUNNER_BUNDLE", "") or "").strip()
    if not raw:
        raise ValueError(
            "H2OMETA_REMOTE_RUNNER_BUNDLE must point to the staged remote-runner artifact "
            "so Local API health refresh cannot redeploy the manifest default artifact"
        )
    artifact = Path(raw).resolve()
    checksum = Path(str(artifact) + ".sha256")
    if not artifact.is_file():
        raise ValueError(f"H2OMETA_REMOTE_RUNNER_BUNDLE artifact not found: {artifact}")
    if not checksum.is_file():
        raise ValueError(f"H2OMETA_REMOTE_RUNNER_BUNDLE checksum not found: {checksum}")
    expected = read_expected_sha256(checksum)
    actual = sha256_file(artifact)
    if actual != expected:
        raise ValueError(f"H2OMETA_REMOTE_RUNNER_BUNDLE sha256 mismatch: {artifact}")
    with tarfile.open(artifact, "r:gz") as archive:
        members = {member.name.strip("./"): member for member in archive.getmembers()}
        missing = [name for name in REQUIRED_BUNDLE_MARKERS if name not in members]
        if missing:
            raise ValueError("H2OMETA_REMOTE_RUNNER_BUNDLE missing required members: " + ", ".join(missing))
        for name, marker in REQUIRED_BUNDLE_MARKERS.items():
            if not marker:
                continue
            handle = archive.extractfile(members[name])
            if handle is None:
                raise ValueError(f"H2OMETA_REMOTE_RUNNER_BUNDLE member unreadable: {name}")
            text = handle.read().decode("utf-8", errors="replace")
            if marker not in text:
                raise ValueError(f"H2OMETA_REMOTE_RUNNER_BUNDLE member {name} missing marker: {marker}")
    print(
        "RELEASE_GATE_BUNDLE: "
        + json.dumps({"path": str(artifact), "sha256": actual, "markers": sorted(REQUIRED_BUNDLE_MARKERS)}, sort_keys=True),
        flush=True,
    )
    return artifact


def _source_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact_sensitive(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            if _sensitive_key(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if isinstance(value, str) and _sensitive_text(value):
        return "[REDACTED]"
    return value


def _sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "").replace("-", "")
    return any(
        marker in normalized
        for marker in (
            "authorization",
            "password",
            "privatekey",
            "secret",
            "token",
            "identityref",
            "keyfile",
        )
    )


def _sensitive_text(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("bearer ") or "authorization:" in lowered or "-----begin " in lowered


if __name__ == "__main__":
    raise SystemExit(main())
