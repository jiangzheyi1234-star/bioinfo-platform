from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import RemoteRunnerConfig
from .rule_execution_storage import append_run_rule_event, fetch_run_rules, upsert_run_rule_state

RULE_TERMINAL_STATUSES = {"blocked", "failed", "skipped", "succeeded"}
SNAKEMAKE_RULE_EVENTS = {"JOB_ERROR", "JOB_FINISHED", "JOB_INFO", "JOB_STARTED", "SHELLCMD"}


class SnakemakeRuleEventProjector:
    def __init__(
        self,
        cfg: RemoteRunnerConfig,
        *,
        run_id: str,
        attempt_id: str | None,
        lease_generation: int | None,
        attempt_number: int | None,
        event_log_path: Path,
    ) -> None:
        self._cfg = cfg
        self._run_id = run_id
        self._attempt_id = attempt_id
        self._lease_generation = lease_generation
        self._attempt_number = attempt_number
        self._event_log_path = event_log_path
        self._offset = 0
        self._event_count = 0
        self._job_rules: dict[str, str] = {}
        self._rules_by_name: dict[str, dict[str, Any]] = {}
        self._rules_loaded = False
        self._last_reason = "not_polled"

    def poll(self) -> dict[str, Any]:
        return self._poll(require_complete_line=True)

    def finalize(self, *, workflow_succeeded: bool) -> dict[str, Any]:
        self._poll(require_complete_line=False)
        if self._event_count == 0:
            return self._result(False, self._last_reason, new_event_count=0)
        terminal_count = _project_workflow_terminal_rules(
            self._cfg,
            run_id=self._run_id,
            attempt_id=str(self._attempt_id),
            lease_generation=int(self._lease_generation),
            attempt_number=self._attempt_number,
            rules_by_name=self._rules_by_name,
            workflow_succeeded=workflow_succeeded,
        )
        self._event_count += terminal_count
        return self._result(True, "snakemake_logger", new_event_count=terminal_count)

    def _poll(self, *, require_complete_line: bool) -> dict[str, Any]:
        if not _has_attempt_context(self._attempt_id, self._lease_generation):
            return self._result(False, "attempt_context_required", new_event_count=0)
        if not self._event_log_path.exists():
            self._last_reason = "event_log_missing"
            return self._result(False, self._last_reason, new_event_count=0)

        self._ensure_rules_loaded()
        records, self._offset = _read_event_records_since(
            self._event_log_path,
            self._offset,
            require_complete_line=require_complete_line,
        )
        new_count = _project_event_records(
            self._cfg,
            run_id=self._run_id,
            attempt_id=str(self._attempt_id),
            lease_generation=int(self._lease_generation),
            attempt_number=self._attempt_number,
            records=records,
            job_rules=self._job_rules,
            rules_by_name=self._rules_by_name,
        )
        self._event_count += new_count
        if new_count > 0:
            self._last_reason = "snakemake_logger_live"
        elif self._event_count == 0:
            self._last_reason = "no_rule_events"
        return self._result(self._event_count > 0, self._last_reason, new_event_count=new_count)

    def _ensure_rules_loaded(self) -> None:
        if self._rules_loaded:
            return
        self._rules_by_name = _attempt_rules_by_name(
            self._cfg,
            self._run_id,
            str(self._attempt_id),
            int(self._lease_generation),
        )
        self._rules_loaded = True

    def _result(self, projected: bool, reason: str, *, new_event_count: int) -> dict[str, Any]:
        return {
            "projected": projected,
            "reason": reason,
            "eventCount": self._event_count,
            "newEventCount": new_event_count,
        }


def project_snakemake_rule_events(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str | None,
    lease_generation: int | None,
    attempt_number: int | None,
    event_log_path: Path,
    workflow_succeeded: bool | None,
) -> dict[str, Any]:
    if not _has_attempt_context(attempt_id, lease_generation):
        return {"projected": False, "reason": "attempt_context_required", "eventCount": 0}
    if not event_log_path.exists():
        return {"projected": False, "reason": "event_log_missing", "eventCount": 0}

    records = _read_event_records(event_log_path)
    job_rules: dict[str, str] = {}
    rules_by_name = _attempt_rules_by_name(cfg, run_id, str(attempt_id), int(lease_generation))
    projected_count = _project_event_records(
        cfg,
        run_id=run_id,
        attempt_id=str(attempt_id),
        lease_generation=int(lease_generation),
        attempt_number=attempt_number,
        records=records,
        job_rules=job_rules,
        rules_by_name=rules_by_name,
    )

    if projected_count == 0:
        return {"projected": False, "reason": "no_rule_events", "eventCount": 0}
    projected_count += _project_workflow_terminal_rules(
        cfg,
        run_id=run_id,
        attempt_id=str(attempt_id),
        lease_generation=int(lease_generation),
        attempt_number=attempt_number,
        rules_by_name=rules_by_name,
        workflow_succeeded=workflow_succeeded,
    )
    return {"projected": True, "reason": "snakemake_logger", "eventCount": projected_count}

def _project_event_records(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    records: list[dict[str, Any]],
    job_rules: dict[str, str],
    rules_by_name: dict[str, dict[str, Any]],
) -> int:
    projected_count = 0
    for record in records:
        event = _event_name(record)
        if event not in SNAKEMAKE_RULE_EVENTS:
            continue
        if event == "JOB_INFO":
            projected_count += _project_job_info(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                record=record,
                job_rules=job_rules,
                rules_by_name=rules_by_name,
            )
        elif event == "JOB_STARTED":
            projected_count += _project_job_started(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                record=record,
                job_rules=job_rules,
                rules_by_name=rules_by_name,
            )
        elif event == "SHELLCMD":
            projected_count += _project_shellcmd(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                record=record,
                job_rules=job_rules,
                rules_by_name=rules_by_name,
            )
        elif event == "JOB_FINISHED":
            projected_count += _project_terminal_event(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                record=record,
                job_rules=job_rules,
                rules_by_name=rules_by_name,
                status="succeeded",
                event_type="rule_finished",
                exit_code=0,
                message="Snakemake rule finished.",
            )
        elif event == "JOB_ERROR":
            projected_count += _project_terminal_event(
                cfg,
                run_id=run_id,
                attempt_id=attempt_id,
                lease_generation=lease_generation,
                attempt_number=attempt_number,
                record=record,
                job_rules=job_rules,
                rules_by_name=rules_by_name,
                status="failed",
                event_type="rule_failed",
                exit_code=1,
                message=_record_message(record) or "Snakemake rule failed.",
            )
    return projected_count


def _project_workflow_terminal_rules(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    rules_by_name: dict[str, dict[str, Any]],
    workflow_succeeded: bool | None,
) -> int:
    if workflow_succeeded is True:
        return _mark_unfinished_rules(
            cfg,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            rules_by_name=rules_by_name,
            status="skipped",
            event_type="rule_skipped",
            message="Snakemake completed without executing this rule in this attempt.",
        )
    if workflow_succeeded is False:
        return _mark_unfinished_rules(
            cfg,
            run_id=run_id,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            rules_by_name=rules_by_name,
            status="blocked",
            event_type="rule_blocked",
            message="Workflow failed before this rule reached a terminal state.",
        )
    return 0


def _project_job_info(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    record: dict[str, Any],
    job_rules: dict[str, str],
    rules_by_name: dict[str, dict[str, Any]],
) -> int:
    rule_name = _rule_name(record, job_rules)
    if not rule_name:
        return 0
    job_id = _job_id(record)
    if job_id:
        job_rules[job_id] = rule_name
    current = rules_by_name.get(rule_name, {})
    status = _non_terminal_status(str(current.get("status") or "planned"))
    updated = upsert_run_rule_state(
        cfg,
        run_id=run_id,
        rule_name=rule_name,
        step_id=str(current.get("stepId") or ""),
        runtime_status_key=str(current.get("runtimeStatusKey") or f"rule:{rule_name}"),
        status=status,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        command_summary=_record_shellcmd(record) or str(current.get("commandSummary") or ""),
        inputs=_record_list(record, "input", current.get("inputs")),
        outputs=_record_list(record, "output", current.get("outputs")),
        wildcards=_record_dict(record, "wildcards", current.get("wildcards")),
        logs=_record_list(record, "log", current.get("logs")),
        occurred_at=_created_at(record),
    )
    rules_by_name[rule_name] = updated
    append_run_rule_event(
        cfg,
        run_id=run_id,
        rule_name=rule_name,
        step_id=str(updated.get("stepId") or ""),
        event_type="rule_observed",
        status=status,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        message=_record_message(record) or "Snakemake reported rule job metadata.",
        details=_event_details(record),
        occurred_at=_created_at(record),
    )
    return 1


def _project_job_started(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    record: dict[str, Any],
    job_rules: dict[str, str],
    rules_by_name: dict[str, dict[str, Any]],
) -> int:
    count = 0
    for job_id in _job_ids(record):
        rule_name = job_rules.get(job_id)
        if not rule_name:
            continue
        current = rules_by_name.get(rule_name, {})
        updated = upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(current.get("stepId") or ""),
            runtime_status_key=str(current.get("runtimeStatusKey") or f"rule:{rule_name}"),
            status="running",
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            started_at=_created_at(record),
            command_summary=str(current.get("commandSummary") or ""),
            inputs=_string_list(current.get("inputs")),
            outputs=_string_list(current.get("outputs")),
            wildcards=_record_dict(record, "wildcards", current.get("wildcards")),
            logs=_string_list(current.get("logs")),
            occurred_at=_created_at(record),
        )
        rules_by_name[rule_name] = updated
        append_run_rule_event(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(updated.get("stepId") or ""),
            event_type="rule_started",
            status="running",
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            message="Snakemake rule started.",
            details=_event_details(record),
            occurred_at=_created_at(record),
        )
        count += 1
    return count


def _project_shellcmd(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    record: dict[str, Any],
    job_rules: dict[str, str],
    rules_by_name: dict[str, dict[str, Any]],
) -> int:
    rule_name = _rule_name(record, job_rules)
    command_summary = _record_shellcmd(record)
    if not rule_name or not command_summary:
        return 0
    current = rules_by_name.get(rule_name, {})
    status = _non_terminal_status(str(current.get("status") or "running"))
    updated = upsert_run_rule_state(
        cfg,
        run_id=run_id,
        rule_name=rule_name,
        step_id=str(current.get("stepId") or ""),
        runtime_status_key=str(current.get("runtimeStatusKey") or f"rule:{rule_name}"),
        status=status,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        command_summary=command_summary,
        inputs=_string_list(current.get("inputs")),
        outputs=_string_list(current.get("outputs")),
        wildcards=_record_dict(record, "wildcards", current.get("wildcards")),
        logs=_string_list(current.get("logs")),
        occurred_at=_created_at(record),
    )
    rules_by_name[rule_name] = updated
    append_run_rule_event(
        cfg,
        run_id=run_id,
        rule_name=rule_name,
        step_id=str(updated.get("stepId") or ""),
        event_type="rule_command",
        status=status,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        message="Snakemake reported rule command.",
        details=_event_details(record),
        occurred_at=_created_at(record),
    )
    return 1


def _project_terminal_event(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    record: dict[str, Any],
    job_rules: dict[str, str],
    rules_by_name: dict[str, dict[str, Any]],
    status: str,
    event_type: str,
    exit_code: int,
    message: str,
) -> int:
    rule_name = _rule_name(record, job_rules)
    if not rule_name:
        return 0
    current = rules_by_name.get(rule_name, {})
    updated = upsert_run_rule_state(
        cfg,
        run_id=run_id,
        rule_name=rule_name,
        step_id=str(current.get("stepId") or ""),
        runtime_status_key=str(current.get("runtimeStatusKey") or f"rule:{rule_name}"),
        status=status,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        finished_at=_created_at(record),
        exit_code=exit_code,
        message=message,
        command_summary=_record_shellcmd(record) or str(current.get("commandSummary") or ""),
        inputs=_string_list(current.get("inputs")),
        outputs=_string_list(current.get("outputs")),
        wildcards=_record_dict(record, "wildcards", current.get("wildcards")),
        logs=_string_list(current.get("logs")),
        occurred_at=_created_at(record),
    )
    rules_by_name[rule_name] = updated
    append_run_rule_event(
        cfg,
        run_id=run_id,
        rule_name=rule_name,
        step_id=str(updated.get("stepId") or ""),
        event_type=event_type,
        status=status,
        attempt_id=attempt_id,
        lease_generation=lease_generation,
        attempt_number=attempt_number,
        message=message,
        details=_event_details(record),
        occurred_at=_created_at(record),
    )
    return 1


def _mark_unfinished_rules(
    cfg: RemoteRunnerConfig,
    *,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
    attempt_number: int | None,
    rules_by_name: dict[str, dict[str, Any]],
    status: str,
    event_type: str,
    message: str,
) -> int:
    count = 0
    for rule_name, current in list(rules_by_name.items()):
        if str(current.get("status") or "") in RULE_TERMINAL_STATUSES:
            continue
        updated = upsert_run_rule_state(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(current.get("stepId") or ""),
            runtime_status_key=str(current.get("runtimeStatusKey") or f"rule:{rule_name}"),
            status=status,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            message=message,
            command_summary=str(current.get("commandSummary") or ""),
            inputs=_string_list(current.get("inputs")),
            outputs=_string_list(current.get("outputs")),
            wildcards=_record_dict({}, "wildcards", current.get("wildcards")),
            logs=_string_list(current.get("logs")),
        )
        rules_by_name[rule_name] = updated
        append_run_rule_event(
            cfg,
            run_id=run_id,
            rule_name=rule_name,
            step_id=str(updated.get("stepId") or ""),
            event_type=event_type,
            status=status,
            attempt_id=attempt_id,
            lease_generation=lease_generation,
            attempt_number=attempt_number,
            message=message,
            details={"source": "snakemake_logger_projection"},
        )
        count += 1
    return count


def _read_event_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _read_event_records_since(
    path: Path,
    offset: int,
    *,
    require_complete_line: bool,
) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    start = max(0, int(offset))
    if path.stat().st_size < start:
        start = 0
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(start)
        while True:
            line_start = handle.tell()
            line = handle.readline()
            if not line:
                break
            if require_complete_line and not line.endswith("\n"):
                handle.seek(line_start)
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records, handle.tell()


def _attempt_rules_by_name(
    cfg: RemoteRunnerConfig,
    run_id: str,
    attempt_id: str,
    lease_generation: int,
) -> dict[str, dict[str, Any]]:
    return {
        str(rule.get("ruleName") or ""): rule
        for rule in fetch_run_rules(cfg, run_id).get("items", [])
        if rule.get("attemptId") == attempt_id
        and int(rule.get("leaseGeneration") or 0) == int(lease_generation)
        and str(rule.get("ruleName") or "")
    }


def _rule_name(record: dict[str, Any], job_rules: dict[str, str]) -> str:
    for key in ("ruleName", "rule_name", "name", "rule"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    job_id = _job_id(record)
    return job_rules.get(job_id, "")


def _job_id(record: dict[str, Any]) -> str:
    for key in ("jobId", "jobid", "job_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _job_ids(record: dict[str, Any]) -> list[str]:
    raw = record.get("jobIds") if "jobIds" in record else record.get("job_ids")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    single = _job_id(record)
    return [single] if single else []


def _record_shellcmd(record: dict[str, Any]) -> str:
    return str(record.get("shellcmd") or "").strip()


def _record_message(record: dict[str, Any]) -> str:
    return str(record.get("message") or "").strip()[:500]


def _record_list(record: dict[str, Any], key: str, fallback: Any) -> list[str]:
    value = record.get(key)
    if value is None:
        return _string_list(fallback)
    return _string_list(value)


def _record_dict(record: dict[str, Any], key: str, fallback: Any) -> dict[str, Any]:
    value = record.get(key)
    if isinstance(value, dict):
        return value
    return fallback if isinstance(fallback, dict) else {}


def _event_details(record: dict[str, Any]) -> dict[str, Any]:
    details = dict(record)
    details.pop("message", None)
    return details


def _event_name(record: dict[str, Any]) -> str:
    return str(record.get("event") or "").strip().upper()


def _created_at(record: dict[str, Any]) -> str | None:
    value = str(record.get("createdAt") or "").strip()
    return value or None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(item) for item in value.values() if str(item).strip()]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _non_terminal_status(status: str) -> str:
    return "running" if status == "running" else "planned"


def _has_attempt_context(attempt_id: str | None, lease_generation: int | None) -> bool:
    return bool(str(attempt_id or "").strip() and lease_generation is not None)
