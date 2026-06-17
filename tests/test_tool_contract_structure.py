from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
REMOTE_RUNNER = ROOT / "apps" / "remote_runner"


def test_tool_contract_status_normalization_lives_outside_contract_builder() -> None:
    contract_source = (REMOTE_RUNNER / "tool_contract.py").read_text(encoding="utf-8")
    status_path = REMOTE_RUNNER / "tool_contract_status.py"

    assert status_path.exists()
    status_source = status_path.read_text(encoding="utf-8")

    assert len(contract_source.splitlines()) <= 460
    assert "from .tool_contract_status import (" in contract_source
    assert "from .tool_resource_codes import WAITING_RESOURCE_CODES" in contract_source
    assert "VALIDATION_KEYS =" not in contract_source
    assert "VALIDATION_NOT_RUN =" not in contract_source
    assert "WAITING_RESOURCE_CODES =" not in contract_source
    assert "def default_contract_status(" not in contract_source
    assert "def normalize_contract_status(" not in contract_source

    assert "VALIDATION_KEYS =" in status_source
    assert "VALIDATION_NOT_RUN =" in status_source
    assert "def default_contract_status(" in status_source
    assert "def normalize_contract_status(" in status_source


def test_tool_contract_environment_summary_lives_outside_contract_builder() -> None:
    contract_source = (REMOTE_RUNNER / "tool_contract.py").read_text(encoding="utf-8")
    environment_path = REMOTE_RUNNER / "tool_contract_environment.py"

    assert environment_path.exists()
    environment_source = environment_path.read_text(encoding="utf-8")
    assert len(contract_source.splitlines()) <= 415
    assert "from .tool_contract_environment import summarize_contract_environment" in contract_source
    assert "def _environment_summary(" not in contract_source
    assert "def _dependency_locked(" not in contract_source
    assert "def _channel_priority_strict(" not in contract_source
    assert "def _string_list(" not in contract_source
    assert "def summarize_contract_environment(" in environment_source
    assert "def _dependency_locked(" in environment_source
    assert "def _channel_priority_strict(" in environment_source


def test_tool_contract_rule_summary_lives_outside_contract_builder() -> None:
    contract_source = (REMOTE_RUNNER / "tool_contract.py").read_text(encoding="utf-8")
    rule_summary_path = REMOTE_RUNNER / "tool_contract_rule_summary.py"

    assert rule_summary_path.exists()
    rule_summary_source = rule_summary_path.read_text(encoding="utf-8")

    assert len(contract_source.splitlines()) <= 260
    assert "from .tool_contract_rule_summary import (" in contract_source
    assert "def summarize_rule_template(" not in contract_source
    assert "def selected_rule_entry(" not in contract_source
    assert "def has_rule_template_shape(" not in contract_source
    assert "def _rule_action_fields(" not in contract_source
    assert "def _wrapper_ref_locked(" not in contract_source
    assert "def _scheduler_resource_count(" not in contract_source
    assert "MOVING_WRAPPER_REFS" not in contract_source
    assert "WRAPPER_VERSION_RE" not in contract_source
    assert "WRAPPER_COMMIT_RE" not in contract_source

    assert "def summarize_rule_template(" in rule_summary_source
    assert "def selected_rule_entry(" in rule_summary_source
    assert "def has_rule_template_shape(" in rule_summary_source
    assert "def _rule_action_fields(" in rule_summary_source
    assert "def _wrapper_ref_locked(" in rule_summary_source
    assert "def _scheduler_resource_count(" in rule_summary_source
    assert "MOVING_WRAPPER_REFS" in rule_summary_source
    assert "WRAPPER_VERSION_RE" in rule_summary_source
    assert "WRAPPER_COMMIT_RE" in rule_summary_source


def test_tool_contract_smoke_summary_lives_outside_contract_builder() -> None:
    contract_source = (REMOTE_RUNNER / "tool_contract.py").read_text(encoding="utf-8")
    smoke_summary_path = REMOTE_RUNNER / "tool_contract_smoke_summary.py"

    assert smoke_summary_path.exists()
    smoke_summary_source = smoke_summary_path.read_text(encoding="utf-8")

    assert "from .tool_contract_smoke_summary import summarize_smoke_test" in contract_source
    assert "def _smoke_test_summary(" not in contract_source
    assert "def _smoke_input_ready(" not in contract_source
    assert "def summarize_smoke_test(" in smoke_summary_source
    assert "def _smoke_input_ready(" in smoke_summary_source


def test_h2ometa_tool_profile_registry_lives_outside_profile_resolver() -> None:
    resolver_path = API / "tool_profiles.py"
    registry_path = API / "tool_profile_registry.py"
    model_path = API / "tool_profile_model.py"
    definitions_path = API / "tool_profile_definitions.py"

    resolver_source = resolver_path.read_text(encoding="utf-8")
    assert len(resolver_source.splitlines()) <= 150
    assert registry_path.exists()
    assert "from .tool_profile_sources import all_tool_profiles" in resolver_source
    assert "TOOL_PROFILES: tuple[ToolProfile, ...]" not in resolver_source

    registry_source = registry_path.read_text(encoding="utf-8")
    assert len(registry_source.splitlines()) <= 30
    assert "from .tool_profile_definitions import TOOL_PROFILES" in registry_source
    assert "from .tool_profile_model import ToolProfile" in registry_source
    assert "class ToolProfile:" not in registry_source
    assert "ToolProfile(" not in registry_source
    assert "rule_template=" not in registry_source

    assert model_path.exists()
    model_source = model_path.read_text(encoding="utf-8")
    assert "class ToolProfile:" in model_source
    assert "TOOL_PROFILES" not in model_source

    assert definitions_path.exists()
    definitions_source = definitions_path.read_text(encoding="utf-8")
    assert "from .tool_profile_model import ToolProfile" in definitions_source
    assert "TOOL_PROFILES: tuple[ToolProfile, ...]" in definitions_source
    for profile_id in ["bracken", "fastp", "fastqc", "kraken2", "multiqc", "seqkit-stats"]:
        assert f'profile_id="{profile_id}"' in definitions_source


def test_tool_contract_smoke_fixture_helpers_live_outside_validation_runner() -> None:
    validation_path = REMOTE_RUNNER / "tool_contract_validation.py"
    smoke_path = REMOTE_RUNNER / "tool_contract_smoke.py"

    validation_source = validation_path.read_text(encoding="utf-8")
    assert len(validation_source.splitlines()) <= 390
    assert smoke_path.exists()
    assert "from .tool_contract_smoke import (" in validation_source
    for helper in [
        "_materialize_smoke_inputs",
        "_smoke_workflow_inputs",
        "_smoke_fixture_error",
        "_fixture_bytes",
        "_default_input_filename",
        "_default_input_content",
        "_smoke_test",
        "_smoke_timeout",
    ]:
        assert f"def {helper}(" not in validation_source

    smoke_source = smoke_path.read_text(encoding="utf-8")
    for helper in [
        "materialize_smoke_inputs",
        "smoke_workflow_inputs",
        "smoke_fixture_error",
        "smoke_test",
        "smoke_timeout",
    ]:
        assert f"def {helper}(" in smoke_source


def test_tool_contract_snakemake_execution_lives_outside_validation_runner() -> None:
    validation_path = REMOTE_RUNNER / "tool_contract_validation.py"
    snakemake_path = REMOTE_RUNNER / "tool_contract_snakemake.py"

    validation_source = validation_path.read_text(encoding="utf-8")
    assert snakemake_path.exists()
    snakemake_source = snakemake_path.read_text(encoding="utf-8")

    assert "from .tool_contract_snakemake import (" in validation_source
    assert "import subprocess" not in validation_source
    assert "SNAKEMAKE_EXECUTION_LOCK" not in validation_source
    assert "def _run_snakemake(" not in validation_source
    assert "def _snakemake_event_details(" not in validation_source
    assert "def _snakemake_execution_args(" not in validation_source
    assert "def _tail(" not in validation_source
    assert "def _write_run_log(" not in validation_source

    assert "def run_snakemake(" in snakemake_source
    assert "def snakemake_event_details(" in snakemake_source
    assert "def _snakemake_execution_args(" in snakemake_source
    assert "def _write_run_log(" in snakemake_source
    assert "subprocess.run(" in snakemake_source
    assert "SNAKEMAKE_EXECUTION_LOCK" in snakemake_source
