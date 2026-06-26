from __future__ import annotations

from typing import Any

from apps.remote_runner.rule_partial_rerun_claim_preflight import build_rule_partial_rerun_claim_binding


def rule_partial_rerun_execution_options(
    *,
    source_plan_hash: str = "b" * 64,
    output_key: str = "summary",
    target_output_keys: list[str] | None = None,
    forcerun_rules: list[str] | None = None,
    finalize_run: bool = False,
    include_outputs: bool = True,
) -> dict[str, Any]:
    output_keys = [output_key]
    scope: dict[str, Any] = {
        "schemaVersion": "rule-output-adoption-scope.v1",
        "mode": "rule-partial-rerun",
        "sourcePlanHash": source_plan_hash,
        "scopeSource": "ruleCacheRestorePlan.outputs",
        "outputCount": len(output_keys),
        "outputKeys": output_keys,
        "targetOutputKeys": target_output_keys if target_output_keys is not None else list(output_keys),
        "finalizeRunOnAdoption": finalize_run,
        "pathExposed": False,
        "storageUriExposed": False,
    }
    if include_outputs:
        scope["outputs"] = [
            {
                "outputKey": output_key,
                "stepId": "align",
                "outputOrdinal": 1,
                "invalidationRole": "selected",
                "cacheHit": True,
            }
        ]
    options = {
        "schemaVersion": "run-job-execution-options.v1",
        "snakemake": {
            "schemaVersion": "snakemake-rule-rerun-options.v1",
            "rerunIncomplete": True,
            "forcerunRules": forcerun_rules if forcerun_rules is not None else ["align"],
        },
        "outputAdoptionScope": scope,
    }
    return bind_rule_partial_rerun_options(options)


def bind_rule_partial_rerun_options(options: dict[str, Any]) -> dict[str, Any]:
    options["rulePartialRerunClaimBinding"] = build_rule_partial_rerun_claim_binding(
        options["outputAdoptionScope"]
    )
    return options
