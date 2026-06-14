#!/usr/bin/env python3
"""Destructive platform acceptance for remote worker crash recovery."""

from __future__ import annotations

import argparse
import base64
import json
import shlex
import sys
import time
import uuid
from typing import Any

import remote_pipeline_common
import remote_smoke
from remote_worker_crash_recovery_evidence import (
    EXPECTED_ARTIFACT_COUNT,
    validate_recovery_evidence,
)


DEFAULT_API_BASE = remote_smoke.DEFAULT_API_BASE
DEFAULT_PIPELINE_ID = remote_smoke.MINIMAL_PIPELINE_ID


REMOTE_PREFLIGHT_SCRIPT = r'''
import json
import pathlib
import sqlite3

root = pathlib.Path.home() / ".h2ometa" / "runner"
cfg = json.loads((root / "shared" / "config" / "runner.json").read_text())
db = sqlite3.connect(f"file:{cfg['db_path']}?mode=ro", uri=True, timeout=2)
db.row_factory = sqlite3.Row
current = pathlib.Path(root / "current").resolve()
executor_artifacts = (current / "remote_runner" / "executor_artifacts.py").read_text()
reconciler = (current / "remote_runner" / "reconciler.py").read_text()
actions_path = current / "remote_runner" / "reconciler_actions.py"
actions = actions_path.read_text() if actions_path.exists() else ""
claimed = db.execute("SELECT COUNT(*) AS count FROM run_jobs WHERE state = 'claimed'").fetchone()["count"]
queued = db.execute("SELECT COUNT(*) AS count FROM run_jobs WHERE state = 'queued'").fetchone()["count"]
tool_jobs = db.execute(
    "SELECT COUNT(*) AS count FROM tool_prepare_jobs WHERE status IN ('queued', 'running')"
).fetchone()["count"]
workers = [dict(row) for row in db.execute(
    "SELECT worker_id, session_id, pid, state, current_attempt_id FROM run_workers ORDER BY worker_id"
).fetchall()]
print(json.dumps({
    "release": str(current),
    "candidateAdoption": "adopt_verified_candidate_outputs" in executor_artifacts,
    "activeReconciler": "run_active_reconciler_once" in reconciler,
    "sigkillEscalation": "signal.SIGKILL" in actions,
    "queuedRunJobs": int(queued),
    "claimedRunJobs": int(claimed),
    "activeToolPrepareJobs": int(tool_jobs),
    "workers": workers,
}, sort_keys=True))
'''


REMOTE_HOLD_ATTEMPT_SCRIPT = r'''
import json
import os
import pathlib
import signal
import sqlite3
import subprocess
import time

run_id = os.environ["H2OMETA_ACCEPTANCE_RUN_ID"]
timeout = float(os.environ["H2OMETA_ACCEPTANCE_TIMEOUT"])
root = pathlib.Path.home() / ".h2ometa" / "runner"
cfg = json.loads((root / "shared" / "config" / "runner.json").read_text())
deadline = time.monotonic() + timeout

def process_state(pid):
    status = pathlib.Path(f"/proc/{pid}/status").read_text()
    for line in status.splitlines():
        if line.startswith("State:"):
            return line.split(":", 1)[1].strip()
    return ""

while time.monotonic() < deadline:
    db = sqlite3.connect(f"file:{cfg['db_path']}?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute(
            """
            SELECT attempts.attempt_id, attempts.lease_generation, attempts.worker_id,
                   attempts.process_group_id,
                   leases.expires_at, workers.session_id, workers.pid
            FROM run_attempts AS attempts
            JOIN run_leases AS leases
              ON leases.run_id = attempts.run_id
             AND leases.attempt_id = attempts.attempt_id
            JOIN run_workers AS workers ON workers.worker_id = attempts.worker_id
            WHERE attempts.run_id = ?
              AND attempts.state = 'running'
              AND leases.state = 'active'
              AND attempts.process_group_id IS NOT NULL
            """,
            (run_id,),
        ).fetchone()
    finally:
        db.close()
    if row is None:
        time.sleep(0.02)
        continue
    state = json.loads(pathlib.Path(cfg["runtime_state_path"]).read_text())
    worker_pid = int(row["pid"])
    runtime_pid = int(state["pid"])
    main_pid = int(subprocess.check_output(
        ["systemctl", "--user", "show", "h2ometa-remote.service", "--property=MainPID", "--value"],
        text=True,
    ).strip())
    if worker_pid <= 0 or worker_pid != runtime_pid or worker_pid != main_pid:
        raise RuntimeError(
            f"worker/runtime/systemd pid mismatch: worker={worker_pid} runtime={runtime_pid} main={main_pid}"
        )
    os.kill(worker_pid, signal.SIGSTOP)
    stop_deadline = time.monotonic() + 5
    observed_state = ""
    while time.monotonic() < stop_deadline:
        observed_state = process_state(worker_pid)
        if observed_state.startswith("T"):
            break
        time.sleep(0.02)
    if not observed_state.startswith("T"):
        raise RuntimeError(f"worker process did not stop: pid={worker_pid} state={observed_state}")
    print(json.dumps({
        "runId": run_id,
        "attemptId": row["attempt_id"],
        "leaseGeneration": int(row["lease_generation"]),
        "leaseExpiresAt": row["expires_at"],
        "workerId": row["worker_id"],
        "workerSessionId": row["session_id"],
        "workerPid": worker_pid,
        "processGroupId": int(row["process_group_id"]),
        "processState": observed_state,
        "bindPort": int(state["bindPort"]),
    }, sort_keys=True), flush=True)
    raise SystemExit(0)
raise TimeoutError(f"target run was not claimed before timeout: {run_id}")
'''


REMOTE_KILL_SCRIPT = r'''
import json
import os
import pathlib
import signal
import sqlite3
import subprocess

run_id = os.environ["H2OMETA_ACCEPTANCE_RUN_ID"]
attempt_id = os.environ["H2OMETA_ACCEPTANCE_ATTEMPT_ID"]
pid = int(os.environ["H2OMETA_ACCEPTANCE_WORKER_PID"])
root = pathlib.Path.home() / ".h2ometa" / "runner"
cfg = json.loads((root / "shared" / "config" / "runner.json").read_text())
main_pid = int(subprocess.check_output(
    ["systemctl", "--user", "show", "h2ometa-remote.service", "--property=MainPID", "--value"],
    text=True,
).strip())
status = pathlib.Path(f"/proc/{pid}/status").read_text()
process_state = next(
    (line.split(":", 1)[1].strip() for line in status.splitlines() if line.startswith("State:")),
    "",
)
db = sqlite3.connect(f"file:{cfg['db_path']}?mode=ro", uri=True, timeout=2)
db.row_factory = sqlite3.Row
try:
    lease = db.execute(
        "SELECT attempt_id, state FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone()
finally:
    db.close()
if main_pid != pid:
    raise RuntimeError(f"systemd MainPID changed before kill: expected={pid} actual={main_pid}")
if not process_state.startswith("T"):
    raise RuntimeError(f"worker is not held before kill: pid={pid} state={process_state}")
if lease is None or lease["attempt_id"] != attempt_id or lease["state"] != "active":
    raise RuntimeError(f"target lease changed before kill: run={run_id} attempt={attempt_id}")
os.kill(pid, signal.SIGKILL)
print(json.dumps({
    "runId": run_id,
    "attemptId": attempt_id,
    "killedPid": pid,
    "signal": "SIGKILL",
}, sort_keys=True))
'''


REMOTE_RESUME_SCRIPT = r'''
import json
import os
import pathlib
import signal
import subprocess

pid = int(os.environ["H2OMETA_ACCEPTANCE_WORKER_PID"])
main_raw = subprocess.check_output(
    ["systemctl", "--user", "show", "h2ometa-remote.service", "--property=MainPID", "--value"],
    text=True,
).strip()
main_pid = int(main_raw or 0)
resumed = False
if main_pid == pid and pathlib.Path(f"/proc/{pid}").exists():
    os.kill(pid, signal.SIGCONT)
    resumed = True
print(json.dumps({"workerPid": pid, "mainPid": main_pid, "resumed": resumed}, sort_keys=True))
'''


REMOTE_WAIT_RESTART_SCRIPT = r'''
import json
import os
import pathlib
import sqlite3
import subprocess
import time

old_pid = int(os.environ["H2OMETA_ACCEPTANCE_OLD_PID"])
old_session = os.environ["H2OMETA_ACCEPTANCE_OLD_SESSION"]
worker_id = os.environ["H2OMETA_ACCEPTANCE_WORKER_ID"]
timeout = float(os.environ["H2OMETA_ACCEPTANCE_TIMEOUT"])
root = pathlib.Path.home() / ".h2ometa" / "runner"
cfg = json.loads((root / "shared" / "config" / "runner.json").read_text())
deadline = time.monotonic() + timeout
while time.monotonic() < deadline:
    main_raw = subprocess.check_output(
        ["systemctl", "--user", "show", "h2ometa-remote.service", "--property=MainPID", "--value"],
        text=True,
    ).strip()
    main_pid = int(main_raw or 0)
    if main_pid <= 0 or main_pid == old_pid or not pathlib.Path(f"/proc/{main_pid}").exists():
        time.sleep(0.2)
        continue
    db = sqlite3.connect(f"file:{cfg['db_path']}?mode=ro", uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        worker = db.execute(
            "SELECT worker_id, session_id, pid, state, current_attempt_id FROM run_workers WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
    finally:
        db.close()
    if worker is None or int(worker["pid"]) != main_pid or worker["session_id"] == old_session:
        time.sleep(0.2)
        continue
    state = json.loads(pathlib.Path(cfg["runtime_state_path"]).read_text())
    if int(state["pid"]) != main_pid:
        time.sleep(0.2)
        continue
    print(json.dumps({
        "workerId": worker["worker_id"],
        "workerSessionId": worker["session_id"],
        "workerPid": int(worker["pid"]),
        "workerState": worker["state"],
        "currentAttemptId": worker["current_attempt_id"],
        "bindPort": int(state["bindPort"]),
    }, sort_keys=True))
    raise SystemExit(0)
raise TimeoutError(f"remote worker did not restart before timeout; old pid={old_pid}")
'''


REMOTE_FINAL_SNAPSHOT_SCRIPT = r'''
import json
import os
import pathlib
import sqlite3
import signal

run_id = os.environ["H2OMETA_ACCEPTANCE_RUN_ID"]
old_process_group_id = int(os.environ["H2OMETA_ACCEPTANCE_OLD_PROCESS_GROUP_ID"])
root = pathlib.Path.home() / ".h2ometa" / "runner"
cfg = json.loads((root / "shared" / "config" / "runner.json").read_text())
db = sqlite3.connect(f"file:{cfg['db_path']}?mode=ro", uri=True, timeout=2)
db.row_factory = sqlite3.Row
try:
    attempts = [dict(row) for row in db.execute(
        """
        SELECT attempt_id, lease_generation, attempt_number, state, worker_id,
               output_adoption_state, fenced_reason, process_pid, process_group_id
        FROM run_attempts WHERE run_id = ? ORDER BY attempt_number
        """,
        (run_id,),
    ).fetchall()]
    job = dict(db.execute(
        "SELECT state, attempt_count, max_attempts FROM run_jobs WHERE run_id = ?",
        (run_id,),
    ).fetchone())
    lease = dict(db.execute(
        "SELECT attempt_id, lease_generation, worker_id, state FROM run_leases WHERE run_id = ?",
        (run_id,),
    ).fetchone())
    artifacts = [dict(row) for row in db.execute(
        "SELECT artifact_id, path, sha256 FROM artifacts WHERE run_id = ? ORDER BY artifact_id",
        (run_id,),
    ).fetchall()]
    candidates = [dict(row) for row in db.execute(
        """
        SELECT attempt_id, lease_generation, output_key, verification_state, adopted_artifact_id
        FROM candidate_outputs WHERE run_id = ? ORDER BY lease_generation, output_key
        """,
        (run_id,),
    ).fetchall()]
    output_edges = [dict(row) for row in db.execute(
        """
        SELECT port_name, content_hash FROM run_artifact_edges
        WHERE run_id = ? AND role = 'output' ORDER BY port_name
        """,
        (run_id,),
    ).fetchall()]
    lineage_count = int(db.execute(
        """
        SELECT COUNT(*) AS count FROM lineage_edges
        WHERE run_id = ? AND predicate = 'prov:generated'
        """,
        (run_id,),
    ).fetchone()["count"])
finally:
    db.close()
old_process_group_exists = True
try:
    os.killpg(old_process_group_id, 0)
except ProcessLookupError:
    old_process_group_exists = False
print(json.dumps({
    "runId": run_id,
    "attempts": attempts,
    "job": job,
    "lease": lease,
    "artifacts": artifacts,
    "candidates": candidates,
    "outputEdges": output_edges,
    "lineageCount": lineage_count,
    "oldProcessGroupExists": old_process_group_exists,
}, sort_keys=True))
'''


def build_run_submit_payload(
    *,
    run_id: str,
    request_id: str,
    server_id: str,
    pipeline_id: str,
    upload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "serverId": server_id,
        "requestId": request_id,
        "runSpec": {
            "runId": run_id,
            "projectId": "proj_worker_crash_acceptance",
            "pipelineId": pipeline_id,
            "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "reads"}],
            "params": {"threads": 1},
            "execution": {
                "retryPolicy": {"maxAttempts": 3, "backoffSeconds": 5},
                "timeoutPolicy": {
                    "queueTtlSeconds": 0,
                    "startToCloseTimeoutSeconds": 0,
                    "heartbeatTimeoutSeconds": 0,
                },
            },
        },
    }


def _connect_ssh():
    get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password, ssh_connect = (
        remote_smoke.load_project_modules()
    )
    cfg = get_config()
    ssh_cfg = normalize_ssh_config(cfg.get("ssh", {}))
    auth_mode = str(ssh_cfg.get("auth_mode") or "password_ref")
    resolved = resolve_ssh_config_target(ssh_cfg) if auth_mode == "ssh_config" else ssh_cfg
    password = resolve_ssh_password({"ssh": ssh_cfg}) if auth_mode == "password_ref" else ""
    key_file = str(resolved.get("identity_ref", "") or "") if auth_mode in {"key_file", "ssh_config"} else ""
    result = ssh_connect(
        ip=str(resolved.get("host") or ""),
        port=int(resolved.get("port") or 22),
        user=str(resolved.get("user") or ""),
        password=password,
        key_file=key_file,
        use_agent=auth_mode == "agent",
        timeout=int(resolved.get("timeout_sec") or 5),
    )
    if not result.ok or result.client is None:
        raise RuntimeError(f"SSH connection failed: {result.message}")
    return result.client


def _remote_command(source: str, env: dict[str, Any]) -> str:
    assignments = " ".join(f"{key}={shlex.quote(str(value))}" for key, value in env.items())
    return f"{assignments} python3 -c {shlex.quote(source)}".strip()


def _start_remote_json(client, source: str, env: dict[str, Any], *, timeout: int):
    return client.exec_command(_remote_command(source, env), timeout=timeout)


def _read_remote_json(stdout, stderr) -> dict[str, Any]:
    exit_code = stdout.channel.recv_exit_status()
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()
    if exit_code != 0:
        raise RuntimeError(error or output or f"remote command failed: {exit_code}")
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("remote command returned no JSON")
    payload = json.loads(lines[-1])
    if not isinstance(payload, dict):
        raise RuntimeError("remote command returned non-object JSON")
    return payload


def _run_remote_json(client, source: str, env: dict[str, Any], *, timeout: int) -> dict[str, Any]:
    _stdin, stdout, stderr = _start_remote_json(client, source, env, timeout=timeout)
    return _read_remote_json(stdout, stderr)


def _wait_for_server_ready(api_base: str, server_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error = ""
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        try:
            payload = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
                "POST",
                api_base,
                f"/api/v1/servers/{server_id}/health/refresh",
                payload={},
                timeout=10,
            ))
            last_payload = payload if isinstance(payload, dict) else {}
            ready = payload.get("ready") if isinstance(payload, dict) else None
            if isinstance(ready, dict) and ready.get("ok") is True:
                return payload
        except Exception as exc:  # noqa: BLE001 - service and tunnel are expected to flap during restart.
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(
        "server did not become ready after worker restart: "
        + json.dumps({"lastError": last_error, "lastPayload": last_payload}, sort_keys=True)
    )


def _wait_for_terminal_run(api_base: str, run_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    final: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            final = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
                "GET",
                api_base,
                f"/api/v1/runs/{run_id}",
                timeout=10,
            ))
            if final.get("status") in remote_pipeline_common.TERMINAL_RUN_STATUSES:
                return final
        except Exception as exc:  # noqa: BLE001 - transient tunnel failures are part of this acceptance.
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"run did not reach a terminal state: run={run_id} last_error={last_error} final={final}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Submit a real run, SIGSTOP and SIGKILL the systemd-hosted remote worker process, "
            "then prove lease fencing, requeue, generation increment, restart, and exactly-once output adoption."
        )
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--pipeline-id", default=DEFAULT_PIPELINE_ID)
    parser.add_argument("--hold-timeout", type=float, default=30)
    parser.add_argument("--restart-timeout", type=float, default=90)
    parser.add_argument("--run-timeout", type=float, default=180)
    parser.add_argument(
        "--allow-runner-kill",
        action="store_true",
        help="Required acknowledgement that this acceptance sends SIGSTOP and SIGKILL to the remote runner service.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not args.allow_runner_kill:
        print("ERROR: --allow-runner-kill is required for this destructive platform acceptance.")
        return 2
    ready, context = remote_smoke.check_local_api(args.api_base, 5.0, bootstrap=False)
    if not context:
        return 1
    server_id = str(context["serverId"])
    try:
        refreshed = _wait_for_server_ready(args.api_base, server_id, args.restart_timeout)
    except TimeoutError:
        if not ready:
            return 1
        raise
    remote_pipeline_common.print_json(
        "SERVER_READY_PREFLIGHT",
        {
            "serverId": server_id,
            "ready": refreshed.get("ready"),
            "runtimeState": refreshed.get("runtimeState"),
            "connectionResynced": refreshed.get("connectionResynced"),
        },
    )
    server = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
        "GET",
        args.api_base,
        f"/api/v1/servers/{server_id}",
        timeout=10,
    ))
    if server.get("runnerMode") != "systemd_user":
        raise RuntimeError(f"acceptance requires systemd_user runner mode, got {server.get('runnerMode')}")

    client = _connect_ssh()
    run_id = f"run_worker_crash_{uuid.uuid4().hex[:12]}"
    request_id = f"req_worker_crash_{uuid.uuid4().hex[:12]}"
    held: dict[str, Any] | None = None
    killed = False
    try:
        preflight = _run_remote_json(client, REMOTE_PREFLIGHT_SCRIPT, {}, timeout=20)
        remote_pipeline_common.print_json("REMOTE_PREFLIGHT", preflight)
        required_markers = ("candidateAdoption", "activeReconciler", "sigkillEscalation")
        missing_markers = [key for key in required_markers if preflight.get(key) is not True]
        if missing_markers:
            raise RuntimeError(f"deployed release is missing P0-1 markers: {', '.join(missing_markers)}")
        if any(int(preflight.get(key) or 0) for key in (
            "queuedRunJobs",
            "claimedRunJobs",
            "activeToolPrepareJobs",
        )):
            raise RuntimeError(f"remote runner is not idle: {preflight}")

        sample = b"@read1\nACGT\n+\n!!!!\n@read2\nTGCA\n+\n####\n"
        upload = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
            "POST",
            args.api_base,
            "/api/v1/uploads",
            payload={
                "filename": f"{run_id}.fastq",
                "contentBase64": base64.b64encode(sample).decode("ascii"),
                "mimeType": "text/plain",
            },
        ))
        _stdin, hold_stdout, hold_stderr = _start_remote_json(
            client,
            REMOTE_HOLD_ATTEMPT_SCRIPT,
            {
                "H2OMETA_ACCEPTANCE_RUN_ID": run_id,
                "H2OMETA_ACCEPTANCE_TIMEOUT": args.hold_timeout,
            },
            timeout=int(args.hold_timeout + 15),
        )
        submitted: dict[str, Any] | None = None
        submission_error = ""
        try:
            submitted = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
                "POST",
                args.api_base,
                "/api/v1/runs",
                payload=build_run_submit_payload(
                    run_id=run_id,
                    request_id=request_id,
                    server_id=server_id,
                    pipeline_id=args.pipeline_id,
                    upload=upload,
                ),
                timeout=15,
            ))
        except Exception as exc:  # noqa: BLE001 - SIGSTOP may interrupt the HTTP response after durable submission.
            submission_error = str(exc)
        held = _read_remote_json(hold_stdout, hold_stderr)
        remote_pipeline_common.print_json("WORKER_HELD", held)
        if submitted is not None:
            if submitted.get("runId") != run_id:
                raise RuntimeError(f"submitted run id mismatch: expected={run_id} actual={submitted.get('runId')}")
            remote_pipeline_common.print_json("RUN_SUBMITTED", submitted)
        else:
            remote_pipeline_common.print_json(
                "RUN_SUBMISSION_RESPONSE_INTERRUPTED",
                {"runId": run_id, "detail": submission_error},
            )
        killed = _run_remote_json(
            client,
            REMOTE_KILL_SCRIPT,
            {
                "H2OMETA_ACCEPTANCE_RUN_ID": run_id,
                "H2OMETA_ACCEPTANCE_ATTEMPT_ID": held["attemptId"],
                "H2OMETA_ACCEPTANCE_WORKER_PID": held["workerPid"],
            },
            timeout=20,
        )
        remote_pipeline_common.print_json("WORKER_KILLED", killed)
        killed = True
        restarted = _run_remote_json(
            client,
            REMOTE_WAIT_RESTART_SCRIPT,
            {
                "H2OMETA_ACCEPTANCE_OLD_PID": held["workerPid"],
                "H2OMETA_ACCEPTANCE_OLD_SESSION": held["workerSessionId"],
                "H2OMETA_ACCEPTANCE_WORKER_ID": held["workerId"],
                "H2OMETA_ACCEPTANCE_TIMEOUT": args.restart_timeout,
            },
            timeout=int(args.restart_timeout + 15),
        )
        remote_pipeline_common.print_json("WORKER_RESTARTED", restarted)

        health = _wait_for_server_ready(args.api_base, server_id, args.restart_timeout)
        remote_pipeline_common.print_json(
            "SERVER_READY",
            {
                "serverId": server_id,
                "ready": health.get("ready"),
                "runtimeState": health.get("runtimeState"),
                "connectionResynced": health.get("connectionResynced"),
            },
        )
        final_run = _wait_for_terminal_run(args.api_base, run_id, args.run_timeout)
        events = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
            "GET",
            args.api_base,
            f"/api/v1/runs/{run_id}/events",
            timeout=10,
        ))["items"]
        results = remote_pipeline_common.response_data(remote_pipeline_common.http_json(
            "GET",
            args.api_base,
            f"/api/v1/runs/{run_id}/results",
            timeout=10,
        ))
        snapshot = _run_remote_json(
            client,
            REMOTE_FINAL_SNAPSHOT_SCRIPT,
            {
                "H2OMETA_ACCEPTANCE_RUN_ID": run_id,
                "H2OMETA_ACCEPTANCE_OLD_PROCESS_GROUP_ID": held["processGroupId"],
            },
            timeout=20,
        )
        evidence = validate_recovery_evidence(
            final_run=final_run,
            events=events,
            results=results,
            held=held,
            restarted=restarted,
            snapshot=snapshot,
        )
        remote_pipeline_common.print_json("RECOVERY_EVIDENCE", evidence)
        print("RESULT: ok")
        return 0
    except Exception as exc:  # noqa: BLE001 - command-line acceptance must emit actionable diagnostics.
        remote_pipeline_common.print_failure(
            "remote worker crash-recovery acceptance failed",
            detail=str(exc),
            hints=remote_pipeline_common.pipeline_diagnostics(args.api_base, run_id),
        )
        return 1
    finally:
        if held is not None and not killed:
            try:
                resumed = _run_remote_json(
                    client,
                    REMOTE_RESUME_SCRIPT,
                    {"H2OMETA_ACCEPTANCE_WORKER_PID": held["workerPid"]},
                    timeout=10,
                )
                remote_pipeline_common.print_json("WORKER_RESUME_CLEANUP", resumed)
            except Exception as exc:  # noqa: BLE001 - report cleanup failure without hiding the primary result.
                remote_pipeline_common.print_json("WORKER_RESUME_CLEANUP_FAILED", {"detail": str(exc)})
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
