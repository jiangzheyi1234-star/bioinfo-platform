from __future__ import annotations


def test_wrapper_catalog_item_exposes_draft_payload_from_environment_hints(monkeypatch) -> None:
    from apps.api.snakemake_wrappers import catalog as snakemake_wrapper_catalog

    monkeypatch.setattr(
        snakemake_wrapper_catalog,
        "wrapper_index",
        lambda: {
            "fastqc": [
                {
                    "name": "fastqc",
                    "toolName": "fastqc",
                    "wrapperRepository": "snakemake/snakemake-wrappers",
                    "wrapperRef": "v9.8.0",
                    "wrapperPath": "bio/fastqc",
                    "wrapperIdentifier": "v9.8.0/bio/fastqc",
                    "wrapperUrl": "https://example.test/bio/fastqc",
                    "ruleSpecDraft": {
                        "source": "snakemake-wrapper",
                        "requiresUserCompletion": True,
                        "ruleTemplate": {
                            "source": "snakemake-wrapper",
                            "wrapper": "v9.8.0/bio/fastqc",
                        },
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        snakemake_wrapper_catalog,
        "wrapper_contract_hints",
        lambda wrapper_path: {
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda", "nodefaults"],
                    "dependencies": ["fastqc =0.12.1", "snakemake-wrapper-utils =0.8.0"],
                }
            }
        },
    )

    catalog = snakemake_wrapper_catalog.catalog_snakemake_wrappers(query="fastqc", page=1, page_size=10)

    item = catalog["items"][0]
    assert item["contractState"] == "Discovered"
    assert item["qualityTier"] == "discovered"
    assert item["preparePayload"]["id"] == "bioconda::fastqc"
    assert item["preparePayload"]["source"] == "bioconda"
    assert item["preparePayload"]["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert item["preparePayload"]["version"] == "0.12.1"
    assert item["preparePayload"]["ruleTemplate"]["wrapper"] == "v9.8.0/bio/fastqc"
    assert item["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is True
