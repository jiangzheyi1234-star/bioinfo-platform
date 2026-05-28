from __future__ import annotations

import shlex
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


RuleScalar = str | int | float
_MISSING = object()
RUNTIME_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class RuleRuntimeDirectives:
    threads: int | None
    resources: dict[str, RuleScalar]
    log: str | dict[str, str]


def resolve_rule_runtime_directives(
    *,
    rule_template: dict[str, Any],
    requested_step: dict[str, Any] | None = None,
    result_dir: Path,
    output_prefix: str = "",
) -> RuleRuntimeDirectives:
    override = _step_runtime_override(requested_step or {})
    threads = _optional_int(rule_template.get("threads"))
    if "threads" in override:
        threads = _required_positive_int(override.get("threads"), error_code="WORKFLOW_STEP_THREADS_INVALID")
    resources = dict(rule_template.get("schedulerResources") or {})
    raw_resources = override.get("resources", override.get("schedulerResources", _MISSING))
    if raw_resources is not _MISSING:
        resources.update(_runtime_resources(raw_resources))
    log_raw = override["log"] if "log" in override else rule_template.get("log")
    return RuleRuntimeDirectives(
        threads=threads,
        resources=resources,
        log=_resolve_log_paths(
            log_raw,
            result_dir=result_dir,
            output_prefix=output_prefix,
            invalid_error="WORKFLOW_STEP_LOG_INVALID" if "log" in override else "",
        ),
    )


def runtime_config(runtime: RuleRuntimeDirectives) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if runtime.threads is not None:
        config["threads"] = runtime.threads
    if runtime.resources:
        config["resources"] = dict(runtime.resources)
    if runtime.log:
        config["log"] = runtime.log
    return config


def render_runtime_directives(runtime: RuleRuntimeDirectives) -> str:
    lines: list[str] = []
    if runtime.threads is not None:
        lines.append(f"    threads: {runtime.threads}\n")
    if runtime.resources:
        lines.append("    resources:\n")
        for name, value in runtime.resources.items():
            lines.append(f"        {name}={value!r},\n")
    if isinstance(runtime.log, str) and runtime.log:
        lines.append("    log:\n")
        lines.append(f"        {runtime.log!r}\n")
    elif isinstance(runtime.log, dict) and runtime.log:
        lines.append("    log:\n")
        for name, path in runtime.log.items():
            lines.append(f"        {name}={path!r},\n")
    return "".join(lines)


def runtime_command_replacements(runtime: RuleRuntimeDirectives) -> dict[str, str]:
    replacements: dict[str, str] = {}
    if runtime.threads is not None:
        replacements["{threads}"] = str(runtime.threads)
        replacements["{threads:q}"] = shlex.quote(str(runtime.threads))
    for name, value in runtime.resources.items():
        rendered = shlex.quote(str(value))
        replacements[f"{{resources.{name}}}"] = rendered
        replacements[f"{{resources.{name}:q}}"] = rendered
    if isinstance(runtime.log, str) and runtime.log:
        rendered = shlex.quote(runtime.log)
        replacements["{log}"] = rendered
        replacements["{log:q}"] = rendered
    elif isinstance(runtime.log, dict) and runtime.log:
        first = next(iter(runtime.log.values()))
        replacements["{log}"] = shlex.quote(first)
        replacements["{log:q}"] = shlex.quote(first)
        for name, path in runtime.log.items():
            rendered = shlex.quote(path)
            replacements[f"{{log.{name}}}"] = rendered
            replacements[f"{{log.{name}:q}}"] = rendered
    return replacements


def runtime_log_parent_dirs(runtime: RuleRuntimeDirectives) -> list[str]:
    paths = [runtime.log] if isinstance(runtime.log, str) else list((runtime.log or {}).values())
    parents = sorted({str(Path(path).parent) for path in paths if path and str(Path(path).parent) != "."})
    return parents


def _step_runtime_override(requested_step: dict[str, Any]) -> dict[str, Any]:
    raw = requested_step.get("runtime")
    if raw in (None, {}):
        override: dict[str, Any] = {}
    elif isinstance(raw, dict):
        override = dict(raw)
    else:
        raise ValueError("WORKFLOW_STEP_RUNTIME_INVALID")
    for key in ["threads", "schedulerResources", "log"]:
        if key in requested_step and key not in override:
            override[key] = requested_step[key]
    return override


def _runtime_resources(raw: Any) -> dict[str, RuleScalar]:
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("WORKFLOW_STEP_RESOURCES_INVALID")
    resources: dict[str, RuleScalar] = {}
    for key, value in raw.items():
        name = str(key or "").strip()
        if not name or not RUNTIME_NAME_RE.match(name):
            raise ValueError("WORKFLOW_STEP_RESOURCE_KEY_INVALID")
        if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value == "":
            raise ValueError(f"WORKFLOW_STEP_RESOURCE_VALUE_INVALID: {name}")
        resources[name] = value
    return resources


def _resolve_log_paths(raw: Any, *, result_dir: Path, output_prefix: str, invalid_error: str = "") -> str | dict[str, str]:
    if raw in (None, "", {}):
        return ""
    if isinstance(raw, str):
        return str(result_dir / _prefixed_relative_path(raw, output_prefix=output_prefix))
    if isinstance(raw, dict):
        return {
            str(name): str(result_dir / _prefixed_relative_path(str(path), output_prefix=output_prefix))
            for name, path in raw.items()
            if str(name).strip() and str(path).strip()
        }
    if invalid_error:
        raise ValueError(invalid_error)
    return ""


def _prefixed_relative_path(value: str, *, output_prefix: str) -> Path:
    path = _safe_relative_path(value)
    if not output_prefix:
        return path
    if path.parent != Path("."):
        return Path(path.parent, f"{output_prefix}-{path.name}")
    return Path(f"{output_prefix}-{path.name}")


def _safe_relative_path(value: str) -> Path:
    posix_path = PurePosixPath(value.replace("\\", "/"))
    if Path(value).is_absolute() or posix_path.is_absolute() or any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ValueError("TOOL_RULE_LOG_PATH_INVALID")
    return Path(*posix_path.parts)


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _required_positive_int(value: Any, *, error_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(error_code)
    return value
