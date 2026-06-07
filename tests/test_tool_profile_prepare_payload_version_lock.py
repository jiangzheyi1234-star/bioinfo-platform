from __future__ import annotations


def test_profile_prepare_payload_locks_package_version_from_wrapper_hints(monkeypatch) -> None:
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
    assert payload["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert payload["version"] == "0.12.1"
    assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert payload["ruleTemplate"]["environment"]["conda"]["dependencies"] == [
        "bioconda::fastqc=0.12.1"
    ]


def test_profile_prepare_payload_labels_conda_forge_dependency(monkeypatch) -> None:
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
                            "dependencies": ["conda-forge::fastqc =0.12.1"],
                        }
                    }
                },
            }
        ],
    )

    payload = tool_profile_prepare_payload.profile_prepare_payload(fastqc_profile)

    assert payload["source"] == "conda-forge"
    assert payload["sourceLabel"] == "conda-forge"
    assert payload["id"] == "conda-forge::fastqc"
    assert payload["packageSpec"] == "conda-forge::fastqc=0.12.1"


def test_profile_prepare_payload_locks_package_version_from_bioconda_index(monkeypatch) -> None:
    from apps.api import tool_profile_prepare_payload
    from apps.api.tool_profile_model import ToolProfile

    profile = ToolProfile(
        profile_id="kraken2",
        version=1,
        tool_names=("kraken2",),
        rule_template={
            "commandTemplate": "kraken2 {input.reads:q} > {output.report:q}",
            "inputs": [{"name": "reads", "type": "file"}],
            "outputs": [{"name": "report", "path": "results/kraken2.report"}],
            "environment": {"conda": {"dependencies": ["{packageSpec}"]}},
        },
    )
    monkeypatch.setattr(tool_profile_prepare_payload, "profile_snakemake_wrappers", lambda profile: [])
    monkeypatch.setattr(
        tool_profile_prepare_payload,
        "search_bioconda_index_page",
        lambda query, *, page, page_size: {
            "items": [
                {"name": "kraken2-data", "latestVersion": "1.0", "platforms": ["linux-64"]},
                {"name": "kraken2", "latestVersion": "2.1.3", "platforms": ["linux-64"]},
            ],
            "total": 2,
            "indexAvailable": True,
        },
    )

    payload = tool_profile_prepare_payload.profile_prepare_payload(profile)

    assert payload["id"] == "bioconda::kraken2"
    assert payload["packageSpec"] == "bioconda::kraken2=2.1.3"
    assert payload["version"] == "2.1.3"
    assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::kraken2=2.1.3"
    assert payload["ruleTemplate"]["environment"]["conda"]["dependencies"] == [
        "bioconda::kraken2=2.1.3"
    ]


def test_profile_prepare_payload_does_not_lock_from_inexact_bioconda_index_result(monkeypatch) -> None:
    from apps.api import tool_profile_prepare_payload
    from apps.api.tool_profile_model import ToolProfile

    profile = ToolProfile(
        profile_id="kraken2",
        version=1,
        tool_names=("kraken2",),
        rule_template={"commandTemplate": "kraken2", "environment": {"conda": {"dependencies": ["{packageSpec}"]}}},
    )
    monkeypatch.setattr(tool_profile_prepare_payload, "profile_snakemake_wrappers", lambda profile: [])
    monkeypatch.setattr(
        tool_profile_prepare_payload,
        "search_bioconda_index_page",
        lambda query, *, page, page_size: {
            "items": [{"name": "kraken2-data", "latestVersion": "1.0", "platforms": ["linux-64"]}],
            "total": 1,
            "indexAvailable": True,
        },
    )

    payload = tool_profile_prepare_payload.profile_prepare_payload(profile)

    assert payload["packageSpec"] == "bioconda::kraken2"
    assert "version" not in payload
    assert payload["ruleSpecDraft"]["lock"]["packageSpec"] == "bioconda::kraken2"
