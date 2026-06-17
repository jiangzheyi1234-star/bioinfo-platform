from apps.api.tool_candidate_target_acceptance import _validation_evidence
from apps.api.tool_profile_prepare_payload import profile_prepare_payload
from apps.api.tool_profile_sources import all_tool_profiles


def test_gtdbtk_validation_queue_evidence_names_required_database_template() -> None:
    profile = next(profile for profile in all_tool_profiles() if profile.profile_id == "gtdbtk-classify")
    evidence = _validation_evidence(profile=profile, prepare_payload=profile_prepare_payload(profile))

    assert evidence["requiredResourceKeys"] == ["gtdbtk_db"]
    assert evidence["requiredResources"] == [
        {
            "resourceKey": "gtdbtk_db",
            "configKey": "gtdbtk_db",
            "type": "database",
            "acceptedTemplates": ["gtdbtk"],
            "acceptedCapabilities": [],
            "nextAction": "add-database",
        }
    ]
