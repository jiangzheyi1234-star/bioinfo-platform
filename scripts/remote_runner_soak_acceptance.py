#!/usr/bin/env python3
"""Run repeatable remote-runner soak, stress, and fault-injection acceptance."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

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
}

REQUIRED_CATEGORIES = {
    "realTwoSlotConcurrency",
    "batchRuns",
    "cancelIsolation",
    "resourceSaturation",
    "workerCrashRestart",
    "leaseExpiryRecovery",
    "retryBackoff",
    "attemptTimeout",
    "queueTtl",
    "observability",
    "sqliteBackpressureObserved",
    "postRunInvariants",
}


@dataclass(frozen=True)
class SoakStep:
    name: str
    iteration: int
    command: list[str]


def build_steps(
    *,
    iterations: int,
    allow_soak: bool,
    allow_runner_kill: bool,
) -> list[SoakStep]:
    if not allow_soak:
        raise ValueError("--allow-soak is required for real remote soak acceptance")
    if not allow_runner_kill:
        raise ValueError("--allow-runner-kill is required for fault-injection acceptance")
    if iterations < 1:
        raise ValueError("--iterations must be at least 1")

    steps: list[SoakStep] = []
    for iteration in range(1, iterations + 1):
        steps.extend(
            [
                SoakStep(
                    name=f"two-slot-stress-{iteration}",
                    iteration=iteration,
                    command=[
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "remote_two_slot_acceptance.py"),
                        "--allow-two-slot",
                    ],
                ),
                SoakStep(
                    name=f"worker-crash-restart-{iteration}",
                    iteration=iteration,
                    command=[
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "remote_worker_crash_recovery_acceptance.py"),
                        "--allow-runner-kill",
                        "--restart-timeout",
                        "90",
                    ],
                ),
                SoakStep(
                    name=f"execution-policy-faults-{iteration}",
                    iteration=iteration,
                    command=[
                        sys.executable,
                        str(REPO_ROOT / "scripts" / "remote_execution_policy_acceptance.py"),
                        "--allow-policy-restart",
                    ],
                ),
            ]
        )
    return steps


def run_step(step: SoakStep) -> dict[str, Any]:
    started = time.monotonic()
    started_at = _utc_now()
    print(
        "SOAK_STEP_START: "
        + json.dumps({"name": step.name, "iteration": step.iteration}, sort_keys=True),
        flush=True,
    )
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
    evidence: list[dict[str, Any]] = []
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
    payload = {
        "name": step.name,
        "iteration": step.iteration,
        "exitCode": exit_code,
        "startedAt": started_at,
        "finishedAt": _utc_now(),
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "evidenceLabels": labels,
        "evidence": evidence,
    }
    print("SOAK_STEP_DONE: " + json.dumps(payload, sort_keys=True), flush=True)
    return payload


def build_soak_summary(*, steps: list[dict[str, Any]], iterations: int) -> dict[str, Any]:
    categories = _build_categories(steps)
    failures = _evaluation_failures(steps=steps, categories=categories, iterations=iterations)
    summary = {
        "schemaVersion": "remote-runner-soak-acceptance.v1",
        "ok": not failures,
        "generatedAt": _utc_now(),
        "iterations": iterations,
        "sourceCommit": _source_commit(),
        "requiredCategories": sorted(REQUIRED_CATEGORIES),
        "categories": categories,
        "slo": _observability_slo(steps),
        "failures": failures,
        "steps": steps,
    }
    return _redact_sensitive(summary)


def build_soak_observability(summary: dict[str, Any]) -> dict[str, Any]:
    slo = _dict(summary.get("slo"))
    categories = _dict(summary.get("categories"))
    return {
        "schemaVersion": "remote-runner-soak-observability.v1",
        "ok": bool(summary.get("ok")),
        "observabilityCount": int(slo.get("observabilityCount") or 0),
        "sloOk": bool(slo.get("sloOk")),
        "sloStatuses": _list(slo.get("sloStatuses")),
        "alertCodes": _list(slo.get("alertCodes")),
        "sqliteBusyErrorsObserved": int(slo.get("sqliteBusyErrorsObserved") or 0),
        "resourceWaitObservations": int(categories.get("resourceWaitObservations") or 0),
    }


def evaluate_soak_summary(summary: dict[str, Any]) -> list[str]:
    steps = _list(summary.get("steps"))
    categories = _dict(summary.get("categories"))
    iterations = int(summary.get("iterations") or 0)
    return _evaluation_failures(steps=steps, categories=categories, iterations=iterations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-soak",
        action="store_true",
        help="Required acknowledgement that the command runs repeated real remote acceptance.",
    )
    parser.add_argument(
        "--allow-runner-kill",
        action="store_true",
        help="Required acknowledgement that fault injection kills a remote runner worker.",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of full two-slot/crash/policy acceptance cycles to run.",
    )
    parser.add_argument(
        "--evidence-json",
        type=Path,
        help="Optional path for machine-readable soak evidence.",
    )
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        steps = build_steps(
            iterations=args.iterations,
            allow_soak=args.allow_soak,
            allow_runner_kill=args.allow_runner_kill,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 2

    results: list[dict[str, Any]] = []
    for step in steps:
        result = run_step(step)
        results.append(result)
        if int(result["exitCode"]) != 0:
            summary = build_soak_summary(steps=results, iterations=args.iterations)
            _write_evidence_json(args.evidence_json, summary)
            _emit_summary(summary)
            return int(result["exitCode"]) or 1

    summary = build_soak_summary(steps=results, iterations=args.iterations)
    _write_evidence_json(args.evidence_json, summary)
    _emit_summary(summary)
    if summary["ok"]:
        print("RESULT: ok", flush=True)
        return 0
    return 1


def _emit_summary(summary: dict[str, Any]) -> None:
    observability = build_soak_observability(summary)
    print("SOAK_OBSERVABILITY_EVIDENCE: " + json.dumps(observability, sort_keys=True), flush=True)
    print("SOAK_ACCEPTANCE_SUMMARY: " + json.dumps(summary, sort_keys=True), flush=True)


def _build_categories(steps: list[dict[str, Any]]) -> dict[str, Any]:
    labels = _all_labels(steps)
    two_slot_summaries = _payloads(steps, "ACCEPTANCE_SUMMARY")
    policy_summaries = _payloads(steps, "POLICY_ACCEPTANCE_SUMMARY")
    resource_wait = _payloads(steps, "RESOURCE_WAIT_EVIDENCE")
    recoveries = _payloads(steps, "RECOVERY_EVIDENCE")
    backoff = _payloads(steps, "POLICY_BACKOFF_EVIDENCE")
    attempt_timeout = _payloads(steps, "POLICY_ATTEMPT_TIMEOUT_EVIDENCE")
    queue_ttl = _payloads(steps, "POLICY_QUEUE_TTL_EVIDENCE")
    observability = _payloads(steps, "OBSERVABILITY_EVIDENCE")
    post_invariants = _payloads(steps, "POST_ACCEPTANCE_INVARIANTS") + _payloads(
        steps,
        "POST_POLICY_INVARIANTS",
    )

    run_ids = _collect_run_ids(two_slot_summaries, policy_summaries, resource_wait, recoveries, queue_ttl)
    resource_wait_observations = sum(len(_list(item.get("waiting"))) for item in resource_wait)
    categories: dict[str, Any] = {
        "realTwoSlotConcurrency": "CONCURRENCY_EVIDENCE" in labels,
        "batchRuns": len(run_ids) >= 4,
        "cancelIsolation": any(item.get("cancelledRunId") for item in two_slot_summaries),
        "resourceSaturation": resource_wait_observations > 0 or _observability_has_resource_wait(observability),
        "workerCrashRestart": any(_recovery_shows_restart(item) for item in recoveries),
        "leaseExpiryRecovery": any(_recovery_shows_lease_expiry(item) for item in recoveries),
        "retryBackoff": bool(backoff),
        "attemptTimeout": any(_reason_code(item) == "ATTEMPT_TIMEOUT" for item in attempt_timeout),
        "queueTtl": any(_reason_code(item) == "QUEUE_TTL_EXCEEDED" for item in queue_ttl),
        "observability": bool(observability),
        "sqliteBackpressureObserved": any(_has_sqlite_and_backpressure(item) for item in observability),
        "postRunInvariants": bool(post_invariants) and all(item.get("ok") is not False for item in post_invariants),
        "runCount": len(run_ids),
        "resourceWaitObservations": resource_wait_observations,
    }
    return categories


def _evaluation_failures(
    *,
    steps: list[dict[str, Any]],
    categories: dict[str, Any],
    iterations: int,
) -> list[str]:
    failures: list[str] = []
    if iterations < 1:
        failures.append("iterations must be at least 1")
    for step in steps:
        if int(_dict(step).get("exitCode") or 0) != 0:
            failures.append(f"{step.get('name')} exited {step.get('exitCode')}")
    for category in sorted(REQUIRED_CATEGORIES):
        if not categories.get(category):
            failures.append(f"missing required soak category: {category}")
    slo = _observability_slo(steps)
    if not slo["sloOk"]:
        failures.append("execution observability reported a failed SLO")
    return failures


def _observability_slo(steps: list[dict[str, Any]]) -> dict[str, Any]:
    payloads = _payloads(steps, "OBSERVABILITY_EVIDENCE")
    statuses = sorted({str(item.get("sloStatus")) for item in payloads if item.get("sloStatus")})
    alert_codes = sorted({
        str(code)
        for item in payloads
        for code in _list(item.get("alertCodes"))
        if code
    })
    sqlite_busy = 0
    for item in payloads:
        errors = _dict(_dict(item.get("goldenSignals")).get("errors"))
        sqlite_busy += int(errors.get("sqliteBusyErrors") or 0)
    return {
        "observabilityCount": len(payloads),
        "sloOk": bool(payloads) and all(item.get("sloOk") is not False for item in payloads),
        "sloStatuses": statuses,
        "alertCodes": alert_codes,
        "sqliteBusyErrorsObserved": sqlite_busy,
    }


def _parse_evidence_line(line: str) -> dict[str, Any] | None:
    label = line.split(":", 1)[0].strip()
    if label not in EVIDENCE_LABELS:
        return None
    payload_text = line.split(":", 1)[1].strip() if ":" in line else ""
    if label == "RESULT" and payload_text == "ok":
        payload: Any = {"ok": True}
    elif payload_text:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {"raw": payload_text}
    else:
        payload = {}
    return {"label": label, "payload": _redact_sensitive(payload)}


def _collect_run_ids(*groups: list[dict[str, Any]]) -> set[str]:
    run_ids: set[str] = set()
    for payloads in groups:
        for payload in payloads:
            for key, value in payload.items():
                if key.endswith("RunId") and isinstance(value, str):
                    run_ids.add(value)
                elif key.endswith("RunIds"):
                    run_ids.update(str(item) for item in _list(value))
    return run_ids


def _all_labels(steps: list[dict[str, Any]]) -> set[str]:
    return {
        str(label)
        for step in steps
        for label in _list(_dict(step).get("evidenceLabels"))
    }


def _payloads(steps: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in steps:
        for entry in _list(_dict(step).get("evidence")):
            if _dict(entry).get("label") == label:
                payloads.append(_dict(_dict(entry).get("payload")))
    return payloads


def _observability_has_resource_wait(payloads: list[dict[str, Any]]) -> bool:
    for item in payloads:
        golden = _dict(item.get("goldenSignals"))
        saturation = _dict(golden.get("saturation"))
        backpressure = _dict(saturation.get("queueBackpressure"))
        if int(backpressure.get("resourceWaitJobs") or 0) > 0:
            return True
        if "SLOT_SATURATION" in _list(item.get("alertCodes")):
            return True
    return False


def _has_sqlite_and_backpressure(payload: dict[str, Any]) -> bool:
    golden = _dict(payload.get("goldenSignals"))
    errors = _dict(golden.get("errors"))
    saturation = _dict(golden.get("saturation"))
    backpressure = _dict(saturation.get("queueBackpressure"))
    return "sqliteBusyErrors" in errors and "resourceWaitJobs" in backpressure


def _recovery_shows_restart(payload: dict[str, Any]) -> bool:
    return bool(payload.get("oldWorkerPid") and payload.get("newWorkerPid")) and (
        payload.get("oldWorkerPid") != payload.get("newWorkerPid")
    )


def _recovery_shows_lease_expiry(payload: dict[str, Any]) -> bool:
    return int(payload.get("fenceEventCount") or 0) > 0 and len(_list(payload.get("leaseGenerations"))) >= 2


def _reason_code(payload: dict[str, Any]) -> str:
    recovery = _dict(payload.get("recovery"))
    return str(recovery.get("reasonCode") or "")


def _write_evidence_json(path: Path | None, summary: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _sensitive_key(str(key)) else _redact_sensitive(item)
            for key, item in value.items()
        }
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    raise SystemExit(main())
