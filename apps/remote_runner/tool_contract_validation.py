from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .config import RemoteRunnerConfig, inspect_workflow_runtime
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from .generated_workflow_graph import GENERATED_WORKFLOW_RULE_CONTRACT_VERSION
from .tool_contract import default_contract_status
from .tool_contract_resources import smoke_resource_bindings, workflow_resource_failure
from .tool_contract_snakemake import (
    run_snakemake as _run_snakemake,
    snakemake_event_details as _snakemake_event_details,
)
from .tool_contract_smoke import (
    materialize_smoke_inputs as _materialize_smoke_inputs,
    smoke_fixture_error as _smoke_fixture_error,
    smoke_test as _smoke_test,
    smoke_timeout as _smoke_timeout,
    smoke_workflow_inputs as _smoke_workflow_inputs,
)
from .tool_contract_validation_status import (
    set_status as _set_status,
    status_detail_value as _status_detail_value,
    validation_result as _result,
)
from .tool_output_validation import ElementTree, _validated_output_summary, _validate_outputs

ValidationEventCallback = Callable[[dict[str, Any]], None]


def run_tool_contract_validation(
    cfg: RemoteRunnerConfig,
    tool: dict[str, Any],
    event_callback: ValidationEventCallback | None = None,
) -> dict[str, Any]:
    status = default_contract_status()
    _emit_event(event_callback, "runtime_check", "Checking workflow runtime.")
    runtime = inspect_workflow_runtime(cfg)
    if not bool(runtime.get("ok")):
        _emit_event(
            event_callback,
            "runtime_check",
            str(runtime.get("message") or "Workflow runtime is not ready."),
            level="error",
            details={"reasonCode": str(runtime.get("reasonCode") or "")},
        )
        return _result(
            status=_set_status(
                status,
                "dryRun",
                "failed",
                "WORKFLOW_RUNTIME_NOT_READY",
                str(runtime.get("message") or "Workflow runtime is not ready."),
            ),
            ok=False,
            message=str(runtime.get("message") or "Workflow runtime is not ready."),
        )
    _emit_event(
        event_callback,
        "runtime_check",
        "Workflow runtime check passed.",
        level="success",
        details={"provider": str(runtime.get("provider") or ""), "version": str(runtime.get("version") or "")},
    )

    run_id = f"toolcheck_{_safe_identifier(str(tool.get('id') or tool.get('name') or 'tool'))}_{int(time.time())}"
    validation_root = Path(cfg.work_dir) / "_tool_contract_checks" / run_id
    result_dir = Path(cfg.results_dir) / "_tool_contract_checks" / run_id
    try:
        _emit_event(event_callback, "preparing_workflow", "Preparing smoke-test workflow.")
        resolved_inputs = _materialize_smoke_inputs(tool, validation_root / "inputs")
        smoke_test = _smoke_test(tool)
        tool_revision_id = str(tool.get("toolRevisionId") or "") or f"{str(tool.get('id') or '')}#candidate"
        node: dict[str, Any] = {
            "id": "run_tool",
            "toolRevisionId": tool_revision_id,
            "inputs": _smoke_workflow_inputs(tool, resolved_inputs),
        }
        if isinstance(smoke_test.get("params"), dict) and smoke_test["params"]:
            node["params"] = dict(smoke_test["params"])
        run_spec: dict[str, Any] = {
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "workflow": {
                "contractVersion": GENERATED_WORKFLOW_RULE_CONTRACT_VERSION,
                "nodes": [node],
                "edges": [],
            },
        }
        resource_bindings = smoke_resource_bindings(cfg, tool, smoke_test)
        if resource_bindings:
            run_spec["resourceBindings"] = resource_bindings
        generated = prepare_generated_tool_workflow(
            cfg,
            run_id=run_id,
            request_id=f"req_{run_id}",
            run_spec=run_spec,
            resolved_inputs=resolved_inputs,
            work_dir=validation_root / "work",
            result_dir=result_dir,
            require_workflow_ready=False,
            tool_overrides={tool_revision_id: {**tool, "toolRevisionId": tool_revision_id}},
        )
    except ValueError as exc:
        resource_failure = workflow_resource_failure(cfg, tool, exc)
        failure_code = resource_failure["code"] if resource_failure else "TOOL_VALIDATION_PREPARE_FAILED"
        failure_message = resource_failure["message"] if resource_failure else str(exc)
        failure_details = resource_failure["details"] if resource_failure else {}
        _emit_event(
            event_callback,
            "preparing_workflow",
            failure_message or "Tool validation preparation failed.",
            level="warning" if resource_failure else "error",
            details={"code": failure_code, **failure_details},
        )
        return _result(
            status=_set_status(
                status,
                "dryRun",
                "failed",
                failure_code,
                failure_message,
                details={key: _status_detail_value(value) for key, value in failure_details.items()},
            ),
            ok=False,
            message=failure_message or "Tool validation preparation failed.",
        )

    _emit_event(
        event_callback,
        "dry_run",
        "Running Snakemake dry-run.",
        details={"runId": run_id, "snakefile": str(generated.snakefile)},
    )
    dry_run = _run_snakemake(
        cfg,
        snakefile=generated.snakefile,
        work_dir=validation_root / "work",
        config_path=generated.config_path,
        dry_run=True,
        timeout=_smoke_timeout(tool),
    )
    if dry_run["returncode"] != 0:
        _emit_event(
            event_callback,
            "dry_run",
            "Snakemake dry-run failed.",
            level="error",
            details=_snakemake_event_details(dry_run),
        )
        return _result(
            status=_set_status(
                status,
                "dryRun",
                "failed",
                "SNAKEMAKE_DRY_RUN_FAILED",
                dry_run["message"],
                run_id=run_id,
                log_path=str(dry_run.get("logPath") or ""),
            ),
            ok=False,
            message="Snakemake dry-run failed.",
        )
    status = _set_status(
        status,
        "dryRun",
        "passed",
        "",
        "Snakemake dry-run passed.",
        run_id=run_id,
        log_path=str(dry_run.get("logPath") or ""),
    )
    _emit_event(
        event_callback,
        "dry_run",
        "Snakemake dry-run passed.",
        level="success",
        details=_snakemake_event_details(dry_run),
    )

    _emit_event(event_callback, "smoke_fixture", "Checking smoke-test fixtures.")
    smoke_error = _smoke_fixture_error(tool)
    if smoke_error:
        _emit_event(
            event_callback,
            "smoke_fixture",
            smoke_error["message"],
            level="error",
            details={"code": smoke_error["code"]},
        )
        return _result(
            status=_set_status(status, "smokeRun", "failed", smoke_error["code"], smoke_error["message"], run_id=run_id),
            ok=False,
            message=smoke_error["message"],
        )

    _emit_event(event_callback, "smoke_run", "Running Snakemake smoke run.", details={"runId": run_id})
    smoke_run = _run_snakemake(
        cfg,
        snakefile=generated.snakefile,
        work_dir=validation_root / "work",
        config_path=generated.config_path,
        dry_run=False,
        timeout=_smoke_timeout(tool),
    )
    if smoke_run["returncode"] != 0:
        _emit_event(
            event_callback,
            "smoke_run",
            "Snakemake smoke run failed.",
            level="error",
            details=_snakemake_event_details(smoke_run),
        )
        return _result(
            status=_set_status(
                status,
                "smokeRun",
                "failed",
                "SNAKEMAKE_SMOKE_RUN_FAILED",
                smoke_run["message"],
                run_id=run_id,
                log_path=str(smoke_run.get("logPath") or ""),
            ),
            ok=False,
            message="Snakemake smoke run failed.",
        )
    status = _set_status(
        status,
        "smokeRun",
        "passed",
        "",
        "Snakemake smoke run passed.",
        run_id=run_id,
        log_path=str(smoke_run.get("logPath") or ""),
    )
    _emit_event(
        event_callback,
        "smoke_run",
        "Snakemake smoke run passed.",
        level="success",
        details=_snakemake_event_details(smoke_run),
    )

    _emit_event(event_callback, "output_validation", "Validating declared outputs.")
    output_error = _validate_outputs(output_schema=generated.output_schema, outputs=generated.outputs)
    if output_error:
        _emit_event(
            event_callback,
            "output_validation",
            output_error["message"],
            level="error",
            details={"code": output_error["code"], "logPath": str(smoke_run.get("logPath") or "")},
        )
        return _result(
            status=_set_status(
                status,
                "outputValidation",
                "failed",
                output_error["code"],
                output_error["message"],
                run_id=run_id,
                log_path=str(smoke_run.get("logPath") or ""),
            ),
            ok=False,
            message=output_error["message"],
        )
    status = _set_status(
        status,
        "outputValidation",
        "passed",
        "",
        "Output validation passed.",
        run_id=run_id,
        log_path=str(smoke_run.get("logPath") or ""),
        details=_validated_output_summary(generated.output_schema),
    )
    _emit_event(
        event_callback,
        "output_validation",
        "Output validation passed.",
        level="success",
        details={"logPath": str(smoke_run.get("logPath") or ""), **_validated_output_summary(generated.output_schema)},
    )
    return _result(status=status, ok=True, message="Tool contract validation passed.")


def _emit_event(
    callback: ValidationEventCallback | None,
    stage: str,
    message: str,
    *,
    level: str = "info",
    details: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return
    callback(
        {
            "stage": stage,
            "message": message,
            "level": level,
            "details": details or {},
        }
    )


def _safe_identifier(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._") or "tool"
