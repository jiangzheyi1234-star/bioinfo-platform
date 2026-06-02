from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Callable

from .config import (
    RemoteRunnerConfig,
    build_workflow_runtime_environment,
    get_workflow_profile_dir,
    inspect_workflow_runtime,
)
from .generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID, prepare_generated_tool_workflow
from .generated_workflow_graph import GENERATED_WORKFLOW_RULE_CONTRACT_VERSION
from .database_templates import DATABASE_TEMPLATES
from .databases import list_reference_databases
from .snakemake_execution_lock import SNAKEMAKE_EXECUTION_LOCK
from .tool_contract import default_contract_status, normalize_contract_status


ValidationEventCallback = Callable[[dict[str, Any]], None]
WAITING_RESOURCE_CODES = {
    "RESOURCE_BINDING_MISSING",
    "RESOURCE_BINDING_AMBIGUOUS",
    "WORKFLOW_RESOURCE_BINDING_REQUIRED",
    "WORKFLOW_RESOURCE_UNAVAILABLE",
}


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
        resource_bindings = _smoke_resource_bindings(cfg, tool, smoke_test)
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
    except Exception as exc:
        resource_failure = _workflow_resource_failure(cfg, tool, exc)
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


def _run_snakemake(
    cfg: RemoteRunnerConfig,
    *,
    snakefile: Path,
    work_dir: Path,
    config_path: Path,
    dry_run: bool,
    timeout: int,
) -> dict[str, Any]:
    command = _snakemake_execution_args(cfg, snakefile=snakefile, work_dir=work_dir, config_path=config_path)
    if dry_run:
        command.append("-n")
    try:
        with SNAKEMAKE_EXECUTION_LOCK:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=build_workflow_runtime_environment(cfg),
            )
    except Exception as exc:
        log_path = _write_run_log(work_dir, dry_run=dry_run, stdout="", stderr=str(exc))
        return {"returncode": 127, "message": str(exc) or "Failed to launch Snakemake.", "logPath": str(log_path)}
    log_path = _write_run_log(work_dir, dry_run=dry_run, stdout=result.stdout or "", stderr=result.stderr or "")
    return {
        "returncode": int(result.returncode),
        "message": _tail(result.stderr or result.stdout or ""),
        "logPath": str(log_path),
    }


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


def _snakemake_event_details(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "returncode": str(result.get("returncode", "")),
        "logPath": str(result.get("logPath") or ""),
        "tail": str(result.get("message") or ""),
    }


def _snakemake_execution_args(
    cfg: RemoteRunnerConfig,
    *,
    snakefile: Path,
    work_dir: Path,
    config_path: Path,
) -> list[str]:
    snakemake_command = str(cfg.snakemake_command or "").strip()
    if not snakemake_command:
        raise RuntimeError("snakemake command not configured")
    command = [snakemake_command, "--snakefile", str(snakefile), "--directory", str(work_dir)]
    workflow_profile_dir = get_workflow_profile_dir(cfg)
    if workflow_profile_dir is not None:
        command.extend(["--workflow-profile", str(workflow_profile_dir)])
    else:
        command.extend(["--cores", "1", "--use-conda"])
    command.extend(["--configfile", str(config_path)])
    return command


def _materialize_smoke_inputs(tool: dict[str, Any], input_dir: Path) -> list[dict[str, Any]]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    specs = [item for item in (template.get("inputs") or []) if isinstance(item, dict)]
    if not specs:
        specs = [{"name": "primary", "type": "file", "required": True}]
    smoke_inputs = _smoke_test(tool).get("inputs")
    smoke_inputs = smoke_inputs if isinstance(smoke_inputs, dict) else {}
    input_dir.mkdir(parents=True, exist_ok=True)
    resolved: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        fixture = smoke_inputs.get(name) if isinstance(smoke_inputs.get(name), dict) else {}
        if not bool(spec.get("required", True)) and not fixture:
            continue
        filename = str(fixture.get("filename") or _default_input_filename(name, spec)).strip()
        path = input_dir / Path(filename).name
        content = _fixture_bytes(fixture, spec)
        path.write_bytes(content)
        resolved.append(
            {
                "uploadId": f"smoke_{name}",
                "filename": path.name,
                "role": "input" if index == 0 else f"input_{index + 1}",
                "path": str(path),
                "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "mimeType": str(fixture.get("mimeType") or spec.get("mimeType") or "text/plain"),
                "index": index,
            }
        )
    return resolved


def _smoke_workflow_inputs(tool: dict[str, Any], resolved_inputs: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    specs = [item for item in (template.get("inputs") or []) if isinstance(item, dict)]
    inputs: dict[str, dict[str, str]] = {}
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        if not name or index >= len(resolved_inputs):
            continue
        role = str(resolved_inputs[index].get("role") or "").strip()
        if role:
            inputs[name] = {"fromInput": role}
    return inputs


def _smoke_fixture_error(tool: dict[str, Any]) -> dict[str, str] | None:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    specs = [item for item in (template.get("inputs") or []) if isinstance(item, dict)]
    smoke_inputs = _smoke_test(tool).get("inputs")
    if not isinstance(smoke_inputs, dict) or not smoke_inputs:
        return {"code": "TOOL_RULE_SMOKE_TEST_REQUIRED", "message": "Smoke test input fixtures are required."}
    missing: list[str] = []
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        fixture = smoke_inputs.get(name)
        if not bool(spec.get("required", True)) and not isinstance(fixture, dict):
            continue
        if not isinstance(fixture, dict) or ("content" not in fixture and "contentBase64" not in fixture):
            missing.append(name)
    if missing:
        return {
            "code": "TOOL_RULE_SMOKE_INPUT_REQUIRED",
            "message": f"Smoke test input fixture is missing: {', '.join(missing)}",
        }
    return None


def _fixture_bytes(fixture: dict[str, Any], spec: dict[str, Any]) -> bytes:
    if "contentBase64" in fixture:
        return base64.b64decode(str(fixture["contentBase64"]).encode("utf-8"))
    if "content" in fixture:
        return str(fixture["content"]).encode("utf-8")
    return _default_input_content(spec)


def _default_input_filename(name: str, spec: dict[str, Any]) -> str:
    mime_type = str(spec.get("mimeType") or "").lower()
    kind = str(spec.get("kind") or "").lower()
    if "fastq" in mime_type or "sequence" in kind or name in {"reads", "fastq"}:
        return f"{name}.fastq"
    if "json" in mime_type:
        return f"{name}.json"
    return f"{name}.txt"


def _default_input_content(spec: dict[str, Any]) -> bytes:
    mime_type = str(spec.get("mimeType") or "").lower()
    kind = str(spec.get("kind") or "").lower()
    if "fastq" in mime_type or "sequence" in kind:
        return b"@smoke\nACGT\n+\nFFFF\n"
    if "json" in mime_type:
        return b'{"smoke": true}\n'
    return b"smoke\n"


def _validate_outputs(*, output_schema: dict[str, Any], outputs: dict[str, str]) -> dict[str, str] | None:
    artifacts = output_schema.get("artifacts") if isinstance(output_schema, dict) else None
    if not isinstance(artifacts, list) or not artifacts:
        return {"code": "OUTPUT_ARTIFACTS_REQUIRED", "message": "Output artifacts are not declared."}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            return {"code": "OUTPUT_ARTIFACT_INVALID", "message": "Output artifact metadata is invalid."}
        key = str(artifact.get("key") or "").strip()
        path = Path(str(outputs.get(key) or ""))
        if not key or key not in outputs:
            return {"code": "OUTPUT_ARTIFACT_KEY_UNKNOWN", "message": f"Output artifact key is unknown: {key}"}
        directory = bool(artifact.get("directory")) or str(artifact.get("mimeType") or "") == "inode/directory"
        if directory:
            if not path.is_dir():
                return {"code": "OUTPUT_ARTIFACT_MISSING", "message": f"Output directory is missing: {key}"}
            if not any(path.iterdir()):
                return {"code": "OUTPUT_ARTIFACT_EMPTY", "message": f"Output directory is empty: {key}"}
            continue
        if not path.is_file():
            return {"code": "OUTPUT_ARTIFACT_MISSING", "message": f"Output file is missing: {key}"}
        if path.stat().st_size <= 0:
            return {"code": "OUTPUT_ARTIFACT_EMPTY", "message": f"Output file is empty: {key}"}
        if _blank_text_output(path, str(artifact.get("mimeType") or "")):
            return {"code": "OUTPUT_ARTIFACT_EMPTY", "message": f"Output file is blank: {key}"}
        parse_error = _parseable_output_error(path, str(artifact.get("mimeType") or ""))
        if parse_error:
            return {"code": "OUTPUT_ARTIFACT_FORMAT_INVALID", "message": f"{key}: {parse_error}"}
    return None


def _blank_text_output(path: Path, mime_type: str) -> bool:
    lowered = mime_type.lower()
    suffix = path.suffix.lower()
    if not (
        lowered.startswith("text/")
        or lowered == "application/json"
        or suffix in {".json", ".csv", ".tsv", ".txt", ".log", ".md", ".html", ".xml"}
    ):
        return False
    try:
        return not path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return False


def _parseable_output_error(path: Path, mime_type: str) -> str:
    lowered = mime_type.lower()
    if lowered == "application/json" or path.suffix.lower() == ".json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return str(exc)
    if lowered == "text/tab-separated-values" or path.suffix.lower() == ".tsv":
        try:
            path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            return str(exc)
    if lowered in {"application/xml", "text/xml"} or lowered.endswith("+xml") or path.suffix.lower() == ".xml":
        try:
            ElementTree.parse(path)
        except Exception as exc:
            return str(exc)
    if lowered.startswith("text/"):
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return str(exc)
    return ""


def _validated_output_summary(output_schema: dict[str, Any]) -> dict[str, str]:
    artifacts = output_schema.get("artifacts") if isinstance(output_schema, dict) else []
    names = [str(item.get("key") or "").strip() for item in artifacts if isinstance(item, dict)]
    names = [name for name in names if name]
    return {"artifactCount": str(len(names)), "artifactNames": ",".join(names)}


def _workflow_resource_failure(cfg: RemoteRunnerConfig, tool: dict[str, Any], exc: Exception) -> dict[str, Any] | None:
    code, resource_key = _split_resource_error(str(exc))
    if code not in WAITING_RESOURCE_CODES:
        return None
    details = build_resource_wait_details(cfg, tool, resource_key)
    code = _normalized_resource_wait_code(code, details)
    return {
        "code": code,
        "message": _resource_wait_message(code, resource_key),
        "details": details,
    }


def _split_resource_error(raw: str) -> tuple[str, str]:
    code, separator, remainder = str(raw or "").partition(":")
    return code.strip(), remainder.strip() if separator else ""


def _resource_wait_message(code: str, resource_key: str) -> str:
    label = resource_key or "required database resource"
    if code in {"RESOURCE_BINDING_MISSING", "WORKFLOW_RESOURCE_BINDING_REQUIRED"}:
        return f"Required database resource binding is missing: {label}"
    if code == "RESOURCE_BINDING_AMBIGUOUS":
        return f"Required database resource binding is ambiguous: {label}"
    if code == "WORKFLOW_RESOURCE_UNAVAILABLE":
        return f"Required database resource is unavailable: {label}"
    return f"Required database resource is waiting: {label}"


def _normalized_resource_wait_code(code: str, details: dict[str, Any]) -> str:
    if code != "WORKFLOW_RESOURCE_BINDING_REQUIRED":
        return code
    candidates = details.get("candidates")
    if isinstance(candidates, list) and len(candidates) > 1:
        return "RESOURCE_BINDING_AMBIGUOUS"
    return "RESOURCE_BINDING_MISSING"


def build_resource_wait_details(cfg: RemoteRunnerConfig, tool: dict[str, Any], resource_key: str) -> dict[str, Any]:
    spec = _database_resource_specs(tool).get(resource_key, {}) if resource_key else {}
    details: dict[str, Any] = {"resourceType": "database"}
    if resource_key:
        details["resourceKey"] = resource_key
    config_key = str(spec.get("configKey") or resource_key or "").strip()
    if config_key:
        details["configKey"] = config_key
    accepted_templates = [str(item).strip() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates:
        details["acceptedTemplates"] = accepted_templates
    accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
    if accepted_capabilities:
        details["acceptedCapabilities"] = accepted_capabilities
    details["candidates"] = _resource_wait_candidates(cfg, spec)
    return details


def _resource_wait_candidates(cfg: RemoteRunnerConfig, spec: dict[str, Any]) -> list[dict[str, str]]:
    if not spec:
        return []
    return [
        _resource_wait_candidate(database)
        for database in list_reference_databases(cfg)
        if _database_matches_resource_spec(database, spec)
    ]


def _resource_wait_candidate(database: dict[str, Any]) -> dict[str, str]:
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    return {
        "id": str(database.get("id") or ""),
        "name": str(database.get("name") or ""),
        "templateId": str(metadata.get("templateId") or ""),
        "version": str(database.get("version") or ""),
        "status": str(database.get("status") or ""),
    }


def _status_detail_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _smoke_test(tool: dict[str, Any]) -> dict[str, Any]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    smoke_test = template.get("smokeTest")
    return smoke_test if isinstance(smoke_test, dict) else {}


def _smoke_resource_bindings(
    cfg: RemoteRunnerConfig,
    tool: dict[str, Any],
    smoke_test: dict[str, Any],
) -> dict[str, Any]:
    bindings = dict(smoke_test.get("resourceBindings") or {}) if isinstance(smoke_test.get("resourceBindings"), dict) else {}
    for resource_key, spec in _database_resource_specs(tool).items():
        if spec.get("required", True) is False:
            continue
        if resource_key in bindings:
            continue
        matches = [database for database in list_reference_databases(cfg) if _database_matches_resource_spec(database, spec)]
        if len(matches) == 1:
            bindings[resource_key] = {"databaseId": str(matches[0].get("id") or "")}
    return bindings


def _database_resource_specs(tool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    resources = template.get("resources")
    if not isinstance(resources, dict):
        return {}
    specs: dict[str, dict[str, Any]] = {}
    for key, value in resources.items():
        if not isinstance(value, dict):
            continue
        if value.get("acceptedTemplates") or value.get("acceptedCapabilities") or value.get("configKey") or value.get("type") == "database":
            specs[str(key)] = value
    return specs


def _database_matches_resource_spec(database: dict[str, Any], spec: dict[str, Any]) -> bool:
    if str(database.get("status") or "") != "available":
        return False
    metadata = database.get("metadata") if isinstance(database.get("metadata"), dict) else {}
    template_id = str(metadata.get("templateId") or "").strip().lower()
    accepted_templates = [str(item).strip().lower() for item in spec.get("acceptedTemplates") or [] if str(item).strip()]
    if accepted_templates and template_id not in accepted_templates:
        return False
    accepted_capabilities = [str(item).strip() for item in spec.get("acceptedCapabilities") or [] if str(item).strip()]
    if accepted_capabilities:
        capabilities = [
            str(item).strip()
            for item in metadata.get("capabilities") or DATABASE_TEMPLATES.get(template_id, {}).get("capabilities") or []
            if str(item).strip()
        ]
        if not any(capability in capabilities for capability in accepted_capabilities):
            return False
    return True


def _smoke_timeout(tool: dict[str, Any]) -> int:
    raw = _smoke_test(tool).get("timeoutSeconds")
    try:
        return max(1, min(int(raw or 600), 3600))
    except (TypeError, ValueError):
        return 600


def _set_status(
    status: dict[str, dict[str, str]],
    key: str,
    result: str,
    code: str,
    message: str,
    *,
    run_id: str = "",
    log_path: str = "",
    details: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    item = {
        "status": result,
        "message": message,
        "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if code:
        item["code"] = code
    if run_id:
        item["runId"] = run_id
    if log_path:
        item["logPath"] = log_path
    if details:
        item.update({key: str(value) for key, value in details.items() if str(value)})
    status[key] = item
    return normalize_contract_status(status)


def _result(*, status: dict[str, dict[str, str]], ok: bool, message: str) -> dict[str, Any]:
    return {"ok": ok, "contractStatus": status, "message": message}


def _tail(text: str) -> str:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return "\n".join(lines[-20:]) if lines else ""


def _write_run_log(work_dir: Path, *, dry_run: bool, stdout: str, stderr: str) -> Path:
    log_dir = work_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / ("dry-run.log" if dry_run else "smoke-run.log")
    log_path.write_text(f"[stdout]\n{stdout}\n[stderr]\n{stderr}\n", encoding="utf-8")
    return log_path


def _safe_identifier(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._") or "tool"
