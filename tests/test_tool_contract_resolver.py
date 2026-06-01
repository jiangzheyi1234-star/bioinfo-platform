from __future__ import annotations

from apps.api.tool_contract_resolver import ToolContractResolver


def test_unresolved_wrapper_contract_requires_editable_confirmation() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_snakemake_wrapper(
        wrapper_repository="snakemake/snakemake-wrappers",
        wrapper_ref="v9.8.0",
        wrapper_path="bio/samtools/sort",
        wrapper_identifier="v9.8.0/bio/samtools/sort",
    )

    assert draft["contractSource"] == "snakemake-wrapper-importer"
    assert draft["reason"] == "WRAPPER_CONTRACT_UNRESOLVED"
    assert draft["requiresUserCompletion"] is True
    assert draft["status"] == "needs-user-completion"
    assert draft["lock"]["wrapperIdentifier"] == "v9.8.0/bio/samtools/sort"
    assert draft["ruleTemplate"] == {
        "source": "snakemake-wrapper",
        "wrapper": "v9.8.0/bio/samtools/sort",
    }


def test_wrapper_import_never_auto_confirms_rule_contracts() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_snakemake_wrapper(
        wrapper_repository="snakemake/snakemake-wrappers",
        wrapper_ref="v9.8.0",
        wrapper_path="bio/example/report",
        wrapper_identifier="v9.8.0/bio/example/report",
    )

    assert draft["contractSource"] == "snakemake-wrapper-importer"
    assert draft["requiresUserCompletion"] is True
    assert draft["reason"] == "WRAPPER_CONTRACT_UNRESOLVED"
    assert draft["ruleTemplate"] == {
        "source": "snakemake-wrapper",
        "wrapper": "v9.8.0/bio/example/report",
    }
