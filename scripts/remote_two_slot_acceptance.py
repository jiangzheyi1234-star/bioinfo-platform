#!/usr/bin/env python3
"""Run a real remote-runner two-slot Snakemake acceptance against the configured SSH host."""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


REMOTE_ACCEPTANCE_SCRIPT = r'''
import base64
import json
import pathlib
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
        },
    )


def wait_ready(timeout=60):
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
    with sqlite3.connect(str(db_path), timeout=10) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(query, params).fetchall()]


def target_snapshot(run_ids):
    marks = ",".join("?" for _ in run_ids)
    rows = db_rows(
        f"""
        SELECT runs.run_id, runs.status, runs.stage,
               jobs.state AS job_state, jobs.wait_reason_json,
               attempts.attempt_id, attempts.state AS attempt_state,
               attempts.slot_id AS attempt_slot_id, attempts.process_pid,
               leases.state AS lease_state, leases.slot_id AS lease_slot_id,
               allocations.state AS allocation_state, allocations.slot_id AS allocation_slot_id
        FROM runs
        LEFT JOIN run_jobs AS jobs ON jobs.run_id = runs.run_id
        LEFT JOIN run_attempts AS attempts ON attempts.run_id = runs.run_id
        LEFT JOIN run_leases AS leases ON leases.run_id = runs.run_id
        LEFT JOIN run_resource_allocations AS allocations ON allocations.run_id = runs.run_id
        WHERE runs.run_id IN ({marks})
        ORDER BY runs.run_id, attempts.created_at
        """,
        tuple(run_ids),
    )
    active = [
        row for row in rows
        if row.get("allocation_state") == "allocated" and row.get("lease_state") == "active"
    ]
    waiting = []
    for row in rows:
        reason = json.loads(row.get("wait_reason_json") or "{}")
        if row.get("job_state") == "queued" and reason:
            waiting.append({"runId": row["run_id"], "waitReason": reason})
    return {"rows": rows, "active": active, "waiting": waiting}


def wait_for_two_active(run_ids, timeout=90):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        snap = target_snapshot(run_ids)
        active_run_ids = {row["run_id"] for row in snap["active"]}
        active_slots = {row["allocation_slot_id"] for row in snap["active"]}
        if len(active_run_ids) >= 2 and len(active_slots) >= 2:
            return snap
        last = snap
        time.sleep(0.2)
    raise TimeoutError(json.dumps({"lastSnapshot": last}, sort_keys=True))


def wait_for_resource_wait(run_ids, timeout=90):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        snap = target_snapshot(run_ids)
        if snap["active"] and snap["waiting"]:
            return snap
        last = snap
        time.sleep(0.1)
    raise TimeoutError(json.dumps({"lastSnapshot": last}, sort_keys=True))


def wait_terminal(run_ids, timeout=240):
    deadline = time.monotonic() + timeout
    final = {}
    terminal = {"completed", "failed", "canceled", "cancelled"}
    while time.monotonic() < deadline:
        final = {run_id: request("GET", f"/api/v1/runs/{run_id}", timeout=10) for run_id in run_ids}
        if all(item.get("status") in terminal for item in final.values()):
            return final
        time.sleep(1)
    raise TimeoutError(json.dumps({"final": final}, sort_keys=True))


def submit_run(label):
    sample = ("@read\nACGTACGTACGTACGT\n+\n!!!!!!!!!!!!!!!!\n" * 400000).encode("ascii")
    upload = request(
        "POST",
        "/api/v1/uploads",
        {
            "filename": f"p0-3b-{label}.fastq",
            "contentBase64": base64.b64encode(sample).decode("ascii"),
            "mimeType": "text/plain",
        },
        timeout=30,
    )
    payload = {
        "serverId": "remote-direct-p0-3b",
        "requestId": f"req_p0_3b_{label}_{uuid.uuid4().hex[:10]}",
        "runSpec": {
            "projectId": "proj_p0_3b",
            "pipelineId": "file-summary-v1",
            "inputs": [{"uploadId": upload["uploadId"], "filename": upload["filename"], "role": "reads"}],
            "params": {"threads": 1},
        },
    }
    return request("POST", "/api/v1/runs", payload, timeout=30)


def configure_worker(*, slots, total_cpu, enable_multi_slot=True):
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    cfg.update(
        {
            "run_worker_slot_count": int(slots),
            "run_worker_total_cpu": int(total_cpu),
            "run_worker_attempt_cpu": 1,
        }
    )
    CONFIG.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n", encoding="utf-8")
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


def current_worker_state():
    workers = db_rows(
        """
        SELECT worker_id, session_id, concurrency_limit, state
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
        ORDER BY slot_id
        """
    )
    return {"workers": workers, "slots": slots}


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


def restore_worker_default():
    configure_worker(slots=1, total_cpu=1, enable_multi_slot=False)
    state = current_worker_state()
    emit("RESTORE_DEFAULT", state)
    return state


def post_acceptance_invariants(run_ids):
    marks = ",".join("?" for _ in run_ids)
    leaks = db_rows(
        f"""
        SELECT run_id, attempt_id, slot_id, state
        FROM run_resource_allocations
        WHERE run_id IN ({marks}) AND state = 'allocated'
        """,
        tuple(run_ids),
    )
    active_leases = db_rows(
        f"""
        SELECT run_id, attempt_id, slot_id, state
        FROM run_leases
        WHERE run_id IN ({marks}) AND state = 'active'
        """,
        tuple(run_ids),
    )
    unfinished_jobs = db_rows(
        f"""
        SELECT run_id, state, wait_reason_json
        FROM run_jobs
        WHERE run_id IN ({marks}) AND state NOT IN ('completed', 'failed', 'cancelled', 'canceled')
        """,
        tuple(run_ids),
    )
    worker_state = current_worker_state()
    workers = worker_state["workers"]
    slots = worker_state["slots"]
    errors = []
    if leaks:
        errors.append("allocated resource rows remain")
    if active_leases:
        errors.append("active leases remain")
    if unfinished_jobs:
        errors.append("unfinished run jobs remain")
    if len(workers) != 1 or int(workers[0].get("concurrency_limit") or 0) != 1:
        errors.append("active worker is not restored to single-slot concurrency")
    if len(slots) != 1 or slots[0].get("slot_id") != "slot-0" or slots[0].get("state") != "idle":
        errors.append("active slot state is not restored to one idle slot")
    payload = {
        "ok": not errors,
        "errors": errors,
        "allocatedLeaks": leaks,
        "activeLeases": active_leases,
        "unfinishedJobs": unfinished_jobs,
        "workers": workers,
        "slots": slots,
    }
    emit("POST_ACCEPTANCE_INVARIANTS", payload)
    if errors:
        raise RuntimeError(f"post-acceptance invariants failed: {errors}")
    return payload


all_run_ids = []
restored = False
try:
    ready = wait_ready()
    state = json.loads(STATE.read_text(encoding="utf-8"))
    emit("RUNNER_READY", {"status": ready.get("status"), "bindPort": state["bindPort"], "pid": state.get("pid")})
    configure_worker(slots=2, total_cpu=2)
    worker_state = current_worker_state()
    emit("WORKER_SLOTS", worker_state)
    if not any(int(row.get("concurrency_limit") or 0) == 2 for row in worker_state["workers"]):
        raise RuntimeError(f"2-slot worker not registered: {worker_state['workers']}")

    submitted = [submit_run(str(index)) for index in range(3)]
    run_ids = [item["runId"] for item in submitted]
    all_run_ids.extend(run_ids)
    emit("RUNS_SUBMITTED", {"runIds": run_ids})

    evidence = wait_for_two_active(run_ids)
    active_summary = [
        {
            "runId": row["run_id"],
            "attemptId": row["attempt_id"],
            "slotId": row["allocation_slot_id"],
            "processPid": row["process_pid"],
        }
        for row in evidence["active"]
    ]
    emit("CONCURRENCY_EVIDENCE", {"active": active_summary})

    cancel_run_id = active_summary[0]["runId"]
    other_active_run_id = active_summary[1]["runId"]
    cancel_result = request("POST", f"/api/v1/runs/{cancel_run_id}/cancel", {}, timeout=10)
    emit("CANCEL_REQUESTED", {"runId": cancel_run_id, "result": cancel_result})

    final = wait_terminal(run_ids)
    emit("RUNS_FINAL", final)
    if final[cancel_run_id].get("status") not in {"canceled", "cancelled"}:
        raise RuntimeError(f"cancel target did not cancel: {final[cancel_run_id]}")
    if final[other_active_run_id].get("status") != "completed":
        raise RuntimeError(f"other active run did not complete: {final[other_active_run_id]}")

    leaks = db_rows(
        f"""
        SELECT run_id, attempt_id, slot_id, state
        FROM run_resource_allocations
        WHERE run_id IN ({",".join("?" for _ in run_ids)}) AND state = 'allocated'
        """,
        tuple(run_ids),
    )
    slot_final = current_worker_state()["slots"]
    emit("FINAL_DB_STATE", {"allocatedLeaks": leaks, "slots": slot_final})
    if leaks:
        raise RuntimeError(f"resource allocations leaked: {leaks}")

    configure_worker(slots=2, total_cpu=1)
    wait_submitted = [submit_run(f"wait-{index}") for index in range(2)]
    wait_run_ids = [item["runId"] for item in wait_submitted]
    all_run_ids.extend(wait_run_ids)
    wait_evidence = wait_for_resource_wait(wait_run_ids)
    emit(
        "RESOURCE_WAIT_EVIDENCE",
        {
            "runIds": wait_run_ids,
            "active": [
                {"runId": row["run_id"], "attemptId": row["attempt_id"], "slotId": row["allocation_slot_id"]}
                for row in wait_evidence["active"]
            ],
            "waiting": wait_evidence["waiting"],
        },
    )
    wait_final = wait_terminal(wait_run_ids)
    emit("RESOURCE_WAIT_FINAL", wait_final)
    restore_worker_default()
    restored = True
    invariants = post_acceptance_invariants(all_run_ids)
    emit_observability("post-two-slot-acceptance", all_run_ids)
    emit(
        "ACCEPTANCE_SUMMARY",
        {
            "twoSlotRunIds": run_ids,
            "resourceWaitRunIds": wait_run_ids,
            "cancelledRunId": cancel_run_id,
            "completedSiblingRunId": other_active_run_id,
            "postAcceptanceOk": invariants["ok"],
        },
    )
    print("RESULT: ok", flush=True)
finally:
    if not restored:
        try:
            restore_worker_default()
            emit("RESTORE_AFTER_FAILURE", {"ok": True})
        except Exception as exc:  # noqa: BLE001 - acceptance must report failed cleanup clearly.
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
    encoded = base64.b64encode(REMOTE_ACCEPTANCE_SCRIPT.encode("utf-8")).decode("ascii")
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
exec(compile(base64.b64decode({encoded!r}).decode("utf-8"), "remote_two_slot_acceptance.py", "exec"))
PY
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-two-slot",
        action="store_true",
        help="Required acknowledgement that the remote runner service will be restarted with 2-slot gate enabled.",
    )
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    if not args.allow_two_slot:
        print("ERROR: --allow-two-slot is required.")
        return 2

    client = _connect()
    try:
        _stdin, stdout, stderr = client.exec_command(_remote_command(), timeout=360)
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
