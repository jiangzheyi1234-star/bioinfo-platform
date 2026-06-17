from __future__ import annotations

from apps.api.tool_contract_resolver import ToolContractResolver
from apps.api.tool_profiles import known_tool_profile_ids


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


def test_bracken_profile_overlay_returns_workflow_rule_spec() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_dependency(
        {
            "name": "bracken",
            "source": "bioconda",
            "packageSpec": "bioconda::bracken=2.9",
            "latestVersion": "2.9",
        }
    )

    template = draft["ruleTemplate"]
    assert draft["source"] == "h2ometa-tool-profile"
    assert draft["contractSource"] == "h2ometa-tool-profile-registry"
    assert draft["status"] == "ready-for-validation"
    assert draft["requiresUserCompletion"] is False
    assert draft["lock"]["profileId"] == "bracken"
    assert draft["lock"]["packageSpec"] == "bioconda::bracken=3.1"
    assert template["resources"]["bracken_db"] == {
        "type": "database",
        "required": True,
        "acceptedTemplates": ["bracken"],
        "configKey": "bracken_db",
    }
    assert "{config.bracken_db:q}" in template["commandTemplate"]
    assert template["environment"]["conda"]["dependencies"] == ["bioconda::bracken=3.1"]
    assert template["smokeTest"]["inputs"]["kraken_report"]["filename"] == "kraken.report"
    assert template["smokeTest"]["params"] == {"read_length": 100, "level": "S"}


def test_profile_registry_exposes_p0_h2ometa_profiles() -> None:
    profile_ids = known_tool_profile_ids()

    assert len(profile_ids) >= 20
    assert {"bracken", "fastp", "fastqc", "kraken2", "multiqc", "seqkit-stats"}.issubset(profile_ids)


def test_fastp_profile_overlay_has_no_database_resource() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_dependency(
        {
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
        }
    )

    template = draft["ruleTemplate"]
    assert draft["source"] == "h2ometa-tool-profile"
    assert draft["lock"]["profileId"] == "fastp"
    assert draft["lock"]["wrapperIdentifier"] == "v9.8.0/bio/fastp"
    assert template["wrapper"] == "v9.8.0/bio/fastp"
    assert "commandTemplate" not in template
    assert template["inputs"] == [
        {
            "name": "sample",
            "type": "file",
            "kind": "sequence_reads",
            "mimeType": "text/plain",
            "required": True,
            "multiple": True,
            "data": "http://edamontology.org/data_2044",
            "format": "http://edamontology.org/format_1930",
        }
    ]
    assert set(template["outputs"][index]["name"] for index in range(len(template["outputs"]))) == {
        "trimmed",
        "html",
        "json",
    }
    assert "bracken_db" not in template["resources"]
    assert "kraken2_db" not in template["resources"]


def test_kraken2_profile_overlay_declares_database_resource() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_dependency(
        {
            "name": "kraken2",
            "source": "bioconda",
            "packageSpec": "bioconda::kraken2=2.1.3",
        }
    )

    template = draft["ruleTemplate"]
    assert draft["lock"]["profileId"] == "kraken2"
    assert template["resources"]["kraken2_db"] == {
        "type": "database",
        "required": True,
        "acceptedTemplates": ["kraken2"],
        "configKey": "kraken2_db",
    }
    assert "{config.kraken2_db:q}" in template["commandTemplate"]


def test_fastqc_profile_overlay_declares_report_outputs() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_dependency(
        {
            "name": "fastqc",
            "source": "bioconda",
            "packageSpec": "bioconda::fastqc=0.12.1",
        }
    )

    template = draft["ruleTemplate"]
    assert draft["source"] == "h2ometa-tool-profile"
    assert draft["lock"]["profileId"] == "fastqc"
    assert draft["lock"]["wrapperIdentifier"] == "v9.8.0/bio/fastqc"
    assert template["wrapper"] == "v9.8.0/bio/fastqc"
    assert "commandTemplate" not in template
    assert {output["name"] for output in template["outputs"]} == {"html", "zip"}
    assert template["outputs"][0]["path"] == "results/reads_fastqc.html"
    assert template["smokeTest"]["inputs"]["reads"]["filename"] == "reads.fastq"


def test_multiqc_profile_overlay_declares_report_output() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_dependency(
        {
            "name": "multiqc",
            "source": "bioconda",
            "packageSpec": "bioconda::multiqc=1.25",
        }
    )

    template = draft["ruleTemplate"]
    assert draft["source"] == "h2ometa-tool-profile"
    assert draft["lock"]["profileId"] == "multiqc"
    assert draft["lock"]["wrapperIdentifier"] == "v9.8.0/bio/multiqc"
    assert template["wrapper"] == "v9.8.0/bio/multiqc"
    assert "commandTemplate" not in template
    assert template["outputs"] == [
        {
            "name": "report",
            "path": "results/multiqc.html",
            "kind": "report",
            "mimeType": "text/html",
            "format": "http://edamontology.org/format_2331",
        }
    ]
    assert template["smokeTest"]["inputs"]["fastqc_data"]["filename"] == "fastqc_data.txt"


def test_seqkit_stats_profile_overlay_declares_locked_generic_wrapper() -> None:
    resolver = ToolContractResolver()

    draft = resolver.resolve_dependency(
        {
            "name": "seqkit",
            "source": "bioconda",
            "packageSpec": "bioconda::seqkit=2.13.0",
        }
    )

    template = draft["ruleTemplate"]
    assert draft["source"] == "h2ometa-tool-profile"
    assert draft["lock"]["profileId"] == "seqkit-stats"
    assert draft["lock"]["wrapperIdentifier"] == "v9.8.0/bio/seqkit"
    assert template["wrapper"] == "v9.8.0/bio/seqkit"
    assert template["inputs"] == [
        {
            "name": "fastx",
            "type": "file",
            "kind": "sequence_reads",
            "mimeType": "text/plain",
            "required": True,
            "data": "http://edamontology.org/data_2044",
            "format": "http://edamontology.org/format_1930",
        }
    ]
    assert template["outputs"] == [
        {
            "name": "stats",
            "path": "results/seqkit-stats.tsv",
            "kind": "sequence_stats",
            "mimeType": "text/tab-separated-values",
        }
    ]
    assert template["params"] == {
        "command": {"type": "string", "title": "SeqKit command", "default": "stats", "const": "stats"},
        "extra": {"type": "string", "title": "Extra seqkit stats arguments", "default": "--all --tabular"},
    }
    assert template["environment"]["conda"]["dependencies"] == ["bioconda::seqkit=2.13.0"]
    assert template["smokeTest"]["inputs"]["fastx"]["filename"] == "reads.fastq"
    assert template["smokeTest"]["params"] == {"command": "stats", "extra": "--all --tabular"}
