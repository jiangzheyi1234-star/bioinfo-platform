from __future__ import annotations

import os
import shlex
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.contracts.portable_relative_path import (
    portable_relative_path_alias_key,
    require_portable_relative_path,
)

from .rule_runtime import RuleRuntimeDirectives, runtime_log_parent_dirs


class RuleActionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RuleAssetPlanEntry:
    relative_path: str
    content: str
    path_error_code: str
    conflict_error_code: str


def rule_action_kind(rule_template: dict[str, Any]) -> str:
    if isinstance(rule_template.get("module"), dict) and rule_template["module"]:
        return "module"
    if str(rule_template.get("wrapper") or "").strip():
        return "wrapper"
    if str(rule_template.get("script") or "").strip():
        return "script"
    return "shell"


def materialize_rule_assets(
    *, rule_template: dict[str, Any], workflow_dir: Path
) -> None:
    materialize_rule_asset_plan(
        plan_rule_assets(rule_template), workflow_dir=workflow_dir
    )


def materialize_rule_script_assets(
    *, rule_template: dict[str, Any], workflow_dir: Path
) -> None:
    script = str(rule_template.get("script") or "").strip()
    if not script:
        return
    script = _require_asset_path(script, "TOOL_RULE_SCRIPT_ASSET_PATH_INVALID")
    materialize_rule_asset_plan(
        _plan_rule_asset_kind(
            raw_assets=rule_template.get("scriptAssets"),
            primary_path=script,
            asset_kind="SCRIPT",
        ),
        workflow_dir=workflow_dir,
    )


def materialize_rule_module_assets(
    *, rule_template: dict[str, Any], workflow_dir: Path
) -> None:
    module = rule_template.get("module")
    if not isinstance(module, dict) or not module:
        return
    snakefile = str(module.get("snakefile") or "").strip()
    snakefile = _require_asset_path(snakefile, "TOOL_RULE_MODULE_ASSET_PATH_INVALID")
    materialize_rule_asset_plan(
        _plan_rule_asset_kind(
            raw_assets=rule_template.get("moduleAssets"),
            primary_path=snakefile,
            asset_kind="MODULE",
        ),
        workflow_dir=workflow_dir,
    )


def plan_rule_assets(rule_template: dict[str, Any]) -> tuple[RuleAssetPlanEntry, ...]:
    """Validate one rule's complete asset declaration without writing files."""

    entries: list[RuleAssetPlanEntry] = []
    script = str(rule_template.get("script") or "").strip()
    if script:
        entries.extend(
            _plan_rule_asset_kind(
                raw_assets=rule_template.get("scriptAssets"),
                primary_path=_require_asset_path(
                    script, "TOOL_RULE_SCRIPT_ASSET_PATH_INVALID"
                ),
                asset_kind="SCRIPT",
            )
        )
    module = rule_template.get("module")
    if isinstance(module, dict) and module:
        entries.extend(
            _plan_rule_asset_kind(
                raw_assets=rule_template.get("moduleAssets"),
                primary_path=_require_asset_path(
                    str(module.get("snakefile") or "").strip(),
                    "TOOL_RULE_MODULE_ASSET_PATH_INVALID",
                ),
                asset_kind="MODULE",
            )
        )
    _require_nonoverlapping_asset_plan(entries)
    return tuple(entries)


def materialize_rule_asset_plan(
    entries: Sequence[RuleAssetPlanEntry],
    *,
    workflow_dir: Path,
) -> None:
    """Preflight the complete plan, then write its validated regular files."""

    planned = tuple(entries)
    _require_nonoverlapping_asset_plan(planned)
    for entry in planned:
        target = workflow_dir.joinpath(*entry.relative_path.split("/"))
        _require_asset_target_available(
            workflow_dir=workflow_dir,
            target=target,
            content=entry.content,
            conflict_code=entry.conflict_error_code,
            relative_path=entry.relative_path,
        )
    for entry in planned:
        target = workflow_dir.joinpath(*entry.relative_path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry.content, encoding="utf-8", newline="\n")


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
        + '        r"""\n'
        + "        set -euo pipefail\n"
        + f"{mkdir_lines}"
        + f"        {shell_command}\n"
        + '        """\n'
    )


def _require_asset_path(value: str, code: str) -> str:
    try:
        return require_portable_relative_path(value, error_code=code)
    except ValueError as exc:
        raise RuleActionError(code) from exc


def _plan_rule_asset_kind(
    *,
    raw_assets: object,
    primary_path: str,
    asset_kind: str,
) -> tuple[RuleAssetPlanEntry, ...]:
    required_code = f"TOOL_RULE_{asset_kind}_ASSET_REQUIRED"
    invalid_code = f"TOOL_RULE_{asset_kind}_ASSET_INVALID"
    path_code = f"TOOL_RULE_{asset_kind}_ASSET_PATH_INVALID"
    content_code = f"TOOL_RULE_{asset_kind}_ASSET_CONTENT_INVALID"
    conflict_code = f"TOOL_RULE_{asset_kind}_ASSET_CONFLICT"
    if not isinstance(raw_assets, list) or not raw_assets:
        raise RuleActionError(required_code)

    validated: list[RuleAssetPlanEntry] = []
    primary_seen = False
    for item in raw_assets:
        if not isinstance(item, dict):
            raise RuleActionError(invalid_code)
        path = _require_asset_path(str(item.get("path") or "").strip(), path_code)
        content = item.get("content")
        if not isinstance(content, str):
            raise RuleActionError(f"{content_code}: {path}")
        validated.append(
            RuleAssetPlanEntry(
                relative_path=path,
                content=content,
                path_error_code=path_code,
                conflict_error_code=conflict_code,
            )
        )
        primary_seen = primary_seen or path == primary_path

    if not primary_seen:
        raise RuleActionError(required_code)
    _require_nonoverlapping_asset_plan(validated)
    return tuple(validated)


def _require_nonoverlapping_asset_plan(
    entries: Sequence[RuleAssetPlanEntry],
) -> None:
    aliases: dict[tuple[str, ...], RuleAssetPlanEntry] = {}
    for entry in entries:
        alias = portable_relative_path_alias_key(entry.relative_path)
        previous = aliases.get(alias)
        if previous is not None:
            if (
                previous.relative_path == entry.relative_path
                and previous.content != entry.content
            ):
                raise RuleActionError(
                    f"{entry.conflict_error_code}: {entry.relative_path}"
                )
            raise RuleActionError(entry.path_error_code)
        if any(_path_aliases_overlap(alias, existing) for existing in aliases):
            raise RuleActionError(entry.path_error_code)
        aliases[alias] = entry


def _path_aliases_overlap(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> bool:
    shorter = min(len(left), len(right))
    return left[:shorter] == right[:shorter]


def _require_asset_target_available(
    *,
    workflow_dir: Path,
    target: Path,
    content: str,
    conflict_code: str,
    relative_path: str,
) -> None:
    cursor = workflow_dir
    if os.path.lexists(cursor):
        _require_regular_asset_directory(
            cursor,
            conflict_code=conflict_code,
            relative_path=relative_path,
        )
    for component in target.relative_to(workflow_dir).parts[:-1]:
        cursor /= component
        if os.path.lexists(cursor):
            _require_regular_asset_directory(
                cursor,
                conflict_code=conflict_code,
                relative_path=relative_path,
            )
    if not os.path.lexists(target):
        return
    status = os.lstat(target)
    if (
        not stat.S_ISREG(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or int(getattr(status, "st_file_attributes", 0)) & 0x400
        or status.st_nlink != 1
        or target.read_text(encoding="utf-8") != content
    ):
        raise RuleActionError(f"{conflict_code}: {relative_path}")


def _require_regular_asset_directory(
    path: Path,
    *,
    conflict_code: str,
    relative_path: str,
) -> None:
    status = os.lstat(path)
    if (
        not stat.S_ISDIR(status.st_mode)
        or stat.S_ISLNK(status.st_mode)
        or int(getattr(status, "st_file_attributes", 0)) & 0x400
    ):
        raise RuleActionError(f"{conflict_code}: {relative_path}")


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
