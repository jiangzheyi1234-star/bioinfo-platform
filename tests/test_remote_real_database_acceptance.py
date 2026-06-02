from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def _load_acceptance_module() -> Any:
    script = Path("skills/h2ometa-remote-smoke-test/scripts/remote_real_database_acceptance.py")
    script_dir = str(script.parent.resolve())
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("remote_real_database_acceptance", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acceptance_scope_reports_missing_required_templates() -> None:
    module = _load_acceptance_module()

    report = module.build_acceptance_scope(
        templates=[
            {"id": "kraken2", "pathKind": "directory"},
            {"id": "blast", "pathKind": "prefix"},
        ],
        databases=[
            {
                "id": "db_kraken2",
                "path": "/db/kraken2",
                "status": "available",
                "metadata": {"templateId": "kraken2"},
            }
        ],
        required_templates=["kraken2", "blast"],
    )

    assert report["ok"] is False
    assert report["missingTemplates"] == ["blast"]
    assert report["selectedTemplateIds"] == ["kraken2"]


def test_single_path_database_requires_resolved_metadata() -> None:
    module = _load_acceptance_module()

    result = module.validate_database_contract(
        {
            "id": "db_blast",
            "path": "/db/blast",
            "status": "available",
            "metadata": {
                "templateId": "blast",
                "input": {"kind": "single", "path": "/db/blast"},
                "resolved": {"default": "/db/blast/core_nt"},
                "resolvedPath": {"kind": "prefix", "prefix": "/db/blast/core_nt"},
            },
        },
        {"id": "blast", "pathKind": "prefix"},
    )

    assert result["status"] == "accepted"
    assert result["resolvedValue"] == "/db/blast/core_nt"


def test_composite_database_requires_field_object_resolution() -> None:
    module = _load_acceptance_module()

    result = module.validate_database_contract(
        {
            "id": "db_humann",
            "path": "/db/humann",
            "status": "available",
            "metadata": {
                "templateId": "humann",
                "input": {
                    "kind": "multi",
                    "fields": {
                        "nucleotide": "/db/humann/chocophlan",
                        "protein": "/db/humann/uniref",
                        "utility_mapping": "/db/humann/utility_mapping",
                    },
                },
                "resolved": {
                    "nucleotide": "/db/humann/chocophlan",
                    "protein": "/db/humann/uniref",
                    "utility_mapping": "/db/humann/utility_mapping",
                },
                "resolvedPath": {
                    "kind": "composite",
                    "entries": {
                        "nucleotide": "/db/humann/chocophlan",
                        "protein": "/db/humann/uniref",
                        "utility_mapping": "/db/humann/utility_mapping",
                    },
                },
            },
        },
        {
            "id": "humann",
            "pathKind": "composite",
            "fields": {
                "nucleotide": {},
                "protein": {},
                "utility_mapping": {},
            },
        },
    )

    assert result["status"] == "accepted"
    assert result["resolvedValue"] == {
        "nucleotide": "/db/humann/chocophlan",
        "protein": "/db/humann/uniref",
        "utility_mapping": "/db/humann/utility_mapping",
    }


def test_contract_rejects_declared_database() -> None:
    module = _load_acceptance_module()

    result = module.validate_database_contract(
        {
            "id": "db_kaiju",
            "path": "/db/kaiju",
            "status": "declared",
            "metadata": {
                "templateId": "kaiju",
                "input": {"kind": "single", "path": "/db/kaiju"},
                "resolved": {"default": "/db/kaiju"},
                "resolvedPath": {"kind": "directory", "path": "/db/kaiju"},
            },
        },
        {"id": "kaiju", "pathKind": "directory"},
    )

    assert result["status"] == "rejected"
    assert "status is declared" in result["issues"]
