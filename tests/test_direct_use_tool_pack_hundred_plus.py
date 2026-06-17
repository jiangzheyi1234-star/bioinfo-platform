from __future__ import annotations


def test_unified_tool_candidate_catalog_pages_hundred_plus_builtin_profiles(
    monkeypatch,
) -> None:
    from apps.api import tool_candidate_catalog
    from apps.api.tool_profile_prepare_payload import profile_prepare_payload
    from apps.api.tool_profile_sources import all_tool_profiles

    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_conda_package_candidates",
        lambda *, query, target_platform, page, page_size: {
            "items": [],
            "total": 0,
            "addableTotal": 0,
            "hasMore": False,
            "qualityCounts": {
                "discovered": 0,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    monkeypatch.setattr(
        tool_candidate_catalog,
        "catalog_snakemake_wrappers",
        lambda *, query, page, page_size: {
            "items": [],
            "total": 0,
            "addableTotal": 0,
            "hasMore": False,
            "qualityCounts": {
                "discovered": 0,
                "draftRunnable": 0,
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )

    first_page = tool_candidate_catalog.search_tool_candidates("", page=1, page_size=50)
    second_page = tool_candidate_catalog.search_tool_candidates(
        "", page=2, page_size=50
    )
    profiles_by_id = {profile.profile_id: profile for profile in all_tool_profiles()}

    assert first_page["sourceCounts"]["toolProfiles"] == len(profiles_by_id) >= 100
    assert first_page["addableDraftCounts"]["toolProfiles"] == len(profiles_by_id)
    assert first_page["qualityCounts"]["draftRunnable"] >= 100
    assert len(first_page["items"]) == 50
    assert len(second_page["items"]) == 50
    assert all(
        item["candidateKind"] == "h2ometa-tool-profile"
        for item in [*first_page["items"], *second_page["items"]]
    )
    for item in [*first_page["items"], *second_page["items"]]:
        profile_id = item["profileId"]
        expected_payload = profile_prepare_payload(profiles_by_id[profile_id])
        assert item["candidateId"] == f"h2ometa-tool-profile::{profile_id}"
        assert item["preparePayload"]["validationTarget"] == profile_id
        assert (
            item["preparePayload"]["ruleSpecDraft"]["requiresUserCompletion"] is False
        )
        assert item["preparePayload"]["id"] == expected_payload["id"]


def test_validation_queue_exposes_hundred_plus_builtin_profile_payloads(
    monkeypatch,
) -> None:
    from apps.api import tool_candidate_target_acceptance
    from apps.api.tool_profile_prepare_payload import profile_prepare_payload
    from apps.api.tool_profile_sources import all_tool_profiles

    profiles = all_tool_profiles()
    expected_ids = [str(profile_prepare_payload(profile)["id"]) for profile in profiles]
    monkeypatch.setattr(
        tool_candidate_target_acceptance,
        "search_tool_candidates",
        lambda query, *, target_platform, page, page_size: {
            "items": [],
            "query": query,
            "total": len(profiles),
            "page": page,
            "pageSize": page_size,
            "hasMore": False,
            "sourceCounts": {
                "condaPackages": 0,
                "snakemakeWrappers": 0,
                "toolProfiles": len(profiles),
            },
            "addableDraftCounts": {
                "condaPackages": 0,
                "snakemakeWrappers": 0,
                "toolProfiles": len(profiles),
                "total": len(profiles),
            },
            "qualityCounts": {
                "discovered": len(profiles),
                "draftRunnable": len(profiles),
                "workflowReady": 0,
                "productionEnabled": 0,
            },
        },
    )
    queue_ids = tool_candidate_target_acceptance.validation_queue_tool_ids()

    report = tool_candidate_target_acceptance.bio_agent_catalog_target_acceptance(
        target_platform="linux-64"
    )
    queue = report["validationQueue"]

    assert len(profiles) >= 100
    assert report["targets"]["workflowReady"]["target"] == len(profiles)
    assert report["targets"]["snakemakeRenderable"]["target"] == len(profiles)
    assert len(queue_ids) == len(expected_ids)
    assert set(queue_ids) == set(expected_ids)
    assert queue["available"] >= 100
    assert queue["remaining"] == len(profiles)
    assert len(queue["items"]) == len(profiles)
    assert {item["profileId"] for item in queue["items"]} == {
        profile.profile_id for profile in profiles
    }
    for item in queue["items"]:
        assert item["currentState"] == "SnakemakeRenderable"
        assert item["requiredState"] == "WorkflowReady"
        assert item["action"] in {"prepare-tool", "wait-for-tool-validation"}
        if "preparePayload" in item:
            assert item["preparePayload"]["validationTarget"] == item["profileId"]


def test_index_profiles_expose_real_directory_artifacts() -> None:
    from apps.api.tool_profile_sources import all_tool_profiles

    profiles = {profile.profile_id: profile for profile in all_tool_profiles()}

    for profile_id in ["bwa-index", "bowtie2-build"]:
        output = profiles[profile_id].rule_template["outputs"][0]
        assert output["name"] == "index"
        assert output["directory"] is True
        assert output["mimeType"] == "inode/directory"
        assert output["path"].startswith("results/")


def test_direct_use_sequence_fixtures_are_long_enough_for_mash_default_k() -> None:
    from apps.api.tool_profile_sources import all_tool_profiles

    profiles = {profile.profile_id: profile for profile in all_tool_profiles()}
    smoke_input = profiles["mash-info"].rule_template["smokeTest"]["inputs"][
        "sequences"
    ]["content"]
    sequence = "".join(
        line.strip() for line in smoke_input.splitlines() if not line.startswith(">")
    )

    assert len(sequence) >= 21


def test_direct_use_alignment_fixture_has_multiple_sequences() -> None:
    from apps.api.tool_profile_sources import all_tool_profiles

    profiles = {profile.profile_id: profile for profile in all_tool_profiles()}
    smoke_input = profiles["clustalo-align"].rule_template["smokeTest"]["inputs"][
        "sequences"
    ]["content"]

    assert smoke_input.count(">") >= 2


def test_strict_priority_packages_use_conda_forge_source() -> None:
    from apps.api.tool_profile_sources import all_tool_profiles

    profiles = {profile.profile_id: profile for profile in all_tool_profiles()}

    assert profiles["csvtk-cut"].package_source == "conda-forge"
    assert profiles["mafft-align"].package_source == "conda-forge"


def test_specialized_gene_fixtures_are_not_generic_short_sequences() -> None:
    from apps.api.tool_profile_sources import all_tool_profiles

    profiles = {profile.profile_id: profile for profile in all_tool_profiles()}
    prodigal_input = profiles["prodigal-genes"].rule_template["smokeTest"][
        "inputs"
    ]["contigs"]["content"]
    trnascan_input = profiles["trnascan-se"].rule_template["smokeTest"]["inputs"][
        "contigs"
    ]["content"]

    assert "ATG" in prodigal_input and "TAA" in prodigal_input
    assert len(prodigal_input.replace("\n", "")) > 250
    assert "trna_candidate" in trnascan_input
