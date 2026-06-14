#!/usr/bin/env python3
"""Run the destructive remote-runner release acceptance gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


EVIDENCE_LABELS = {
    "ACCEPTANCE_SUMMARY",
    "CONCURRENCY_EVIDENCE",
    "POST_ACCEPTANCE_INVARIANTS",
    "RECOVERY_EVIDENCE",
    "RESOURCE_WAIT_EVIDENCE",
    "RESULT",
    "RUNNER_READY",
}


@dataclass(frozen=True)
class GateStep:
    name: str
    command: list[str]


def build_steps(*, allow_two_slot: bool, allow_runner_kill: bool) -> list[GateStep]:
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
            ],
        ),
    ]
    if not allow_two_slot:
        raise ValueError("--allow-two-slot is required for the real 2-slot acceptance gate")
    if not allow_runner_kill:
        raise ValueError("--allow-runner-kill is required for the crash-recovery acceptance gate")
    return steps


def _collect_label(line: str) -> str | None:
    label = line.split(":", 1)[0].strip()
    if label in EVIDENCE_LABELS:
        return label
    if line.strip() == "RESULT: ok":
        return "RESULT"
    return None


def run_step(step: GateStep) -> dict[str, object]:
    started = time.monotonic()
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
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        label = _collect_label(line)
        if label and label not in labels:
            labels.append(label)
    exit_code = process.wait()
    elapsed_seconds = round(time.monotonic() - started, 3)
    payload = {
        "name": step.name,
        "exitCode": exit_code,
        "elapsedSeconds": elapsed_seconds,
        "evidenceLabels": labels,
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
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        steps = build_steps(allow_two_slot=args.allow_two_slot, allow_runner_kill=args.allow_runner_kill)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2

    results = []
    for step in steps:
        result = run_step(step)
        results.append(result)
        if int(result["exitCode"]) != 0:
            print(
                "RELEASE_GATE_SUMMARY: "
                + json.dumps({"ok": False, "failedStep": step.name, "steps": results}, sort_keys=True),
                flush=True,
            )
            return int(result["exitCode"]) or 1

    print("RELEASE_GATE_SUMMARY: " + json.dumps({"ok": True, "steps": results}, sort_keys=True), flush=True)
    print("RESULT: ok", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
