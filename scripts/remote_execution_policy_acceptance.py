#!/usr/bin/env python3
"""Run real remote execution-policy acceptance against the configured SSH host."""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REMOTE_POLICY_ACCEPTANCE_SCRIPT = r'''
import base64
from datetime import datetime, timezone
import json
import os
import pathlib
import signal
import sqlite3
import subprocess
import time
import urllib.request
import uuid

ROOT = pathlib.Path.home() / ".h2ometa" / "runner"
CONFIG = ROOT / "shared" / "config" / "runner.json"
STATE = ROOT / "shared" / "runtime" / "runner-state.json"
cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
token = cfg["token"]
db_path = pathlib.Path(cfg["db_path"])


def emit(label, payload):
    print(f"{label}: {json.dumps(payload, sort_keys=True)}", flush=True)


def parse_utc(value):
    return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def request(method, path, payload=None, timeout=20):
    state = json.loads(STATE.read_text(encoding="utf-8"))
    base_url = f"http://127.0.0.1:{state['bindPort']}"
    data = None
    headers = {"Authorization": "Bearer " + token}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    parsed = json.loads(raw) if raw else {}
    return parsed.get("data", parsed)


def emit_observability(phase, run_ids):
    diagnostics = request("GET", "/health/execution-diagnostics", timeout=20)
    observability = diagnostics.get("executionObservability") or {}
    golden = observability.get("goldenSignals") or {}
    slo = observability.get("slo") or {}
    emit(
        "OBSERVABILITY_EVIDENCE",
        {
            "phase": phase,
            "runIds": list(run_ids),
            "schemaVersion": observability.get("schemaVersion"),
            "sloStatus": slo.get("status"),
            "sloOk": slo.get("ok"),
            "alertCodes": [
                str(alert.get("code"))
                for alert in observability.get("alerts") or []
                if isinstance(alert, dict)
            ],
            "goldenSignals": golden,
            "executionPolicy": observability.get("executionPolicy") or {},
        },
    )


def wait_ready(timeout=90):
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            payload = request("GET", "/health/ready", timeout=3)
            if payload.get("status") == "ok":
                return payload
        except Exception as exc:
            last_error = str(exc)
        time.sleep(1)
    raise TimeoutError(f"runner did not become ready: {last_error}")


def db_rows(query, params=()):
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query, params).fetchall()]


def db_one(query, params=()):
    rows = db_rows(query, params)
    return rows[0] if rows else None


def event_payload(row):
    details = json.loads(row.get("details_json") or "{}")
    payload = details.get("payload") if isinstance(details, dict) else None
    return payload if isinstance(payload, dict) else details


def run_events(run_id, event_type=None):
    if event_type:
        rows = db_rows(
            """
            SELECT event_type, created_at AS occurred_at, details_json
            FROM run_events
            WHERE run_id = ? AND event_type = ?
            ORDER BY occurred_at ASC, rowid ASC
            """,
            (run_id, event_type),
        )
    else:
        rows = db_rows(
            """
            SELECT event_type, created_at AS occurred_at, details_json
            FROM run_events
            WHERE run_id = ?
            ORDER BY occurred_at ASC, rowid ASC
            """,
            (run_id,),
        )
    return [{**row, "payload": event_payload(row)} for row in rows]


def wait_event(run_id, event_type, predicate=lambda _payload: True, timeout=90):
    deadline = time.monotonic() + timeout
    last = []
    while time.monotonic() < deadline:
        last = run_events(run_id, event_type)
        for event in last:
            if predicate(event["payload"]):
                return event
        time.sleep(0.5)
    raise TimeoutError(json.dumps({"runId": run_id, "eventType": event_type, "last": last}, sort_keys=True))


def wait_terminal(run_id, timeout=240):
    deadline = time.monotonic() + timeout
    final = {}
    terminal = {"completed", "failed", "canceled", "cancelled"}
    while time.monotonic() < deadline:
        final = request("GET", f"/api/v1/runs/{run_id}", timeout=10)
        if final.get("status") in terminal:
            return final
        time.sleep(1)
    raise TimeoutError(json.dumps({"runId": run_id, "final": final}, sort_keys=True))


def wait_attempt(run_id, *, attempt_number=None, require_process_group=False, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        rows = db_rows(
            """
            SELECT attempts.attempt_id, attempts.attempt_number, attempts.lease_generation,
                   attempts.worker_id, attempts.process_group_id, attempts.state,
                   leases.state AS lease_state, leases.expires_at,
                   workers.session_id, workers.pid
            FROM run_attempts AS attempts
            JOIN run_leases AS leases
              ON leases.run_id = attempts.run_id
             AND leases.attempt_id = attempts.attempt_id
            JOIN run_workers AS workers ON workers.worker_id = attempts.worker_id
            WHERE attempts.run_id = ?
            ORDER BY attempts.attempt_number DESC
            """,
            (run_id,),
        )
        last = rows
        for row in rows:
            if attempt_number is not None and int(row["attempt_number"]) != int(attempt_number):
                continue
            if row["state"] != "running" or row["lease_state"] != "active":
                continue
            if require_process_group and not row.get("process_group_id"):
                continue
            return row
        time.sleep(0.2)
    raise TimeoutError(json.dumps({"runId": run_id, "lastAttempts": last}, sort_keys=True))


def current_worker_state():
    workers = db_rows(
        """
        SELECT worker_id, session_id, concurrency_limit, pid, state
        FROM run_workers
        WHERE stopped_at IS NULL
        ORDER BY started_at DESC
        LIMIT 3
        """
    )
    slots = db_rows(
        """
        SELECT worker_id, session_id, slot_id, state, current_attempt_id
        FROM run_worker_slots
        WHERE stopped_at IS NULL
        ORDER BY slot_id ASC
        """
    )
    return {"workers": workers, "slots": slots}


def configure_worker(*, slots, total_cpu, enable_multi_slot=True):
    current_cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    current_cfg.update(
        {
            "run_worker_slot_count": int(slots),
            "run_worker_total_cpu": int(total_cpu),
            "run_worker_attempt_cpu": 1,
        }
    )
    CONFIG.write_text(json.dumps(current_cfg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if enable_multi_slot:
        subprocess.run(
            [
                "systemctl",
                "--user",
                "set-environment",
                "H2OMETA_REMOTE_ENABLE_MULTI_SLOT=1",
                f"H2OMETA_REMOTE_RUN_WORKER_SLOTS={int(slots)}",
                f"H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU={int(total_cpu)}",
                "H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_CPU=1",
            ],
            check=True,
        )
    else:
        subprocess.run(
            [
                "systemctl",
                "--user",
                "unset-environment",
                "H2OMETA_REMOTE_ENABLE_MULTI_SLOT",
                "H2OMETA_REMOTE_RUN_WORKER_SLOTS",
                "H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU",
                "H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_CPU",
            ],
            check=True,
        )
    subprocess.run(["systemctl", "--user", "restart", "h2ometa-remote.service"], check=True)
    wait_ready()
    wait_worker_config(slots=slots)


def restore_worker_default():
    configure_worker(slots=1, total_cpu=1, enable_multi_slot=False)
    state = current_worker_state()
    emit("RESTORE_DEFAULT", state)
    return state


def wait_worker_config(*, slots, timeout=45):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        state = current_worker_state()
        last = state
        if (
            len(state["workers"]) == 1
            and int(state["workers"][0].get("concurrency_limit") or 0) == int(slots)
            and len(state["slots"]) == int(slots)
            and all(slot.get("session_id") == state["workers"][0].get("session_id") for slot in state["slots"])
        ):
            return state
        time.sleep(0.5)
    raise TimeoutError(json.dumps({"expectedSlots": int(slots), "lastWorkerState": last}, sort_keys=True))


def upload_sample(label, repeats):
    sample = (("@read\nACGTACGTACGTACGT\n+\n!!!!!!!!!!!!!!!!\n") * int(repeats)).encode("ascii")
    return request(
        "POST",
        "/api/v1/uploads",
        {
            "filename": f"p0-3c-policy-{label}.fastq",
            "contentBase64": base64.b64encode(sample).decode("ascii"),
            "mimeType": "text/plain",
        },
        timeout=60,
    )


def submit_run(label, *, execution, repeats=120000):
    upload = upload_sample(label, repeats)
    run_id = f"run_policy_{label}_{uuid.uuid4().hex[:10]}"
    payload = {
        "serverId": "remote-direct-p0-3c-policy",
        "requestId": f"req_policy_{label}_{uuid.uuid4().hex[:10]}",
        "runSpec": {
            "runId": run_id,
            "projectId": "proj_p0_3c_policy",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "reads"}],
            "params": {"threads": 1},
            "execution": execution,
        },
    }
    submitted = request("POST", "/api/v1/runs", payload, timeout=30)
    return str(submitted["runId"])


def wait_resource_wait(run_id, timeout=90):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        row = db_one(
            """
            SELECT state, wait_reason_json
            FROM run_jobs
            WHERE run_id = ?
            """,
            (run_id,),
        )
        last = row or {}
        if row and row["state"] == "queued":
            reason = json.loads(row.get("wait_reason_json") or "{}")
            if reason:
                return {"runId": run_id, "waitReason": reason}
        time.sleep(0.2)
    raise TimeoutError(json.dumps({"runId": run_id, "lastJob": last}, sort_keys=True))


def wait_job_state(run_id, state, timeout=120):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        row = db_one("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,))
        last = row or {}
        if row and row["state"] == state:
            return row
        time.sleep(0.5)
    raise TimeoutError(json.dumps({"runId": run_id, "state": state, "lastJob": last}, sort_keys=True))


def kill_worker_for_attempt(attempt):
    worker_pid = int(attempt["pid"])
    main_pid = int(subprocess.check_output(
        ["systemctl", "--user", "show", "h2ometa-remote.service", "--property=MainPID", "--value"],
        text=True,
    ).strip() or "0")
    if worker_pid <= 0 or worker_pid != main_pid:
        raise RuntimeError(f"worker pid mismatch before kill: worker={worker_pid} main={main_pid}")
    os.kill(worker_pid, signal.SIGKILL)
    return {"workerPid": worker_pid, "signal": "SIGKILL", "attemptId": attempt["attempt_id"]}


def wait_worker_restart(old_pid, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        main_raw = subprocess.check_output(
            ["systemctl", "--user", "show", "h2ometa-remote.service", "--property=MainPID", "--value"],
            text=True,
        ).strip()
        main_pid = int(main_raw or 0)
        if main_pid > 0 and main_pid != int(old_pid) and pathlib.Path(f"/proc/{main_pid}").exists():
            wait_ready()
            return {"oldPid": int(old_pid), "newPid": main_pid}
        time.sleep(0.5)
    raise TimeoutError(f"worker did not restart: oldPid={old_pid}")


def count_attempts(run_id):
    row = db_one("SELECT COUNT(*) AS count FROM run_attempts WHERE run_id = ?", (run_id,))
    return int(row["count"] if row else 0)


def prove_retry_backoff():
    backoff_seconds = 12
    run_id = submit_run(
        "backoff",
        repeats=180000,
        execution={
            "retryPolicy": {"maxAttempts": 2, "backoffSeconds": backoff_seconds},
            "timeoutPolicy": {
                "queueTtlSeconds": 0,
                "startToCloseTimeoutSeconds": 0,
                "heartbeatTimeoutSeconds": 30,
            },
        },
    )
    first = wait_attempt(run_id, attempt_number=1, require_process_group=True)
    killed = kill_worker_for_attempt(first)
    restarted = wait_worker_restart(killed["workerPid"])
    requeue = wait_event(run_id, "run_job_requeued")
    available_at = requeue["payload"].get("availableAt")
    event_at = requeue["occurred_at"]
    if not available_at:
        raise RuntimeError(f"requeue event missing availableAt: {requeue}")
    actual_backoff = (parse_utc(available_at) - parse_utc(event_at)).total_seconds()
    if actual_backoff < backoff_seconds:
        raise RuntimeError(f"retry backoff too short: expected={backoff_seconds} actual={actual_backoff}")
    attempts_before_available = count_attempts(run_id)
    remaining = (parse_utc(available_at) - datetime.now(timezone.utc)).total_seconds()
    if remaining > 1:
        time.sleep(min(remaining - 0.5, 5))
        if count_attempts(run_id) != attempts_before_available:
            raise RuntimeError("job was reclaimed before retry availableAt")
    second = wait_attempt(run_id, attempt_number=2, timeout=120)
    final = wait_terminal(run_id)
    recovery = wait_event(
        run_id,
        "run_control_plane_recovered",
        lambda payload: payload.get("reasonCode") == "LEASE_EXPIRED"
        and payload.get("action") == "requeue_after_lease_expiry",
    )
    evidence = {
        "runId": run_id,
        "oldAttemptId": first["attempt_id"],
        "newAttemptId": second["attempt_id"],
        "killed": killed,
        "restarted": restarted,
        "availableAt": available_at,
        "eventAt": event_at,
        "backoffSeconds": int(actual_backoff),
        "attemptsBeforeAvailable": attempts_before_available,
        "finalStatus": final.get("status"),
        "recovery": recovery["payload"],
    }
    if final.get("status") != "completed":
        raise RuntimeError(f"backoff recovery run did not complete: {final}")
    emit("POLICY_BACKOFF_EVIDENCE", evidence)
    return evidence


def prove_attempt_timeout():
    run_id = submit_run(
        "attempt_timeout",
        repeats=220000,
        execution={
            "retryPolicy": {"maxAttempts": 1, "backoffSeconds": 0},
            "timeoutPolicy": {
                "queueTtlSeconds": 0,
                "startToCloseTimeoutSeconds": 1,
                "heartbeatTimeoutSeconds": 0,
            },
        },
    )
    fence = wait_event(
        run_id,
        "run_attempt_fenced",
        lambda payload: payload.get("reason") == "attempt_timeout",
        timeout=120,
    )
    recovery = wait_event(
        run_id,
        "run_control_plane_recovered",
        lambda payload: payload.get("reasonCode") == "ATTEMPT_TIMEOUT",
        timeout=120,
    )
    final = wait_terminal(run_id, timeout=180)
    job = wait_job_state(run_id, "failed", timeout=30)
    evidence = {
        "runId": run_id,
        "attemptId": fence["payload"].get("attemptId"),
        "fenceReason": fence["payload"].get("reason"),
        "recovery": recovery["payload"],
        "jobState": job["state"],
        "finalStatus": final.get("status"),
    }
    if final.get("status") != "failed":
        raise RuntimeError(f"attempt-timeout run did not fail: {final}")
    emit("POLICY_ATTEMPT_TIMEOUT_EVIDENCE", evidence)
    return evidence


def prove_queue_ttl_resource_wait():
    configure_worker(slots=2, total_cpu=1, enable_multi_slot=True)
    blocker_id = submit_run(
        "ttl_blocker",
        repeats=260000,
        execution={
            "retryPolicy": {"maxAttempts": 1, "backoffSeconds": 0},
            "timeoutPolicy": {
                "queueTtlSeconds": 0,
                "startToCloseTimeoutSeconds": 0,
                "heartbeatTimeoutSeconds": 0,
            },
        },
    )
    blocker = wait_attempt(blocker_id, attempt_number=1, require_process_group=True)
    ttl_id = submit_run(
        "queue_ttl",
        repeats=20000,
        execution={
            "retryPolicy": {"maxAttempts": 1, "backoffSeconds": 0},
            "timeoutPolicy": {
                "queueTtlSeconds": 3,
                "startToCloseTimeoutSeconds": 0,
                "heartbeatTimeoutSeconds": 0,
            },
        },
    )
    wait = wait_resource_wait(ttl_id)
    recovery = wait_event(
        ttl_id,
        "run_control_plane_recovered",
        lambda payload: payload.get("reasonCode") == "QUEUE_TTL_EXCEEDED",
        timeout=90,
    )
    final = wait_terminal(ttl_id, timeout=120)
    if final.get("status") != "failed":
        raise RuntimeError(f"queue-ttl run did not fail: {final}")
    request("POST", f"/api/v1/runs/{blocker_id}/cancel", {}, timeout=10)
    blocker_final = wait_terminal(blocker_id, timeout=180)
    evidence = {
        "blockerRunId": blocker_id,
        "blockerAttemptId": blocker["attempt_id"],
        "blockerFinalStatus": blocker_final.get("status"),
        "ttlRunId": ttl_id,
        "wait": wait,
        "recovery": recovery["payload"],
        "finalStatus": final.get("status"),
    }
    emit("POLICY_QUEUE_TTL_EVIDENCE", evidence)
    return evidence


def post_acceptance_invariants(run_ids):
    marks = ",".join("?" for _ in run_ids)
    leaks = db_rows(
        f"""
        SELECT run_id, attempt_id, slot_id, state
        FROM run_resource_allocations
        WHERE run_id IN ({marks}) AND state = 'allocated'
        """,
        tuple(run_ids),
    ) if run_ids else []
    active_leases = db_rows(
        f"""
        SELECT run_id, attempt_id, slot_id, state
        FROM run_leases
        WHERE run_id IN ({marks}) AND state = 'active'
        """,
        tuple(run_ids),
    ) if run_ids else []
    worker_state = current_worker_state()
    workers = worker_state["workers"]
    slots = worker_state["slots"]
    errors = []
    if leaks:
        errors.append("allocated resource rows remain")
    if active_leases:
        errors.append("active leases remain")
    if len(workers) != 1 or int(workers[0].get("concurrency_limit") or 0) != 1:
        errors.append("active worker is not restored to single-slot concurrency")
    if len(slots) != 1 or slots[0].get("slot_id") != "slot-0" or slots[0].get("state") != "idle":
        errors.append("active slot state is not restored to one idle slot")
    payload = {
        "ok": not errors,
        "errors": errors,
        "allocatedLeaks": leaks,
        "activeLeases": active_leases,
        "workers": workers,
        "slots": slots,
    }
    emit("POST_POLICY_INVARIANTS", payload)
    if errors:
        raise RuntimeError(f"post-policy invariants failed: {errors}")
    return payload


all_run_ids = []
restored = False
try:
    ready = wait_ready()
    current = pathlib.Path(ROOT / "current").resolve()
    preflight = {
        "status": ready.get("status"),
        "release": str(current),
        "executionPolicyModule": (current / "remote_runner" / "execution_policy.py").exists(),
        "workerState": current_worker_state(),
    }
    emit("POLICY_PREFLIGHT", preflight)
    if not preflight["executionPolicyModule"]:
        raise RuntimeError(f"deployed runner is missing execution_policy.py: {current}")
    restore_worker_default()
    restored = True

    backoff = prove_retry_backoff()
    all_run_ids.append(backoff["runId"])
    timeout = prove_attempt_timeout()
    all_run_ids.append(timeout["runId"])
    queue_ttl = prove_queue_ttl_resource_wait()
    all_run_ids.extend([queue_ttl["blockerRunId"], queue_ttl["ttlRunId"]])

    restore_worker_default()
    invariants = post_acceptance_invariants(all_run_ids)
    emit_observability("post-policy-acceptance", all_run_ids)
    emit(
        "POLICY_ACCEPTANCE_SUMMARY",
        {
            "backoffRunId": backoff["runId"],
            "attemptTimeoutRunId": timeout["runId"],
            "queueTtlRunId": queue_ttl["ttlRunId"],
            "postAcceptanceOk": invariants["ok"],
        },
    )
    print("RESULT: ok", flush=True)
finally:
    if not restored:
        try:
            restore_worker_default()
            emit("RESTORE_AFTER_FAILURE", {"ok": True})
        except Exception as exc:
            emit("RESTORE_AFTER_FAILURE", {"ok": False, "error": str(exc)})
'''


def _connect():
    from config import get_config, normalize_ssh_config, resolve_ssh_config_target, resolve_ssh_password
    from core.remote.ssh_connector import ssh_connect

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


def _remote_command() -> str:
    encoded = base64.b64encode(REMOTE_POLICY_ACCEPTANCE_SCRIPT.encode("utf-8")).decode("ascii")
    return f"""
set -euo pipefail
ROOT="$HOME/.h2ometa/runner"
CONFIG="$ROOT/shared/config/runner.json"
restore_default() {{
if [ -f "$CONFIG" ]; then
python3 - "$CONFIG" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
cfg = json.loads(path.read_text(encoding="utf-8"))
cfg.update({{
    "run_worker_slot_count": 1,
    "run_worker_total_cpu": 1,
    "run_worker_attempt_cpu": 1,
}})
path.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
PY
fi
systemctl --user unset-environment H2OMETA_REMOTE_ENABLE_MULTI_SLOT H2OMETA_REMOTE_RUN_WORKER_SLOTS H2OMETA_REMOTE_RUN_WORKER_TOTAL_CPU H2OMETA_REMOTE_RUN_WORKER_ATTEMPT_CPU >/dev/null 2>&1 || true
systemctl --user restart h2ometa-remote.service >/dev/null 2>&1 || true
}}
trap 'code=$?; restore_default; exit $code' EXIT
python3 - <<'PY'
import base64
exec(compile(base64.b64decode({encoded!r}).decode("utf-8"), "remote_execution_policy_acceptance.py", "exec"))
PY
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-policy-restart",
        action="store_true",
        help="Required acknowledgement that this acceptance restarts the remote runner and sends SIGKILL once.",
    )
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not args.allow_policy_restart:
        print("ERROR: --allow-policy-restart is required.")
        return 2

    client = _connect()
    try:
        _stdin, stdout, stderr = client.exec_command(_remote_command(), timeout=900)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if out:
            print(out, end="")
        if err:
            print(err, end="", file=sys.stderr)
        return exit_code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
