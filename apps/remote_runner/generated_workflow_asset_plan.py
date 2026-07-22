"""Whole-workflow file planning before any generated asset is materialized."""

from __future__ import annotations

from dataclasses import dataclass

from core.contracts.portable_relative_path import (
    portable_relative_path_alias_key,
    require_portable_relative_path,
)

from .generated_workflow_plan import GeneratedWorkflowStepPlan
from .rule_action import (
    RuleActionError,
    RuleAssetPlanEntry,
    plan_rule_assets,
)
from .rule_environment import render_rule_conda_env_yaml


_GENERATED_SNAKEFILE = "Snakefile"


@dataclass(frozen=True, slots=True)
class _PathClaim:
    relative_path: str
    content: str | None
    is_rule_asset: bool


def plan_generated_workflow_files(
    steps: list[GeneratedWorkflowStepPlan],
) -> tuple[RuleAssetPlanEntry, ...]:
    """Bind reserved names, every env, and every step asset in one registry."""

    claims: dict[tuple[str, ...], _PathClaim] = {
        portable_relative_path_alias_key(_GENERATED_SNAKEFILE): _PathClaim(
            relative_path=_GENERATED_SNAKEFILE,
            content=None,
            is_rule_asset=False,
        )
    }
    planned: list[RuleAssetPlanEntry] = []
    for step in steps:
        env_path = require_portable_relative_path(
            step.env_path.as_posix(),
            error_code="GENERATED_WORKFLOW_ENV_PATH_INVALID",
        )
        env_entry = RuleAssetPlanEntry(
            relative_path=env_path,
            content=render_rule_conda_env_yaml(
                rule_template=step.rule_template,
                source=str(step.tool.get("source") or ""),
                package_spec=str(step.tool.get("packageSpec") or "").strip(),
            ),
            path_error_code="GENERATED_WORKFLOW_ENV_PATH_INVALID",
            conflict_error_code="GENERATED_WORKFLOW_ENV_CONFLICT",
        )
        _register_path_claim(claims, env_entry, is_rule_asset=False)
        planned.append(env_entry)
        for entry in plan_rule_assets(step.rule_template):
            _register_path_claim(claims, entry, is_rule_asset=True)
            planned.append(entry)
    return tuple(planned)


def _register_path_claim(
    claims: dict[tuple[str, ...], _PathClaim],
    entry: RuleAssetPlanEntry,
    *,
    is_rule_asset: bool,
) -> None:
    alias = portable_relative_path_alias_key(entry.relative_path)
    previous = claims.get(alias)
    if previous is not None:
        if (
            previous.relative_path == entry.relative_path
            and previous.is_rule_asset
            and is_rule_asset
            and previous.content is not None
            and previous.content != entry.content
        ):
            raise RuleActionError(f"{entry.conflict_error_code}: {entry.relative_path}")
        raise RuleActionError(entry.path_error_code)
    for existing_alias in claims:
        shorter = min(len(alias), len(existing_alias))
        if alias[:shorter] == existing_alias[:shorter]:
            raise RuleActionError(entry.path_error_code)
    claims[alias] = _PathClaim(
        entry.relative_path,
        entry.content,
        is_rule_asset,
    )


__all__ = ["plan_generated_workflow_files"]
