from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .rule_runtime import RuleRuntimeDirectives, runtime_log_parent_dirs


class RuleActionError(ValueError):
    pass


def rule_action_kind(rule_template: dict[str, Any]) -> str:
    if isinstance(rule_template.get("module"), dict) and rule_template["module"]:
        return "module"
    if str(rule_template.get("wrapper") or "").strip():
        return "wrapper"
    if str(rule_template.get("script") or "").strip():
        return "script"
    return "shell"


def materialize_rule_assets(*, rule_template: dict[str, Any], workflow_dir: Path) -> None:
    materialize_rule_script_assets(rule_template=rule_template, workflow_dir=workflow_dir)
    materialize_rule_module_assets(rule_template=rule_template, workflow_dir=workflow_dir)


def materialize_rule_script_assets(*, rule_template: dict[str, Any], workflow_dir: Path) -> None:
    script = str(rule_template.get("script") or "").strip()
    if not script:
        return
    raw_assets = rule_template.get("scriptAssets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise RuleActionError("TOOL_RULE_SCRIPT_ASSET_REQUIRED")
    seen_script = False
    for item in raw_assets:
        if not isinstance(item, dict):
            raise RuleActionError("TOOL_RULE_SCRIPT_ASSET_INVALID")
        path = str(item.get("path") or "").strip().replace("\\", "/")
        content = item.get("content")
        if not path or Path(path).is_absolute() or any(part in {"", ".", ".."} for part in Path(path).parts):
            raise RuleActionError("TOOL_RULE_SCRIPT_ASSET_PATH_INVALID")
        if not isinstance(content, str):
            raise RuleActionError(f"TOOL_RULE_SCRIPT_ASSET_CONTENT_INVALID: {path}")
        target = workflow_dir / path
        if target.exists() and target.read_text(encoding="utf-8") != content:
            raise RuleActionError(f"TOOL_RULE_SCRIPT_ASSET_CONFLICT: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        seen_script = seen_script or path == script
    if not seen_script:
        raise RuleActionError("TOOL_RULE_SCRIPT_ASSET_REQUIRED")


def materialize_rule_module_assets(*, rule_template: dict[str, Any], workflow_dir: Path) -> None:
    module = rule_template.get("module")
    if not isinstance(module, dict) or not module:
        return
    snakefile = str(module.get("snakefile") or "").strip()
    raw_assets = rule_template.get("moduleAssets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise RuleActionError("TOOL_RULE_MODULE_ASSET_REQUIRED")
    seen_snakefile = False
    for item in raw_assets:
        if not isinstance(item, dict):
            raise RuleActionError("TOOL_RULE_MODULE_ASSET_INVALID")
        path = str(item.get("path") or "").strip().replace("\\", "/")
        content = item.get("content")
        if not path or Path(path).is_absolute() or any(part in {"", ".", ".."} for part in Path(path).parts):
            raise RuleActionError("TOOL_RULE_MODULE_ASSET_PATH_INVALID")
        if not isinstance(content, str):
            raise RuleActionError(f"TOOL_RULE_MODULE_ASSET_CONTENT_INVALID: {path}")
        target = workflow_dir / path
        if target.exists() and target.read_text(encoding="utf-8") != content:
            raise RuleActionError(f"TOOL_RULE_MODULE_ASSET_CONFLICT: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        seen_snakefile = seen_snakefile or path == snakefile
    if not seen_snakefile:
        raise RuleActionError("TOOL_RULE_MODULE_ASSET_REQUIRED")


def render_rule_action_lines(
    *,
    rule_template: dict[str, Any],
    env_path: Path,
    output_dir: str,
    runtime: RuleRuntimeDirectives,
    output_parent_dirs: list[str] | None = None,
    shell_command: str,
) -> str:
    wrapper = str(rule_template.get("wrapper") or "").strip()
    if wrapper:
        return f"    wrapper:\n        {wrapper!r}\n"

    conda_lines = f"    conda:\n        {env_path.as_posix()!r}\n"
    script = str(rule_template.get("script") or "").strip()
    if script:
        return conda_lines + f"    script:\n        {script!r}\n"

    mkdir_lines = _mkdir_lines(
        [output_dir, *runtime_log_parent_dirs(runtime), *(output_parent_dirs or [])]
    )
    return (
        conda_lines
        + "    shell:\n"
        + "        r\"\"\"\n"
        + "        set -euo pipefail\n"
        + f"{mkdir_lines}"
        + f"        {shell_command}\n"
        + "        \"\"\"\n"
    )


def _mkdir_lines(paths: list[str]) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for value in paths:
        path = str(value or "").strip()
        if not path or path == "." or path in seen:
            continue
        seen.add(path)
        lines.append(f"        mkdir -p {shlex.quote(path)}\n")
    return "".join(lines)
