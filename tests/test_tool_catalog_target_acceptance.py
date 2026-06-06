from __future__ import annotations


def test_bio_agent_catalog_target_acceptance_reports_current_gates(monkeypatch) -> None:
    from apps.api import tool_candidate_target_acceptance

    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "total": 12884,
            "sourceCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 466,
                "toolProfiles": 20,
            },
            "addableDraftCounts": {
                "condaPackages": 12398,
                "snakemakeWrappers": 0,
                "toolProfiles": 20,
                "total": 12418,
            },
            "qualityCounts": {
                "discovered": 12884,
                "draftRunnable": 20,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "catalog_tool_profiles",
        lambda *, query, page, page_size: {
            "total": 20,
            "items": [{"contractState": "SnakemakeRenderable"} for _ in range(20)],
        },
    )

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(target_platform="linux-64")

    assert report["targetPlatform"] == "linux-64"
    assert report["complete"] is False
    assert report["targets"]["discovered"] == {
        "target": 500,
        "actual": 12884,
        "passed": True,
        "remaining": 0,
    }
    assert report["targets"]["addableDraft"] == {
        "target": 100,
        "actual": 12418,
        "passed": True,
        "remaining": 0,
    }
    assert report["targets"]["snakemakeRenderable"] == {
        "target": 20,
        "actual": 20,
        "passed": True,
        "remaining": 0,
    }
    assert report["targets"]["workflowReady"] == {
        "target": 30,
        "actual": 0,
        "passed": False,
        "remaining": 30,
    }
    assert report["targets"]["productionEnabled"] == {
        "target": 10,
        "actual": 0,
        "passed": False,
        "remaining": 10,
    }
    assert report["blockedTargets"] == ["workflowReady", "productionEnabled"]
    assert report["nextActions"] == [
        {
            "target": "workflowReady",
            "remaining": 30,
            "action": "prepare-and-validate-tool-contracts",
            "requiredState": "WorkflowReady",
            "evidence": "Snakemake dry-run, smoke run, and output validation evidence",
        },
        {
            "target": "productionEnabled",
            "remaining": 10,
            "action": "promote-workflow-ready-tools-with-production-evidence",
            "requiredState": "ProductionEnabled",
            "evidence": "Scoped production attestation for tool revision, platform, environment, data scope, and policy",
        },
    ]
    assert report["catalog"]["sourceCounts"]["snakemakeWrappers"] == 466
