from __future__ import annotations

import pytest


def test_profile_prepare_payload_locks_package_version_from_profile_contract(monkeypatch) -> None:
    from apps.api import tool_profile_prepare_payload
    from apps.api.tool_profile_registry import TOOL_PROFILES

    fastqc_profile = next(profile for profile in TOOL_PROFILES if profile.profile_id == "fastqc")
    monkeypatch.setattr(
        tool_profile_prepare_payload,
        "profile_snakemake_wrappers",
        lambda profile: [
            {
                "wrapperPath": "bio/fastqc",
                "wrapperIdentifier": "v9.8.0/bio/fastqc",
                "wrapperContractHints": {
                    "environment": {
                        "conda": {
                            "channels": ["conda-forge", "bioconda", "nodefaults"],
                            "dependencies": ["fastqc =0.12.1", "snakemake-wrapper-utils =0.8.0"],
                        }
                    }
                },
            }
        ],
    )

    payload = tool_profile_prepare_payload.profile_prepare_payload(fastqc_profile)

    assert payload["id"] == "bioconda::fastqc"
    assert payload["source"] == "bioconda"
    assert payload["packageName"] == "fastqc"
    assert payload["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert payload["version"] == "0.12.1"
    assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert payload["ruleTemplate"]["environment"]["conda"]["dependencies"] == [
        "bioconda::fastqc=0.12.1"
    ]


def test_profile_prepare_payload_does_not_let_wrapper_hints_override_profile_lock(monkeypatch) -> None:
    from apps.api import tool_profile_prepare_payload
    from apps.api.tool_profile_registry import TOOL_PROFILES

    fastqc_profile = next(profile for profile in TOOL_PROFILES if profile.profile_id == "fastqc")
    monkeypatch.setattr(
        tool_profile_prepare_payload,
        "profile_snakemake_wrappers",
        lambda profile: [
            {
                "wrapperPath": "bio/fastqc",
                "wrapperIdentifier": "v9.8.0/bio/fastqc",
                "wrapperContractHints": {
                    "environment": {
                        "conda": {
                            "channels": ["conda-forge", "nodefaults"],
                            "dependencies": ["conda-forge::fastqc =9.9.9"],
                        }
                    }
                },
            }
        ],
    )

    payload = tool_profile_prepare_payload.profile_prepare_payload(fastqc_profile)

    assert payload["source"] == "bioconda"
    assert payload["sourceLabel"] == "Bioconda"
    assert payload["id"] == "bioconda::fastqc"
    assert payload["packageSpec"] == "bioconda::fastqc=0.12.1"


def test_profile_prepare_payload_uses_profile_id_for_tool_identity() -> None:
    from apps.api import tool_profile_prepare_payload
    from apps.api.tool_profile_registry import TOOL_PROFILES

    profile = next(profile for profile in TOOL_PROFILES if profile.profile_id == "samtools-sort")

    payload = tool_profile_prepare_payload.profile_prepare_payload(profile)

    assert payload["id"] == "bioconda::samtools-sort"
    assert payload["name"] == "samtools-sort"
    assert payload["profileId"] == "samtools-sort"
    assert payload["validationTarget"] == "samtools-sort"
    assert payload["packageName"] == "samtools"
    assert payload["packageSpec"] == "bioconda::samtools=1.23.1"
    assert payload["ruleSpecDraft"]["lock"]["profileId"] == "samtools-sort"
    assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::samtools=1.23.1"


def test_profile_prepare_payload_requires_exact_profile_package_version() -> None:
    from apps.api.tool_profile_model import ToolProfile
    from apps.api.tool_profile_prepare_payload import profile_prepare_payload

    profile = ToolProfile(
        profile_id="kraken2",
        version=1,
        tool_names=("kraken2",),
        package_name="kraken2",
        package_source="bioconda",
        rule_template={
            "commandTemplate": "kraken2 {input.reads:q} > {output.report:q}",
            "inputs": [{"name": "reads", "type": "file"}],
            "outputs": [{"name": "report", "path": "results/kraken2.report"}],
            "environment": {"conda": {"dependencies": ["{packageSpec}"]}},
        },
    )

    with pytest.raises(ValueError, match="BIO_TOOL_PROFILE_PACKAGE_VERSION_REQUIRED"):
        profile_prepare_payload(profile)


def test_qiime2_profile_uses_qiime2_package_source() -> None:
    from apps.api.tool_profile_prepare_payload import profile_prepare_payload
    from apps.api.tool_profile_registry import TOOL_PROFILES

    profile = next(profile for profile in TOOL_PROFILES if profile.profile_id == "qiime2-classify-sklearn")
    payload = profile_prepare_payload(profile)

    assert payload["id"] == "qiime2::qiime2-classify-sklearn"
    assert payload["source"] == "qiime2"
    assert payload["packageName"] == "q2-feature-classifier"
    assert payload["packageSpec"] == "qiime2::q2-feature-classifier=2024.10.0"
    assert payload["ruleTemplate"]["environment"]["conda"]["channels"] == [
        "qiime2",
        "conda-forge",
        "bioconda",
    ]
    assert payload["ruleTemplate"]["environment"]["conda"]["dependencies"] == [
        "qiime2::q2-feature-classifier=2024.10.0",
        "qiime2::qiime2=2024.10.0",
        "qiime2::q2cli=2024.10.0",
        "conda-forge::click=8.1.7",
        "conda-forge::setuptools=80.9.0",
    ]
