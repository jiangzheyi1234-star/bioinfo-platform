from __future__ import annotations

from apps.remote_runner.tool_contract import build_tool_contract


def test_contract_without_saved_package_stays_discovered() -> None:
    contract = build_tool_contract(
        {
            "id": "discovered-only",
            "name": "discovered-only",
            "source": "conda-forge",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
        }
    )

    assert contract["requirements"]["packageSpecified"] is False
    assert contract["state"] == "Discovered"
    assert contract["workflowReady"] is False


def test_output_validated_contract_advances_to_explicit_workflow_ready_state() -> None:
    contract = build_tool_contract(
        {
            "id": "conda-forge::ready-tool",
            "name": "ready-tool",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/ready-tool.log",
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
            "contractStatus": {
                "dryRun": {"status": "passed"},
                "smokeRun": {"status": "passed"},
                "outputValidation": {"status": "passed"},
            },
        }
    )

    assert contract["requirements"]["smokeRunPassed"] is True
    assert contract["requirements"]["outputValidated"] is True
    assert contract["state"] == "WorkflowReady"
    assert contract["workflowReady"] is True


def test_contract_without_smoke_fixture_does_not_advance_past_dry_run() -> None:
    contract = build_tool_contract(
        {
            "id": "conda-forge::incomplete-ready-tool",
            "name": "incomplete-ready-tool",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/incomplete-ready-tool.log",
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
            },
            "contractStatus": {
                "dryRun": {"status": "passed"},
                "smokeRun": {"status": "passed"},
                "outputValidation": {"status": "passed"},
            },
        }
    )

    assert contract["requirements"]["smokeRunPassed"] is False
    assert contract["requirements"]["outputValidated"] is False
    assert contract["requirements"]["smokeTestSpecified"] is False
    assert contract["state"] == "DryRunPassed"
    assert contract["workflowReady"] is False


def test_contract_state_does_not_skip_validation_prerequisites() -> None:
    contract = build_tool_contract(
        {
            "id": "conda-forge::out-of-order-tool",
            "name": "out-of-order-tool",
            "source": "conda-forge",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "cp {input.primary:q} {output.report:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
                "params": {},
                "resources": {"threads": {"default": 1}, "mem_mb": {"default": 128}},
                "log": "logs/out-of-order-tool.log",
                "environment": {
                    "conda": {
                        "channels": ["conda-forge", "bioconda"],
                        "dependencies": ["conda-forge::coreutils=9.5"],
                    }
                },
                "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
            },
            "contractStatus": {
                "outputValidation": {"status": "passed"},
            },
        }
    )

    assert contract["requirements"]["smokeRunPassed"] is False
    assert contract["requirements"]["outputValidated"] is False
    assert contract["requirements"]["dryRunPassed"] is False
    assert contract["state"] == "SnakemakeRenderable"
    assert contract["workflowReady"] is False
