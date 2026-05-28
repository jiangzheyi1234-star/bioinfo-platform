from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


RuleScalar = str | int | float


@dataclass(frozen=True)
class RuleRuntimeDirectives:
    threads: int | None
    resources: dict[str, RuleScalar]
    log: str | dict[str, str]


def resolve_rule_runtime_directives(
    *,
    rule_template: dict[str, Any],
    result_dir: Path,
    output_prefix: str = "",
) -> RuleRuntimeDirectives:
    return RuleRuntimeDirectives(
        threads=_optional_int(rule_template.get("threads")),
        resources=dict(rule_template.get("schedulerResources") or {}),
        log=_resolve_log_paths(rule_template.get("log"), result_dir=result_dir, output_prefix=output_prefix),
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


def _resolve_log_paths(raw: Any, *, result_dir: Path, output_prefix: str) -> str | dict[str, str]:
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
