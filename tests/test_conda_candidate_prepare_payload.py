from __future__ import annotations


def test_draft_runnable_conda_candidate_exposes_prepare_payload(monkeypatch) -> None:
    from apps.api import tool_candidate_catalog

    monkeypatch.setattr(tool_candidate_catalog, "find_snakemake_wrappers_for_tool", lambda name: [])
    monkeypatch.setattr(
        tool_candidate_catalog.DEFAULT_TOOL_CONTRACT_RESOLVER,
        "resolve_dependency",
        lambda hit, *, wrappers: {
            "source": "conda-package",
            "requiresUserCompletion": False,
            "ruleTemplate": {
                "commandTemplate": "fastqc {input.reads:q}",
                "inputs": [{"name": "reads", "type": "file", "kind": "sequence_reads"}],
                "outputs": [{"name": "html", "path": "results/fastqc.html", "kind": "report"}],
            },
        },
    )

    candidate = tool_candidate_catalog._conda_candidate_from_index_record(
        {
            "name": "fastqc",
            "summary": "Read QC",
            "latestVersion": "0.12.1",
            "versions": ["0.12.1"],
            "platforms": ["linux-64"],
        },
        target_platform="linux-64",
    )

    assert candidate["contractState"] == "SnakemakeRenderable"
    assert candidate["qualityTier"] == "draft-runnable"
    assert candidate["preparePayload"]["id"] == "bioconda::fastqc"
    assert candidate["preparePayload"]["packageSpec"] == "bioconda::fastqc=0.12.1"
    assert candidate["preparePayload"]["version"] == "0.12.1"
    assert candidate["preparePayload"]["ruleTemplate"] == candidate["ruleSpecDraft"]["ruleTemplate"]
    assert candidate["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is False
