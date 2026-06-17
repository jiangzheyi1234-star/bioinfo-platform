from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


from apps.api.tool_profiles import resolve_tool_profile
from apps.remote_runner.config import ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database, check_reference_database
from apps.remote_runner.storage import fetch_tool
from apps.remote_runner.storage import upsert_tool
from apps.remote_runner.tool_prepare_job_storage import (
    cancel_tool_prepare_job,
    complete_tool_prepare_job,
    create_tool_prepare_job,
    fail_tool_prepare_job,
    fetch_tool_prepare_job,
    mark_tool_prepare_job_waiting_resource,
    record_tool_prepare_job_event,
)
from apps.remote_runner.tool_prepare_jobs import run_tool_prepare_job
from apps.remote_runner.tool_preparation import validate_registered_tool_for_publish
from apps.remote_runner.tool_revisions import fetch_tool_revision, publish_tool_revision
from apps.remote_runner.tools import ToolRegistryError
from tests.test_tool_contract_pipeline import _cfg, _rule_contract_fields, _runtime_commands


def test_prepare_job_publish_validates_unsaved_candidate_before_persisting(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    snakemake_commands: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        snakemake_commands.append(list(cmd))
        if "-n" not in cmd:
            config_path = Path(cmd[cmd.index("--configfile") + 1])
            run_config = json.loads(config_path.read_text(encoding="utf-8"))
            assert run_config["tool"]["id"] == "conda-forge::prepare-unsaved"
            output = Path(run_config["outputs"]["report"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

    saved = _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::prepare-unsaved", "prepare-unsaved"))

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert fetch_tool(cfg, "conda-forge::prepare-unsaved")["contractStatus"]["smokeRun"]["status"] == "passed"
    assert any("-n" in cmd for cmd in snakemake_commands)
    assert any("-n" not in cmd for cmd in snakemake_commands)


def test_prepare_job_publish_does_not_persist_failed_validation(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)

    def fake_validation(_cfg, _tool):
        return {
            "ok": False,
            "message": "Smoke test input fixtures are required.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {
                    "status": "failed",
                    "code": "TOOL_RULE_SMOKE_TEST_REQUIRED",
                    "message": "Smoke test input fixtures are required.",
                },
                "outputValidation": {"status": "not_run", "message": ""},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    try:
        _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::prepare-fails", "prepare-fails"))
    except ToolRegistryError as exc:
        assert str(exc) == "TOOL_RULE_SMOKE_TEST_REQUIRED"
    else:
        raise AssertionError("failed prepare must raise and not persist the tool")

    assert fetch_tool(cfg, "conda-forge::prepare-fails") is None


def test_prepare_job_publish_persists_only_after_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)

    def fake_validation(_cfg, _tool):
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    saved = _publish_tool_candidate(cfg, _prepare_tool_payload("conda-forge::prepare-ready", "prepare-ready"))

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert fetch_tool(cfg, "conda-forge::prepare-ready")["contractStatus"]["outputValidation"]["status"] == "passed"


def test_prepare_job_publish_accepts_qiime2_source(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)

    def fake_validation(_cfg, _tool):
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    payload = _prepare_tool_payload("qiime2::q2-feature-classifier", "q2-feature-classifier")
    payload["source"] = "qiime2"
    payload["packageSpec"] = "qiime2::q2-feature-classifier=2024.10.0"
    payload["ruleTemplate"]["environment"]["conda"] = {
        "channels": ["qiime2", "conda-forge", "bioconda"],
        "dependencies": ["qiime2::q2-feature-classifier=2024.10.0"],
    }

    saved = _publish_tool_candidate(cfg, payload)

    assert saved["source"] == "qiime2"
    assert saved["packageSpec"] == "qiime2::q2-feature-classifier=2024.10.0"
    assert saved["toolContract"]["workflowReady"] is True


def test_h2ometa_profile_prepare_payload_publishes_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
            "latestVersion": "0.24.1",
        }
    )
    assert draft is not None

    def fake_validation(_cfg, tool):
        assert tool["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
        assert tool["ruleSpecDraft"]["requiresUserCompletion"] is False
        assert tool["ruleTemplate"]["wrapper"] == "v9.8.0/bio/fastp"
        assert tool["ruleTemplate"]["outputs"][0]["name"] == "trimmed"
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    saved = _publish_tool_candidate(
        cfg,
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "0.24.1",
            "packageSpec": "bioconda::fastp=0.24.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    assert saved["status"] == "published"
    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert saved["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
    assert fetch_tool(cfg, "bioconda::fastp")["toolContract"]["workflowReady"] is True


def test_h2ometa_profile_prepare_job_result_is_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "packageSpec": "bioconda::fastp=0.24.1",
            "latestVersion": "0.24.1",
        }
    )
    assert draft is not None

    def fake_validation(_cfg, tool, event_callback=None):
        assert tool["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
        assert tool["ruleSpecDraft"]["requiresUserCompletion"] is False
        if event_callback is not None:
            event_callback({"stage": "runtime_check", "message": "Workflow runtime check passed.", "level": "success"})
            event_callback({"stage": "dry_run", "message": "Snakemake dry-run passed.", "level": "success"})
            event_callback({"stage": "smoke_run", "message": "Snakemake smoke run passed.", "level": "success"})
            event_callback({"stage": "output_validation", "message": "Output validation passed.", "level": "success"})
        return {
            "ok": True,
            "message": "Tool contract validation passed.",
            "contractStatus": {
                "dryRun": {"status": "passed", "message": "dry-run passed"},
                "smokeRun": {"status": "passed", "message": "smoke passed"},
                "outputValidation": {"status": "passed", "message": "output passed"},
                "production": {"status": "not_run", "message": ""},
            },
        }

    monkeypatch.setattr("apps.remote_runner.tool_preparation.run_tool_contract_validation", fake_validation)

    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::fastp",
            "name": "fastp",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "0.24.1",
            "packageSpec": "bioconda::fastp=0.24.1",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["stage"] == "published"
    assert finished["result"]["toolContract"]["state"] == "WorkflowReady"
    assert finished["result"]["toolContract"]["workflowReady"] is True
    assert finished["result"]["ruleSpecDraft"]["source"] == "h2ometa-tool-profile"
    assert {event["stage"] for event in finished["events"]} >= {
        "validating_spec",
        "profile_schema_validation",
        "static_rulespec_validation",
        "environment_resolution",
        "runtime_check",
        "dry_run",
        "smoke_run",
        "output_validation",
        "published",
    }
    saved_tool = fetch_tool(cfg, "bioconda::fastp")
    assert saved_tool["toolContract"]["workflowReady"] is True
    assert saved_tool["validationSummary"]["latestResultId"] == finished["result"]["validationResultId"]
    assert saved_tool["validationSummary"]["evidenceId"] == finished["result"]["evidenceId"]
    revision = fetch_tool_revision(cfg, finished["result"]["toolRevisionId"])
    assert revision is not None
    assert revision["validationResultId"] == finished["result"]["validationResultId"]
    assert revision["evidenceId"] == finished["result"]["evidenceId"]
    assert revision["validationSummary"]["latestStatus"] == "succeeded"


def test_h2ometa_database_profile_prepare_auto_binds_single_matching_database(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    database_dir = tmp_path / "kraken2-db"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text("db\n", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "db_kraken2",
            "name": "Kraken2 smoke DB",
            "templateId": "kraken2",
            "path": str(database_dir),
        },
    )
    checked_database = check_reference_database(cfg, "db_kraken2")
    assert checked_database["status"] == "available"
    draft = resolve_tool_profile(
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "latestVersion": "2.1.3",
        }
    )
    assert draft is not None

    run_configs: list[dict[str, object]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        config_path = Path(cmd[cmd.index("--configfile") + 1])
        run_config = json.loads(config_path.read_text(encoding="utf-8"))
        run_configs.append(run_config)
        if "-n" not in cmd:
            for output_path in run_config["outputs"].values():
                output = Path(str(output_path))
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("ok\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

    saved = _publish_tool_candidate(
        cfg,
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "2.1.3",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    assert saved["toolContract"]["state"] == "WorkflowReady"
    assert saved["toolContract"]["workflowReady"] is True
    assert run_configs
    assert all(run_config["databases"]["kraken2_db"] == str(database_dir) for run_config in run_configs)
    assert all(run_config["resourceConfig"]["kraken2_db"] == str(database_dir) for run_config in run_configs)
    assert all(run_config["resources"]["kraken2_db"]["databaseId"] == "db_kraken2" for run_config in run_configs)


def test_h2ometa_seqkit_stats_profile_prepare_job_result_is_workflow_ready(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::seqkit",
            "name": "seqkit",
            "source": "bioconda",
            "packageSpec": "bioconda::seqkit=2.13.0",
            "latestVersion": "2.13.0",
        }
    )
    assert draft is not None

    run_configs: list[dict[str, object]] = []

    def fake_run(cmd, **_kwargs):
        if "--version" in cmd:
            return SimpleNamespace(returncode=0, stdout="9.19.0\n", stderr="")
        config_path = Path(cmd[cmd.index("--configfile") + 1])
        run_config = json.loads(config_path.read_text(encoding="utf-8"))
        run_configs.append(run_config)
        if "-n" not in cmd:
            output = Path(run_config["outputs"]["stats"])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("file\tformat\ttype\tnum_seqs\tsum_len\nreads.fastq\tFASTQ\tDNA\t1\t8\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr("apps.remote_runner.tool_contract_snakemake.subprocess.run", fake_run)

    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::seqkit",
            "name": "seqkit",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "2.13.0",
            "packageSpec": "bioconda::seqkit=2.13.0",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "succeeded"
    assert finished["stage"] == "published"
    assert finished["result"]["toolContract"]["state"] == "WorkflowReady"
    assert finished["result"]["toolContract"]["workflowReady"] is True
    assert finished["result"]["ruleSpecDraft"]["lock"]["profileId"] == "seqkit-stats"
    assert run_configs
    assert all(run_config["tool"]["ruleTemplate"]["wrapper"] == "v9.8.0/bio/seqkit" for run_config in run_configs)
    assert all(run_config["workflow"]["steps"][0]["params"] == {"command": "stats", "extra": "--all --tabular"} for run_config in run_configs)
    assert fetch_tool(cfg, "bioconda::seqkit")["toolContract"]["workflowReady"] is True
    from apps.remote_runner.tool_platform_storage import search_tool_index

    workflow_ready_page = search_tool_index(cfg, state="WorkflowReady", query="seqkit", limit=10, offset=0)
    assert workflow_ready_page["total"] == 1
    assert workflow_ready_page["items"][0]["toolId"] == "bioconda::seqkit"


def test_h2ometa_database_profile_prepare_job_waits_for_missing_database_resource(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "latestVersion": "2.1.3",
        }
    )
    assert draft is not None

    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "2.1.3",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "waiting_resource"
    assert finished["stage"] == "waiting_resource"
    assert finished["errorCode"] == "RESOURCE_BINDING_MISSING"
    assert "kraken2_db" in finished["message"]
    assert finished["result"] is None
    waiting_events = [event for event in finished["events"] if event["stage"] == "waiting_resource"]
    assert waiting_events
    assert waiting_events[-1]["level"] == "warning"
    assert waiting_events[-1]["details"]["resourceKey"] == "kraken2_db"
    assert waiting_events[-1]["details"]["acceptedTemplates"] == ["kraken2"]
    assert finished["missingResources"] == [
        {
            "key": "kraken2_db",
            "resourceType": "database",
            "configKey": "kraken2_db",
            "acceptedTemplates": ["kraken2"],
            "candidates": [],
        }
    ]
    assert fetch_tool(cfg, "bioconda::kraken2") is None


def test_h2ometa_bracken_profile_prepare_job_waits_for_missing_database_resource(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    draft = resolve_tool_profile(
        {
            "id": "bioconda::bracken",
            "name": "bracken",
            "source": "bioconda",
            "packageSpec": "bioconda::bracken=2.9",
            "latestVersion": "2.9",
        }
    )
    assert draft is not None

    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::bracken",
            "name": "bracken",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "2.9",
            "packageSpec": "bioconda::bracken=2.9",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "waiting_resource"
    assert finished["errorCode"] == "RESOURCE_BINDING_MISSING"
    assert finished["missingResources"] == [
        {
            "key": "bracken_db",
            "resourceType": "database",
            "configKey": "bracken_db",
            "acceptedTemplates": ["bracken"],
            "candidates": [],
        }
    ]


def test_database_profile_prepare_job_reports_ambiguous_resource_candidates(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    _runtime_commands(tmp_path)
    for index in range(2):
        database_dir = tmp_path / f"kraken2-db-{index}"
        database_dir.mkdir()
        for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
            (database_dir / filename).write_text("db\n", encoding="utf-8")
        add_reference_database(
            cfg,
            {
                "id": f"db_kraken2_{index}",
                "name": f"Kraken2 DB {index}",
                "templateId": "kraken2",
                "path": str(database_dir),
            },
        )
        checked_database = check_reference_database(cfg, f"db_kraken2_{index}")
        assert checked_database["status"] == "available"
    draft = resolve_tool_profile(
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "latestVersion": "2.1.3",
        }
    )
    assert draft is not None

    job = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::kraken2",
            "name": "kraken2",
            "source": "bioconda",
            "sourceLabel": "Bioconda",
            "version": "2.1.3",
            "packageSpec": "bioconda::kraken2=2.1.3",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": draft["ruleTemplate"],
            "ruleSpecDraft": draft,
        },
    )

    run_tool_prepare_job(cfg, job["jobId"])

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "waiting_resource"
    assert finished["errorCode"] == "RESOURCE_BINDING_AMBIGUOUS"
    assert finished["missingResources"][0]["key"] == "kraken2_db"
    assert finished["missingResources"][0]["acceptedTemplates"] == ["kraken2"]
    assert sorted(candidate["id"] for candidate in finished["missingResources"][0]["candidates"]) == [
        "db_kraken2_0",
        "db_kraken2_1",
    ]


def test_waiting_resource_prepare_job_is_terminal(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    job = create_tool_prepare_job(cfg, {"id": "bioconda::kraken2", "name": "kraken2"})

    mark_tool_prepare_job_waiting_resource(
        cfg,
        job["jobId"],
        code="WORKFLOW_RESOURCE_BINDING_REQUIRED",
        message="Required database resource binding is missing: kraken2_db",
        details={"resourceKey": "kraken2_db", "acceptedTemplates": ["kraken2"]},
    )

    record_tool_prepare_job_event(cfg, job["jobId"], stage="dry_run", message="This event should not advance a terminal job.")
    fail_tool_prepare_job(cfg, job["jobId"], code="SNAKEMAKE_DRY_RUN_FAILED", message="This should not overwrite waiting_resource.")
    cancel_tool_prepare_job(cfg, job["jobId"])
    complete_tool_prepare_job(cfg, job["jobId"], {"message": "This should not publish."})

    finished = fetch_tool_prepare_job(cfg, job["jobId"])
    assert finished is not None
    assert finished["status"] == "waiting_resource"
    assert finished["stage"] == "waiting_resource"
    assert finished["errorCode"] == "WORKFLOW_RESOURCE_BINDING_REQUIRED"
    assert finished["result"] is None
    assert [event["stage"] for event in finished["events"]] == ["queued", "waiting_resource"]


def test_create_prepare_job_reuses_existing_active_job_for_same_tool(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    first = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    second = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc", "summary": "ignored"})

    assert second["jobId"] == first["jobId"]
    assert second["status"] == "queued"
    assert second["request"] == {"id": "bioconda::fastqc", "name": "fastqc"}
    assert [event["stage"] for event in second["events"]] == ["queued"]

    record_tool_prepare_job_event(cfg, first["jobId"], stage="dry_run", message="Running dry-run.")
    third = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    assert third["jobId"] == first["jobId"]
    assert third["status"] == "running"

    fail_tool_prepare_job(cfg, first["jobId"], code="SNAKEMAKE_DRY_RUN_FAILED", message="dry-run failed")
    retry = create_tool_prepare_job(cfg, {"id": "bioconda::fastqc", "name": "fastqc"})
    assert retry["jobId"] != first["jobId"]
    assert retry["status"] == "queued"


def test_create_prepare_job_reserves_active_job_by_package_and_validation_target(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

    first = create_tool_prepare_job(
        cfg,
        {
            "id": "bioconda::fastqc",
            "name": "fastqc",
            "packageSpec": "  Bioconda::FASTQC=0.12.1  ",
            "validationTarget": "workflow-ready",
        },
    )
    same_reservation = create_tool_prepare_job(
        cfg,
        {
            "id": "curated::fastqc",
            "name": "FastQC",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "validationTarget": " workflow-ready ",
        },
    )
    different_target = create_tool_prepare_job(
        cfg,
        {
            "id": "curated::fastqc-production",
            "name": "FastQC",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "validationTarget": "production-evidence",
        },
    )

    assert same_reservation["jobId"] == first["jobId"]
    assert same_reservation["reusedExisting"] is True
    assert same_reservation["reservation"] == {
        "key": "workflow-ready\x1fbioconda::fastqc=0.12.1",
        "packageSpec": "bioconda::fastqc=0.12.1",
        "validationTarget": "workflow-ready",
    }
    assert different_target["jobId"] != first["jobId"]
    assert different_target["reusedExisting"] is False

    fail_tool_prepare_job(cfg, first["jobId"], code="SNAKEMAKE_DRY_RUN_FAILED", message="dry-run failed")
    retry = create_tool_prepare_job(
        cfg,
        {
            "id": "curated::fastqc-retry",
            "name": "FastQC",
            "packageSpec": "bioconda::fastqc=0.12.1",
            "validationTarget": "workflow-ready",
        },
    )
    assert retry["jobId"] != first["jobId"]
    assert retry["reservation"]["key"] == "workflow-ready\x1fbioconda::fastqc=0.12.1"


def _publish_tool_candidate(cfg, payload: dict[str, object]) -> dict[str, object]:
    item = validate_registered_tool_for_publish(cfg, payload)
    published = publish_tool_revision(cfg, item)
    published["status"] = "published"
    published["message"] = str(item.get("message") or "Tool revision published.")
    return upsert_tool(cfg, published)


def _prepare_tool_payload(tool_id: str, name: str) -> dict[str, object]:
    return {
        "id": tool_id,
        "name": name,
        "source": "conda-forge",
        "packageSpec": f"conda-forge::{name}=1.0",
        "targetPlatform": "linux-64",
        "targetPlatformSupported": True,
        "ruleTemplate": {
            "commandTemplate": "cp {input.primary:q} {output.report:q}",
            "inputs": [{"name": "primary", "type": "file", "required": True}],
            "outputs": [{"name": "report", "path": "report.txt", "kind": "log", "mimeType": "text/plain"}],
            **_rule_contract_fields(),
            "environment": {
                "conda": {
                    "channels": ["conda-forge", "bioconda"],
                    "dependencies": [f"conda-forge::{name}=1.0"],
                }
            },
            "smokeTest": {"inputs": {"primary": {"filename": "input.txt", "content": "smoke\n"}}},
        },
    }
