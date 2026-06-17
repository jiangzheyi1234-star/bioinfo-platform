from __future__ import annotations

import asyncio
from pathlib import Path

from apps.remote_runner.databases import (
    DATABASE_TEMPLATES,
    DatabaseRegistryError,
    add_reference_database,
    add_verified_reference_database,
    check_reference_database,
    list_reference_databases,
    remove_reference_database,
    resolve_run_databases,
    update_reference_database,
)
from apps.remote_runner.database_templates import list_database_templates
from tests.helpers.reference_database import (
    assert_resolution_contract as _assert_resolution_contract,
    make_bwa_reference as _make_bwa_reference,
    make_configured_remote_runner as _cfg,
    make_kraken2_database as _make_kraken2_database,
    materialize_template_path as _materialize_template_path,
)
from scripts.register_gtdbtk_r232_database import (
    DEFAULT_PACK_ID,
    GTDBTK_R232_ARCHIVE_BYTES,
    GTDBTK_R232_MD5,
    GTDBTK_R232_SOURCE_URL,
)


def test_reference_database_registry_checks_remote_path(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-mini", complete=False)

    saved = add_reference_database(
        cfg,
        {
            "id": "kraken2-mini",
            "name": "Kraken2 Mini",
            "type": "taxonomy",
            "version": "test",
            "path": str(database_dir),
        },
    )
    checked = check_reference_database(cfg, saved["id"])

    assert checked["status"] == "available"
    assert checked["path"] == str(database_dir)
    assert list_reference_databases(cfg)[0]["id"] == "kraken2-mini"

    remove_reference_database(cfg, "kraken2-mini")
    assert list_reference_databases(cfg) == []


def test_reference_database_records_include_database_layer_metadata(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    (manual_dir / "data.txt").write_text("manual", encoding="utf-8")

    manual = add_reference_database(
        cfg,
        {
            "id": "manual-db",
            "name": "Manual DB",
            "templateId": "custom",
            "path": str(manual_dir),
        },
    )

    assert manual["databaseLayer"] == "user_manual"
    assert manual["metadata"]["databaseLayer"] == "user_manual"
    assert manual["metadata"]["productionEligible"] is True

    fixture_dir = _make_kraken2_database(tmp_path / "kraken2-fixture")
    fixture = add_reference_database(
        cfg,
        {
            "id": "fixture-db",
            "name": "Fixture DB",
            "templateId": "kraken2",
            "path": str(fixture_dir),
            "source": "minimal-real-smoke",
            "metadata": {
                "databaseLayer": "validation_fixture",
                "fixtureScope": "template-smoke",
            },
        },
    )

    assert fixture["databaseLayer"] == "validation_fixture"
    assert fixture["metadata"]["databaseLayer"] == "validation_fixture"
    assert fixture["metadata"]["fixtureScope"] == "template-smoke"
    assert fixture["metadata"]["productionEligible"] is False


def test_pack_lineage_registration_metadata_must_match_catalog(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "gtdbtk-pack"
    database_dir.mkdir()

    saved = add_reference_database(
        cfg,
        {
            "id": "gtdbtk-pack",
            "name": "GTDB-Tk Pack",
            "templateId": "gtdbtk",
            "type": "taxonomy",
            "version": "R232",
            "path": str(database_dir),
            "source": GTDBTK_R232_SOURCE_URL,
            "databaseLayer": "production_full",
            "sizeBytes": GTDBTK_R232_ARCHIVE_BYTES,
            "checksum": f"md5:{GTDBTK_R232_MD5}",
            "metadata": {
                "packId": DEFAULT_PACK_ID,
                "installedFromPackId": DEFAULT_PACK_ID,
            },
        },
    )

    assert saved["databaseLayer"] == "production_full"
    assert saved["metadata"]["packId"] == DEFAULT_PACK_ID
    assert saved["metadata"]["installedFromPackId"] == DEFAULT_PACK_ID
    assert saved["metadata"]["packSourceUrl"] == GTDBTK_R232_SOURCE_URL
    assert saved["metadata"]["packChecksum"] == f"md5:{GTDBTK_R232_MD5}"
    assert saved["metadata"]["packArchiveSizeBytes"] == GTDBTK_R232_ARCHIVE_BYTES
    assert saved["metadata"]["installationMethod"] == "manual_external"


def test_pack_lineage_registration_rejects_catalog_mismatch(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "gtdbtk-pack-mismatch"
    database_dir.mkdir()

    invalid_cases = [
        ("source", {"source": "https://example.invalid/gtdbtk.tar.gz"}, "DATABASE_PACK_SOURCE_MISMATCH"),
        ("checksum", {"checksum": "md5:bad"}, "DATABASE_PACK_CHECKSUM_MISMATCH"),
        ("size", {"sizeBytes": GTDBTK_R232_ARCHIVE_BYTES + 1}, "DATABASE_PACK_SIZE_MISMATCH"),
        ("layer", {"databaseLayer": "user_manual"}, "DATABASE_PACK_LAYER_MISMATCH"),
    ]

    for label, override, expected in invalid_cases:
        payload = {
            "id": f"gtdbtk-pack-{label}",
            "name": f"GTDB-Tk Pack {label}",
            "templateId": "gtdbtk",
            "path": str(database_dir),
            "source": GTDBTK_R232_SOURCE_URL,
            "databaseLayer": "production_full",
            "sizeBytes": GTDBTK_R232_ARCHIVE_BYTES,
            "checksum": f"md5:{GTDBTK_R232_MD5}",
            "metadata": {"installedFromPackId": DEFAULT_PACK_ID},
            **override,
        }
        try:
            add_reference_database(cfg, payload)
        except DatabaseRegistryError as exc:
            assert str(exc) == expected
        else:
            raise AssertionError(f"pack mismatch case {label!r} should fail")


def test_reference_database_rejects_unsupported_database_layer(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "unsupported-layer"
    database_dir.mkdir()

    try:
        add_reference_database(
            cfg,
            {
                "id": "unsupported-layer",
                "name": "Unsupported Layer",
                "templateId": "custom",
                "path": str(database_dir),
                "metadata": {"databaseLayer": "mini_realish"},
            },
        )
    except DatabaseRegistryError as exc:
        assert str(exc) == "DATABASE_LAYER_UNSUPPORTED"
    else:
        raise AssertionError("unsupported database layers should fail loudly")


def test_downloadable_pack_layer_is_not_registered_as_installed_database(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "downloadable-pack"
    database_dir.mkdir()

    try:
        add_reference_database(
            cfg,
            {
                "id": "downloadable-pack",
                "name": "Downloadable Pack",
                "templateId": "custom",
                "path": str(database_dir),
                "metadata": {"databaseLayer": "downloadable_pack"},
            },
        )
    except DatabaseRegistryError as exc:
        assert str(exc) == "DATABASE_LAYER_DOWNLOADABLE_PACK_NOT_REGISTERABLE"
    else:
        raise AssertionError("downloadable packs should be catalog entries, not installed database records")


def test_verified_reference_database_add_rejects_invalid_kraken2_database(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-incomplete", complete=False)

    try:
        add_verified_reference_database(
            cfg,
            {
                "id": "kraken2-incomplete",
                "name": "Kraken2 Incomplete",
                "templateId": "kraken2",
                "path": str(database_dir),
            },
        )
    except DatabaseRegistryError as exc:
        assert "opts.k2d" in str(exc)
    else:
        raise AssertionError("incomplete Kraken2 database should be rejected")

    assert list_reference_databases(cfg) == []


def test_verified_reference_database_update_keeps_previous_state_on_failure(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    valid_dir = _make_kraken2_database(tmp_path / "kraken2-valid")

    saved = add_verified_reference_database(
        cfg,
        {
            "id": "kraken2-existing",
            "name": "Kraken2 Existing",
            "templateId": "kraken2",
            "path": str(valid_dir),
        },
    )
    assert saved["status"] == "available"
    original_message = saved["message"]

    invalid_dir = _make_kraken2_database(tmp_path / "kraken2-invalid", complete=False)

    try:
        add_verified_reference_database(
            cfg,
            {
                "id": "kraken2-existing",
                "name": "Kraken2 Existing",
                "templateId": "kraken2",
                "path": str(invalid_dir),
            },
        )
    except DatabaseRegistryError as exc:
        assert "opts.k2d" in str(exc)
    else:
        raise AssertionError("updating with invalid path should be rejected")

    current = list_reference_databases(cfg)
    assert len(current) == 1
    assert current[0]["id"] == "kraken2-existing"
    assert current[0]["status"] == "available"
    assert current[0]["path"] == str(valid_dir)
    assert current[0]["message"] == original_message


def test_verified_reference_database_add_requires_template(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "generic-nonempty"
    database_dir.mkdir()
    (database_dir / "data.txt").write_text("data", encoding="utf-8")

    try:
        add_verified_reference_database(
            cfg,
            {
                "id": "generic-db",
                "name": "Generic DB",
                "type": "taxonomy",
                "path": str(database_dir),
            },
        )
    except DatabaseRegistryError as exc:
        assert str(exc) == "DATABASE_TEMPLATE_REQUIRED"
    else:
        raise AssertionError("verified add should require a database template")

    assert list_reference_databases(cfg) == []


def test_verified_reference_database_add_accepts_valid_kraken2_database(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-complete")

    saved = add_verified_reference_database(
        cfg,
        {
            "id": "kraken2-complete",
            "name": "Kraken2 Complete",
            "templateId": "kraken2",
            "path": str(database_dir),
        },
    )

    assert saved["status"] == "available"
    assert saved["id"] == "kraken2-complete"
    assert list_reference_databases(cfg)[0]["id"] == "kraken2-complete"



def test_remote_runner_database_post_returns_only_available_after_validation(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-api")

    from apps.remote_runner.api_models import DatabaseManifestRequest
    from apps.remote_runner.database_routes import add_database

    payload = DatabaseManifestRequest(
        id="kraken2-api",
        name="Kraken2 API",
        templateId="kraken2",
        path=str(database_dir),
    )
    result = asyncio.run(add_database(payload, authorization=f"Bearer {cfg.token}"))

    item = result["data"]
    assert item["status"] == "available"
    assert item["message"] != "Database declared."


def test_remote_runner_database_post_rejects_invalid_database_without_registering(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("apps.remote_runner.route_utils.load_remote_runner_config", lambda: cfg)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-api-invalid", complete=False)

    from apps.remote_runner.api_models import DatabaseManifestRequest
    from apps.remote_runner.database_routes import add_database

    payload = DatabaseManifestRequest(
        id="kraken2-api-invalid",
        name="Kraken2 API Invalid",
        templateId="kraken2",
        path=str(database_dir),
    )

    try:
        asyncio.run(add_database(payload, authorization=f"Bearer {cfg.token}"))
    except DatabaseRegistryError as exc:
        assert "opts.k2d" in str(exc)
    else:
        raise AssertionError("invalid database should fail the add endpoint")
    assert list_reference_databases(cfg) == []


def test_verified_reference_database_add_restores_existing_record_when_replacement_is_invalid(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    valid_dir = _make_kraken2_database(tmp_path / "kraken2-valid")
    invalid_dir = _make_kraken2_database(tmp_path / "kraken2-invalid", complete=False)

    original = add_verified_reference_database(
        cfg,
        {
            "id": "kraken2-db",
            "name": "Kraken2 Valid",
            "templateId": "kraken2",
            "path": str(valid_dir),
        },
    )

    try:
        add_verified_reference_database(
            cfg,
            {
                "id": "kraken2-db",
                "name": "Kraken2 Invalid",
                "templateId": "kraken2",
                "path": str(invalid_dir),
            },
        )
    except DatabaseRegistryError as exc:
        assert "opts.k2d" in str(exc)
    else:
        raise AssertionError("invalid replacement should be rejected")

    current = list_reference_databases(cfg)
    assert len(current) == 1
    assert current[0]["id"] == original["id"]
    assert current[0]["name"] == original["name"]
    assert current[0]["path"] == original["path"]
    assert current[0]["status"] == "available"


def test_reference_database_registry_updates_display_fields(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-mini", complete=False)

    saved = add_reference_database(
        cfg,
        {
            "id": "kraken2-mini",
            "name": "Kraken2 Mini",
            "type": "taxonomy",
            "version": "test",
            "path": str(database_dir),
        },
    )
    checked = check_reference_database(cfg, saved["id"])

    updated = update_reference_database(
        cfg,
        saved["id"],
        {
            "name": "Core NT",
            "version": "2026.04",
            "description": "Production BLAST core_nt database",
        },
    )

    assert updated["name"] == "Core NT"
    assert updated["version"] == "2026.04"
    assert updated["description"] == "Production BLAST core_nt database"
    assert updated["path"] == str(database_dir)
    assert updated["status"] == checked["status"]
    assert updated["lastCheckedAt"] == checked["lastCheckedAt"]


def test_reference_database_template_validation_requires_expected_files(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = _make_kraken2_database(tmp_path / "kraken2-template", complete=False)

    saved = add_reference_database(
        cfg,
        {
            "id": "kraken2-template",
            "name": "Kraken2 Template",
            "templateId": "kraken2",
            "version": "test",
            "path": str(database_dir),
        },
    )
    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "opts.k2d" in missing["message"]

    (database_dir / "opts.k2d").write_text("mini", encoding="utf-8")
    (database_dir / "taxo.k2d").write_text("mini", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])

    assert checked["status"] == "available"
    assert checked["type"] == "taxonomy"
    assert checked["metadata"]["templateId"] == "kraken2"


def test_database_template_catalog_includes_common_bioinformatics_references() -> None:
    templates = {item["id"]: item for item in list_database_templates()}

    for template_id in [
        "humann",
        "gtdbtk",
        "mmseqs2",
        "hmmer_pfam",
        "eggnog_mapper",
        "interproscan",
        "minimap2",
        "star",
        "hisat2",
        "salmon",
        "kallisto",
        "silva_qiime",
        "checkm",
        "ncbi_taxonomy",
    ]:
        assert template_id in templates
        assert templates[template_id]["name"]
        assert templates[template_id]["pathHint"]
        assert isinstance(templates[template_id]["expectedFiles"], list)
    assert templates["blast"]["pathKind"] == "prefix"
    assert templates["diamond"]["pathKind"] == "file"


def test_all_database_templates_publish_consistent_selection_contract() -> None:
    api_templates = {item["id"]: item for item in list_database_templates()}

    assert set(api_templates) == set(DATABASE_TEMPLATES)

    for template_id, template in DATABASE_TEMPLATES.items():
        api_item = api_templates[template_id]
        assert api_item["pathKind"] == template["pathKind"]
        assert api_item["category"]
        assert api_item["name"] == template["label"]
        assert api_item["pathHint"] == template["pathHint"]
        assert api_item["pathLabel"]
        assert api_item["runtimeValue"]
        assert isinstance(api_item["expectedFiles"], list)
        assert "anyPatterns" in api_item
        assert "primaryExtensions" in api_item
        assert "sidecars" in api_item
        assert "indexSuffixes" in api_item
        assert "companionSuffixes" in api_item
        if template["pathKind"] == "prefix":
            assert api_item["prefixPatternSets"] == template.get("prefixPatternSets")
            assert "prefixPatternSets" in api_item
            assert "prefixAliasPatterns" in api_item
        if template["pathKind"] == "composite":
            assert api_item["fields"] == template.get("fields")
        assert api_item["selector"]["kind"] in {"directory", "file", "prefix", "primary_with_sidecars", "composite"}
        assert api_item["selectorKind"] == api_item["selector"]["kind"]
        assert template["pathKind"] in {"directory", "file", "prefix", "primary_with_sidecars", "composite"}
        assert "category" in template, f"{template_id} should explicitly declare category"
        assert "pathLabel" in template, f"{template_id} should explicitly declare pathLabel"
        assert "runtimeValue" in template, f"{template_id} should explicitly declare runtimeValue"

        has_validation_rule = any(
            template.get(key)
            for key in (
                "requiredFiles",
                "requiredPatterns",
                "requiredSuffixes",
                "anyPatterns",
                "anyIndexPatterns",
                "anyFiles",
                "requiredRecursiveFiles",
                "primaryExtensions",
                "sidecars",
                "anyPatternSets",
                "prefixPatternSets",
                "companionSuffixes",
                "indexSuffixes",
            )
        )
        if template["pathKind"] == "composite":
            has_validation_rule = bool(template.get("fields"))
        if template_id == "custom":
            assert template["pathKind"] in {"directory", "file"}
            continue
        if template["pathKind"] == "prefix":
            assert template.get("requiredSuffixes"), f"{template_id} should explain required prefix suffixes"
        if template["pathKind"] == "primary_with_sidecars":
            assert template.get("primaryExtensions"), f"{template_id} should explain primary file extensions"
            assert template.get("sidecars"), f"{template_id} should explain sidecar index files"
        assert has_validation_rule, f"{template_id} should declare at least one validation rule"


def test_builtin_templates_accept_directory_selection_and_resolve_tool_target(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)

    for template_id, template in DATABASE_TEMPLATES.items():
        if template_id == "custom":
            continue
        target = _materialize_template_path(tmp_path / template_id, template_id)
        selected_path = target if target.is_dir() else target.parent

        saved = add_verified_reference_database(
            cfg,
            {
                "id": f"{template_id}-directory-selection",
                "name": f"{template_id} directory selection",
                "templateId": template_id,
                "path": str(selected_path),
            },
        )

        assert saved["status"] == "available", template_id
        assert saved["path"] == str(selected_path), template_id
        assert saved["inputPath"] == str(selected_path), template_id
        assert saved["pathMode"] == template["pathKind"], template_id
        assert saved["resolvedPath"] == saved["metadata"]["resolvedPath"], template_id
        resolved = saved["metadata"].get("resolvedPath") or {}
        expected_entry_path = "" if template["pathKind"] == "composite" else str(resolved.get("prefix") or resolved.get("path") or selected_path)
        assert saved["entryPath"] == expected_entry_path, template_id
        assert saved["metadata"]["inputPath"] == str(selected_path), template_id
        assert saved["metadata"]["entryPath"] == expected_entry_path, template_id
        assert saved["metadata"]["pathMode"] == template["pathKind"], template_id
        if template["pathKind"] == "prefix":
            assert resolved.get("prefix"), template_id
            assert resolved["prefix"] != str(selected_path), template_id
        if template["pathKind"] == "file":
            assert resolved.get("path"), template_id
            assert Path(resolved["path"]).is_file(), template_id
        if template["pathKind"] == "primary_with_sidecars":
            assert resolved.get("path"), template_id
            assert Path(resolved["path"]).is_file(), template_id
        if template["pathKind"] == "composite":
            assert saved["resolved"], template_id


def test_bwa_template_uses_fasta_main_file_as_entry_path(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    fasta = _make_bwa_reference(tmp_path / "bwa")

    saved = add_verified_reference_database(
        cfg,
        {
            "id": "bwa-hg38",
            "name": "BWA hg38",
            "templateId": "bwa",
            "path": str(fasta),
        },
    )

    assert saved["status"] == "available"
    assert saved["metadata"]["resolvedPath"]["kind"] == "primary_with_sidecars"
    assert saved["metadata"]["resolvedPath"]["path"] == str(fasta)
    _assert_resolution_contract(
        saved,
        input_path=fasta,
        entry_path=fasta,
        path_mode="primary_with_sidecars",
        resolved_path=saved["metadata"]["resolvedPath"],
    )

    resolved = resolve_run_databases(cfg, {"databases": [{"id": "bwa-hg38", "role": "bwa_ref"}]})
    assert resolved["bwa_ref"]["path"] == str(fasta)
    _assert_resolution_contract(
        resolved["bwa_ref"],
        input_path=fasta,
        entry_path=fasta,
        path_mode="primary_with_sidecars",
    )


def test_bwa_template_rejects_selecting_index_file_instead_of_fasta(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    fasta = _make_bwa_reference(tmp_path / "bwa")

    saved = add_reference_database(
        cfg,
        {
            "id": "bwa-index-file",
            "name": "BWA index file",
            "templateId": "bwa",
            "path": str(fasta) + ".amb",
        },
    )

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "missing"
    assert "FASTA main file" in checked["message"]


def test_ncbi_taxonomy_template_requires_taxdump_files(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "taxdump"
    database_dir.mkdir()
    (database_dir / "nodes.dmp").write_text("nodes", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "ncbi-taxonomy",
            "name": "NCBI Taxonomy",
            "templateId": "ncbi_taxonomy",
            "path": str(database_dir),
        },
    )

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "names.dmp" in missing["message"]

    (database_dir / "names.dmp").write_text("names", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
