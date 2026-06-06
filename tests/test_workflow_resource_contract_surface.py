from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.workflow_catalog_service import _catalog_item_from_pipeline
from core.contracts.pipeline_manifest import PipelineRegistryError, validate_pipeline_manifest


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "apps" / "web" / "app" / "components"
DOCS = ROOT / "docs"
PIPELINES = ROOT / "apps" / "remote_runner" / "pipelines"


def _write_manifest(root: Path, resources: object) -> Path:
    pipeline_dir = root / "resource-contract-v1"
    (pipeline_dir / "workflow").mkdir(parents=True)
    (pipeline_dir / ".test").mkdir()
    (pipeline_dir / "workflow" / "Snakefile").write_text('configfile: "run-config.json"\n', encoding="utf-8")
    (pipeline_dir / ".test" / "run-config.json").write_text("{}", encoding="utf-8")
    manifest = {
        "pipelineId": "resource-contract-v1",
        "snakefile": "workflow/Snakefile",
        "execution": {"outputs": {"report": "report.html"}},
        "outputSchema": {
            "artifacts": [
                {
                    "key": "report",
                    "kind": "report",
                    "mimeType": "text/html",
                    "name": "report.html",
                }
            ]
        },
        "resources": resources,
    }
    manifest_path = pipeline_dir / "pipeline.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_workflow_catalog_preserves_pipeline_resource_contract() -> None:
    item = _catalog_item_from_pipeline(
        {
            "pipelineId": "database-backed-analysis-v1",
            "name": "Database Backed Analysis",
            "enabled": True,
            "resources": {
                "reference_database": {
                    "type": "database",
                    "required": False,
                    "configKey": "reference_database",
                }
            },
        }
    )

    assert item["resources"]["reference_database"]["type"] == "database"
    assert item["resources"]["reference_database"]["required"] is False
    assert item["resources"]["reference_database"]["configKey"] == "reference_database"


def test_pipeline_manifest_accepts_valid_resource_contract(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path,
        {
            "reference_database": {
                "type": "database",
                "required": True,
                "configKey": "reference_database",
                "acceptedTemplates": ["blast"],
                "acceptedCapabilities": ["sequence_search"],
            }
        },
    )

    validation = validate_pipeline_manifest(json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path)
    assert validation.pipeline_id == "resource-contract-v1"


@pytest.mark.parametrize(
    ("resources", "error"),
    [
        (
            {"reference_database": {"type": "database", "required": "yes", "configKey": "reference_database"}},
            "RESOURCE_REQUIRED_INVALID",
        ),
        (
            {"reference_database": {"type": "file", "required": True, "configKey": "reference_database"}},
            "RESOURCE_TYPE_UNSUPPORTED",
        ),
        (
            {"reference_database": {"type": "database", "required": True, "configKey": ""}},
            "RESOURCE_CONFIG_KEY_REQUIRED",
        ),
        (
            {"reference_database": {"type": "database", "acceptedTemplates": ["blast", ""]}},
            "RESOURCE_ACCEPTEDTEMPLATES_INVALID",
        ),
        (
            {"reference_database": {"type": "database", "acceptedCapabilities": "sequence_search"}},
            "RESOURCE_ACCEPTEDCAPABILITIES_INVALID",
        ),
    ],
)
def test_pipeline_manifest_rejects_invalid_resource_contract(
    tmp_path: Path,
    resources: object,
    error: str,
) -> None:
    manifest_path = _write_manifest(tmp_path, resources)

    with pytest.raises(PipelineRegistryError, match=error):
        validate_pipeline_manifest(json.loads(manifest_path.read_text(encoding="utf-8")), manifest_path)


def test_workflow_template_docs_describe_resource_binding_import_contract() -> None:
    source = (DOCS / "workflow-template-structure.md").read_text(encoding="utf-8")

    assert "### `resources` Contract" in source
    assert '"type": "database"' in source
    assert '"configKey": "reference_database"' in source
    assert '"acceptedTemplates": ["blast"]' in source
    assert '"resourceBindings"' in source
    assert '`databases`: config-key-to-runtime-value map' in source
    assert '`resourceConfig`: same resolved map' in source
    assert '`resources`: provenance and path-resolution metadata' in source


def test_database_backed_pipeline_consumes_resource_binding_config() -> None:
    source = (PIPELINES / "database-backed-analysis-v1" / "workflow" / "Snakefile").read_text(encoding="utf-8")

    assert 'configfile: "run-config.json"' in source
    assert 'DATABASES = config.get("databases", {})' in source
    assert 'RESOURCE_CONFIG = config.get("resourceConfig", {})' in source
    assert 'RESOURCE_META = config.get("resources", {})' in source
    assert 'REFERENCE_KEY = "reference_database"' in source
    assert "DATABASES.get(REFERENCE_KEY) or RESOURCE_CONFIG.get(REFERENCE_KEY)" in source
    assert "database_bound" in source
    assert "database_unbound" in source
    assert "database_id" in source


def test_database_backed_test_config_models_bound_resource() -> None:
    config_path = PIPELINES / "database-backed-analysis-v1" / ".test" / "run-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["databases"]["reference_database"].endswith(".test/fixtures/reference-db")
    assert config["resourceConfig"]["reference_database"] == config["databases"]["reference_database"]
    resource = config["resources"]["reference_database"]
    assert resource["resourceKey"] == "reference_database"
    assert resource["databaseId"] == "db_reference_test"
    assert resource["configKey"] == "reference_database"
    assert resource["path"] == config["databases"]["reference_database"]
    assert resource["resolved"] == {"default": config["databases"]["reference_database"]}
    assert resource["input"] == {"kind": "single", "path": config["databases"]["reference_database"]}


def test_frontend_normal_pipeline_keeps_resource_binding_contract() -> None:
    model = (COMPONENTS / "workflows-page-model.ts").read_text(encoding="utf-8")
    api = (COMPONENTS / "workflows-page-api.ts").read_text(encoding="utf-8")
    hook = (COMPONENTS / "use-workflows-page-state.ts").read_text(encoding="utf-8")
    ui = (COMPONENTS / "workflows-page-ui.tsx").read_text(encoding="utf-8")

    assert "resources?: Record<string, WorkflowResourceSpec>" in model
    assert "runSpec.resourceBindings = resourceBindings" in model
    assert "databaseMatchesWorkflowResource" in model
    assert "resourceBindings?: WorkflowResourceBindings" in api
    assert "resourceBindings: workflowResourceBindings" in hook
    assert "missingRequiredResourceKeys.length === 0" in hook
    assert "WorkflowResourceBindingsPanel" in ui
    assert "onWorkflowResourceBindingChange" in ui


def test_generated_workflow_builder_auto_binds_single_matching_database() -> None:
    hook = (COMPONENTS / "use-generated-workflow-builder.ts").read_text(encoding="utf-8")
    binding = (COMPONENTS / "generated-workflow-resource-binding.ts").read_text(encoding="utf-8")

    assert 'import { autoBindGeneratedWorkflowResources } from "./generated-workflow-resource-binding";' in hook
    assert "autoBindGeneratedWorkflowResources" in hook
    assert "export function autoBindGeneratedWorkflowResources" in binding
    assert "matching.length === 1" in binding
    assert "databaseMatchesWorkflowResource(database, spec)" in binding
    assert "delete next[resourceKey]" in binding
    assert "matching.length !== 1" in binding
