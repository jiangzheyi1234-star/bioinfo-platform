from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REMOTE_RUNNER = ROOT / "apps" / "remote_runner"


def test_database_registry_schema_lives_outside_database_module() -> None:
    schema = (REMOTE_RUNNER / "database_registry_schema.py").read_text(encoding="utf-8")
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    sqlite_migrations = (REMOTE_RUNNER / "sqlite_migrations.py").read_text(encoding="utf-8")

    assert "REFERENCE_DATABASE_SCHEMA_SQL" in schema
    assert "CREATE TABLE IF NOT EXISTS reference_databases" in schema
    assert "from .database_registry_schema import REFERENCE_DATABASE_SCHEMA_SQL" in sqlite_migrations
    assert "ensure_runtime_schema_current(connection)" in databases
    assert "executescript(REFERENCE_DATABASE_SCHEMA_SQL)" not in databases
    assert '_SCHEMA_SQL = """' not in databases


def test_candidate_database_errors_are_reported_as_conflicts() -> None:
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    database_errors = (REMOTE_RUNNER / "database_errors.py").read_text(encoding="utf-8")
    source = (REMOTE_RUNNER / "route_errors.py").read_text(encoding="utf-8")

    assert "DatabaseCandidateConflictError" in source
    assert "from .database_errors import DatabaseCandidateConflictError, DatabaseRegistryError" in source
    assert "from .databases import DatabaseCandidateConflictError, DatabaseRegistryError" not in source
    assert "DatabaseCandidateConflictError(DatabaseRegistryError):\n    status_code = 409" in database_errors
    assert "class DatabaseCandidateConflictError" not in databases
    assert "DATABASE_CANDIDATES" not in source
    assert 'detail.startswith("DATABASE_CANDIDATES:")' not in source
    assert "_detail_response(409, exc.payload)" not in source
    assert "return status_payload_response(exc)" in source


def test_database_not_found_status_lives_on_domain_error() -> None:
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    database_errors = (REMOTE_RUNNER / "database_errors.py").read_text(encoding="utf-8")
    route_errors = (REMOTE_RUNNER / "route_errors.py").read_text(encoding="utf-8")

    assert "class DatabaseRegistryError(ValueError):\n    status_code = 400" in database_errors
    assert "class DatabaseNotFoundError(DatabaseRegistryError)" in database_errors
    assert "class DatabaseRegistryError" not in databases
    assert "class DatabaseNotFoundError" not in databases
    assert 'raise DatabaseNotFoundError("DATABASE_NOT_FOUND")' in databases
    assert "def database_registry_status_code(" not in route_errors
    assert "DATABASE_NOT_FOUND" not in route_errors
    assert "getattr(exc, \"status_code\", 400)" not in route_errors
    assert "register_status_detail_exception_handlers(" in route_errors
    assert "DatabaseRegistryError," in route_errors


def test_database_candidate_scanning_lives_outside_registry_module() -> None:
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    candidates = (REMOTE_RUNNER / "database_candidates.py").read_text(encoding="utf-8")

    assert len(databases.splitlines()) <= 610
    assert "from .database_candidates import resolve_candidate_payload" in databases
    assert "def _resolve_candidate_payload(" not in databases
    assert "def _candidate_entries(" not in databases
    assert "def _prefix_candidates(" not in databases
    assert "def _file_candidates(" not in databases
    assert "def _primary_with_sidecar_candidates(" not in databases

    assert "def resolve_candidate_payload(" in candidates
    assert "def _candidate_entries(" in candidates
    assert "def _prefix_candidates(" in candidates
    assert "def _file_candidates(" in candidates
    assert "def _primary_with_sidecar_candidates(" in candidates
    assert "DatabaseCandidateConflictError" in candidates


def test_database_runtime_path_semantics_live_outside_registry_module() -> None:
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    runtime_paths_path = REMOTE_RUNNER / "database_runtime_paths.py"

    assert runtime_paths_path.exists()
    runtime_paths = runtime_paths_path.read_text(encoding="utf-8")

    assert len(databases.splitlines()) <= 470
    assert "from .database_runtime_paths import (" in databases
    assert "def compute_database_entry_path(" not in databases
    assert "def database_input_metadata(" not in databases
    assert "def database_resolved_metadata(" not in databases
    assert "def database_resolved_values(" not in databases
    assert "def database_resolved_config_value(" not in databases
    assert "def _composite_input_metadata(" not in databases
    assert "def _composite_resolved_metadata(" not in databases
    assert "def _validate_composite_resolved(" not in databases
    assert "def _resolve_composite_field_value(" not in databases

    assert "def compute_database_entry_path(" in runtime_paths
    assert "def database_input_metadata(" in runtime_paths
    assert "def database_resolved_metadata(" in runtime_paths
    assert "def database_resolved_values(" in runtime_paths
    assert "def database_resolved_config_value(" in runtime_paths
    assert "def _composite_input_metadata(" in runtime_paths
    assert "def _composite_resolved_metadata(" in runtime_paths
    assert "def _validate_composite_resolved(" in runtime_paths
    assert "def _resolve_composite_field_value(" in runtime_paths


def test_database_record_mapping_lives_outside_registry_module() -> None:
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    records_path = REMOTE_RUNNER / "database_records.py"

    assert records_path.exists()
    records = records_path.read_text(encoding="utf-8")

    assert len(databases.splitlines()) <= 370
    assert "from .database_records import" in databases
    assert "def database_row_to_dict(" not in databases
    assert "def normalize_database_payload(" not in databases
    assert "def _row_to_dict(" not in databases
    assert "def _normalize_payload(" not in databases
    assert "def _with_database_path_semantics(" not in databases
    assert "def _default_id(" not in databases

    assert "def database_row_to_dict(" in records
    assert "def normalize_database_payload(" in records
    assert "def _with_database_path_semantics(" in records
    assert "def _default_id(" in records


def test_run_database_resolution_lives_outside_registry_module() -> None:
    databases = (REMOTE_RUNNER / "databases.py").read_text(encoding="utf-8")
    resolution_path = REMOTE_RUNNER / "database_run_resolution.py"

    assert resolution_path.exists()
    resolution = resolution_path.read_text(encoding="utf-8")

    assert len(databases.splitlines()) <= 300
    assert "from .database_run_resolution import resolve_run_databases" in databases
    assert "def resolve_run_databases(" not in databases
    assert "DATABASES_FIELD_REQUIRED" not in databases
    assert "DATABASE_UNAVAILABLE" not in databases
    assert "def resolve_run_databases(" in resolution
    assert "DATABASES_FIELD_REQUIRED" in resolution
    assert "DATABASE_UNAVAILABLE" in resolution
    assert "fetch_reference_database(" in resolution
    assert "check_reference_database(" in resolution


def test_workflow_resource_database_path_helpers_use_runtime_path_module() -> None:
    workflow_resources = (REMOTE_RUNNER / "workflow_resources.py").read_text(encoding="utf-8")

    assert "from .database_runtime_paths import (" in workflow_resources
    assert "database_resolved_config_value" in workflow_resources
    assert "database_resolved_values" in workflow_resources
    assert "from .databases import DATABASE_TEMPLATES" not in workflow_resources
    assert "compute_database_entry_path, database_resolved_config_value" not in workflow_resources


def test_database_template_catalog_mapping_lives_outside_template_definitions() -> None:
    templates = (REMOTE_RUNNER / "database_templates.py").read_text(encoding="utf-8")
    catalog_path = REMOTE_RUNNER / "database_template_catalog.py"

    assert catalog_path.exists()
    catalog = catalog_path.read_text(encoding="utf-8")

    assert len(templates.splitlines()) <= 470
    assert "from .database_template_catalog import (" in templates
    assert "def list_database_templates(" in templates
    assert "def build_database_template_catalog(" not in templates
    assert "def _template_category(" not in templates
    assert "def _template_runtime_shape(" not in templates
    assert "_PATH_KIND_DEFAULTS" not in templates
    assert "_TYPE_CATEGORY_DEFAULTS" not in templates
    assert "_TYPE_CAPABILITY_DEFAULTS" not in templates
    assert "_RUNTIME_SHAPE_DEFAULTS" not in templates

    assert "def build_database_template_catalog(" in catalog
    assert "def database_template_runtime_shape(" in catalog
    assert "def database_template_capabilities(" in catalog
    assert "def _template_category(" in catalog
    assert "def _template_runtime_shape(" in catalog
    assert "_PATH_KIND_DEFAULTS" in catalog
    assert "_TYPE_CATEGORY_DEFAULTS" in catalog
    assert "_TYPE_CAPABILITY_DEFAULTS" in catalog
    assert "_RUNTIME_SHAPE_DEFAULTS" in catalog


def test_database_template_definitions_live_outside_template_facade() -> None:
    templates = (REMOTE_RUNNER / "database_templates.py").read_text(encoding="utf-8")
    definitions_path = REMOTE_RUNNER / "database_template_definitions.py"

    assert definitions_path.exists()
    definitions = definitions_path.read_text(encoding="utf-8")

    assert len(templates.splitlines()) <= 35
    assert "from .database_template_definitions import DATABASE_TEMPLATES" in templates
    assert "DATABASE_TEMPLATES: dict" not in templates
    assert '"kraken2": {' not in templates
    assert "def list_database_templates(" in templates

    assert "DATABASE_TEMPLATES: dict" in definitions
    assert '"kraken2": {' in definitions
    assert "def list_database_templates(" not in definitions
    assert "from .database_template_catalog" not in definitions
