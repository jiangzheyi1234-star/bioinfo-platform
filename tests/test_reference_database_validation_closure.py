from __future__ import annotations

import json
from pathlib import Path

from apps.remote_runner.databases import (
    DatabaseRegistryError,
    add_reference_database,
    add_verified_reference_database,
    check_reference_database,
    resolve_run_databases,
)
from tests.helpers.reference_database import (
    assert_resolution_contract as _assert_resolution_contract,
    iter_workflow_resource_contract_cases,
    make_configured_remote_runner,
    make_kraken2_database as _make_kraken2_database,
)


def _cfg(tmp_path: Path):
    return make_configured_remote_runner(tmp_path, token="database-validation-token")


def test_prefix_database_templates_require_complete_index_sets(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    prefix = tmp_path / "bowtie2" / "human"
    prefix.parent.mkdir()
    for suffix in ("1.bt2", "2.bt2", "3.bt2", "4.bt2", "rev.1.bt2"):
        (prefix.parent / f"{prefix.name}.{suffix}").write_text("index", encoding="utf-8")

    saved = add_reference_database(cfg, {"id": "bowtie2-human", "name": "Bowtie2 human", "templateId": "bowtie2", "path": str(prefix)})

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "human.rev.2.bt2" in missing["message"]

    (prefix.parent / "human.rev.2.bt2").write_text("index", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"
    assert checked["metadata"]["resolvedPath"]["kind"] == "prefix"
    assert checked["metadata"]["resolvedPath"]["prefix"] == str(prefix)
    _assert_resolution_contract(
        checked,
        input_path=prefix,
        entry_path=prefix,
        path_mode="prefix",
        resolved_path=checked["metadata"]["resolvedPath"],
    )




def test_prefix_template_directory_resolves_alias_prefix(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "blast"
    database_dir.mkdir()
    (database_dir / "core_nt.nal").write_text("alias", encoding="utf-8")
    for suffix in (".00.nhr", ".00.nin", ".00.nsq"):
        (database_dir / f"core_nt{suffix}").write_text("volume", encoding="utf-8")

    template = {"pathKind": "prefix", "prefixPatternSets": [[".nhr", ".nin", ".nsq"]], "prefixAliasPatterns": ["*.nal"]}
    resolved = database_validation.resolve_template_path(database_dir, template)

    assert resolved["prefix"] == str(database_dir / "core_nt")
    assert database_validation.validate_template_files(database_dir, {"metadata": {"templateId": "blast"}}, template, resolved=resolved) == ""


def test_prefix_template_directory_resolves_first_complete_index_prefix(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "blast"
    database_dir.mkdir()
    for suffix in (".nhr", ".nin", ".nsq"):
        (database_dir / f"custom{suffix}").write_text("index", encoding="utf-8")

    template = {"pathKind": "prefix", "prefixPatternSets": [[".nhr", ".nin", ".nsq"]]}
    resolved = database_validation.resolve_template_path(database_dir, template)

    assert resolved["prefix"] == str(database_dir / "custom")
    assert database_validation.validate_template_files(database_dir, {"metadata": {"templateId": "blast"}}, template, resolved=resolved) == ""


def test_file_template_directory_resolves_first_matching_database_file(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "diamond"
    database_dir.mkdir()
    (database_dir / "nr.dmnd").write_text("diamond", encoding="utf-8")

    template = {"pathKind": "file", "anyPatterns": ["*.dmnd"]}
    resolved = database_validation.resolve_template_path(database_dir, template)

    assert resolved["path"] == str(database_dir / "nr.dmnd")
    assert resolved["firstMatch"] == str(database_dir / "nr.dmnd")
    assert database_validation.validate_template_files(database_dir, {"metadata": {"templateId": "diamond"}}, template, resolved=resolved) == ""


def test_file_template_directory_rejects_multiple_matching_database_files(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "diamond"
    database_dir.mkdir()
    (database_dir / "nr.dmnd").write_text("diamond", encoding="utf-8")
    (database_dir / "uniref.dmnd").write_text("diamond", encoding="utf-8")

    template = {"pathKind": "file", "anyPatterns": ["*.dmnd"]}
    resolved = database_validation.resolve_template_path(database_dir, template)

    assert "ambiguousCandidates" in resolved
    assert "multiple candidate targets" in database_validation.validate_template_files(
        database_dir,
        {"metadata": {"templateId": "diamond"}},
        template,
        resolved=resolved,
    )


def test_ambiguous_candidates_list_is_truncated_for_readability(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "diamond_many"
    database_dir.mkdir()
    for index in range(12):
        (database_dir / f"nr{index:02d}.dmnd").write_text("diamond", encoding="utf-8")

    template = {"pathKind": "file", "anyPatterns": ["*.dmnd"]}
    resolved = database_validation.resolve_template_path(database_dir, template)

    assert "ambiguousCandidates" in resolved
    assert "还有" in str(resolved["ambiguousCandidates"])


def test_prefix_template_directory_rejects_multiple_complete_prefixes(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "bowtie2"
    database_dir.mkdir()
    for prefix in ("human", "mouse"):
        for suffix in (".1.bt2", ".2.bt2", ".3.bt2", ".4.bt2", ".rev.1.bt2", ".rev.2.bt2"):
            (database_dir / f"{prefix}{suffix}").write_text("index", encoding="utf-8")

    template = {"pathKind": "prefix", "prefixPatternSets": [[".1.bt2", ".2.bt2", ".3.bt2", ".4.bt2", ".rev.1.bt2", ".rev.2.bt2"]]}
    resolved = database_validation.resolve_template_path(database_dir, template)

    assert "ambiguousCandidates" in resolved
    assert "multiple candidate targets" in database_validation.validate_template_files(
        database_dir,
        {"metadata": {"templateId": "bowtie2"}},
        template,
        resolved=resolved,
    )


def test_verified_database_add_returns_structured_candidates_for_multiple_blast_prefixes(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "blast"
    database_dir.mkdir()
    for prefix in ("core_nt.00", "core_nt.01"):
        for suffix in (".nhr", ".nin", ".nsq"):
            (database_dir / f"{prefix}{suffix}").write_text("index", encoding="utf-8")

    try:
        add_verified_reference_database(
            cfg,
            {"id": "blast-core", "name": "BLAST core", "templateId": "blast", "path": str(database_dir)},
        )
    except DatabaseRegistryError as exc:
        message = str(exc)
        assert message.startswith("DATABASE_CANDIDATES:")
        payload = json.loads(message.removeprefix("DATABASE_CANDIDATES:"))
        assert payload["status"] == "multiple_candidates"
        assert [candidate["entryPath"] for candidate in payload["candidates"]] == [
            str(database_dir / "core_nt.00"),
            str(database_dir / "core_nt.01"),
        ]
    else:
        raise AssertionError("expected multiple candidate response")


def test_verified_database_add_accepts_selected_candidate_prefix(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "blast"
    database_dir.mkdir()
    for prefix in ("core_nt.00", "core_nt.01"):
        for suffix in (".nhr", ".nin", ".nsq"):
            (database_dir / f"{prefix}{suffix}").write_text("index", encoding="utf-8")

    selected = str(database_dir / "core_nt.01")
    saved = add_verified_reference_database(
        cfg,
        {
            "id": "blast-core",
            "name": "BLAST core",
            "templateId": "blast",
            "path": str(database_dir),
            "selectedEntryPath": selected,
        },
    )

    assert saved["status"] == "available"
    assert saved["inputPath"] == str(database_dir)
    assert saved["entryPath"] == selected
    assert saved["metadata"]["resolvedCandidate"]["entryPath"] == selected


def test_verified_database_add_prefers_blast_alias_prefix_over_volume_prefixes(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "blast"
    database_dir.mkdir()
    (database_dir / "core_nt.nal").write_text("alias", encoding="utf-8")
    for index in range(3):
        for suffix in (".nhr", ".nin", ".nsq"):
            (database_dir / f"core_nt.{index:02d}{suffix}").write_text("index", encoding="utf-8")

    saved = add_verified_reference_database(
        cfg,
        {"id": "blast-core", "name": "BLAST core", "templateId": "blast", "path": str(database_dir)},
    )

    assert saved["status"] == "available"
    assert saved["inputPath"] == str(database_dir)
    assert saved["entryPath"] == str(database_dir / "core_nt")
    assert saved["metadata"]["resolvedCandidate"]["entryPath"] == str(database_dir / "core_nt")
    assert saved["metadata"]["resolvedCandidate"]["evidence"] == ["core_nt.nal"]




def test_directory_template_resolution_prefers_index_prefix_over_metadata_file(tmp_path: Path) -> None:
    from apps.remote_runner import database_validation

    database_dir = tmp_path / "metaphlan"
    database_dir.mkdir()
    (database_dir / "markers.pkl").write_text("metadata", encoding="utf-8")
    (database_dir / "mpa.1.bt2").write_text("index", encoding="utf-8")

    resolved = database_validation.resolve_template_path(
        database_dir,
        {"pathKind": "directory", "anyPatterns": ["*.pkl"], "anyIndexPatterns": ["*.bt2"]},
    )

    assert resolved["firstMatch"] == str(database_dir / "mpa.1.bt2")
    assert resolved["firstIndexPrefix"] == str(database_dir / "mpa")


def test_bracken_registration_keeps_directory_as_resolved_path_and_lists_read_lengths(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    case_root = tmp_path / "reference-database-contracts"
    cases = {case.case_id: case for case in iter_workflow_resource_contract_cases(case_root)}
    database_dir = Path(cases["directory-kraken2"].database_path)
    for read_length in (50, 150, 300):
        (database_dir / f"database{read_length}mers.kmer_distrib").write_text("bracken", encoding="utf-8")

    add_reference_database(
        cfg,
        {
            "id": "bracken-standard",
            "name": "Bracken standard",
            "templateId": "bracken",
            "path": str(database_dir),
        },
    )

    checked = check_reference_database(cfg, "bracken-standard")
    assert checked["status"] == "available"
    assert checked["metadata"]["resolvedPath"] == {"kind": "directory", "path": str(database_dir)}
    _assert_resolution_contract(
        checked,
        input_path=database_dir,
        entry_path=database_dir,
        path_mode="directory",
        resolved_path={"kind": "directory", "path": str(database_dir)},
        input_value={"kind": "single", "path": str(database_dir)},
        input_kind="single",
    )
    assert checked["metadata"]["availableReadLengths"] == [50, 150, 300]


def test_blast_directory_selection_resolves_alias_prefix_for_injection(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "core_nt_database"
    database_dir.mkdir()
    (database_dir / "core_nt.nal").write_text("TITLE core nt\nDBLIST core_nt.00\n", encoding="utf-8")
    for suffix in ("nhr", "nin", "nsq"):
        (database_dir / f"core_nt.00.{suffix}").write_text("blast", encoding="utf-8")

    add_reference_database(
        cfg,
        {
            "id": "blast-core-nt",
            "name": "BLAST core nt",
            "templateId": "blast",
            "path": str(database_dir),
        },
    )

    checked = check_reference_database(cfg, "blast-core-nt")
    assert checked["status"] == "available"
    assert checked["path"] == str(database_dir)
    assert checked["metadata"]["resolvedPath"]["prefix"] == str(database_dir / "core_nt")
    _assert_resolution_contract(
        checked,
        input_path=database_dir,
        entry_path=database_dir / "core_nt",
        path_mode="prefix",
        resolved_path=checked["metadata"]["resolvedPath"],
    )
    assert checked["metadata"]["input"] == {"kind": "single", "path": str(database_dir)}
    assert checked["metadata"]["resolved"] == {"default": str(database_dir / "core_nt")}
    assert checked["input"] == {"kind": "single", "path": str(database_dir)}
    assert checked["resolved"] == {"default": str(database_dir / "core_nt")}

    resolved = resolve_run_databases(cfg, {"databases": [{"id": "blast-core-nt", "role": "blast"}]})
    assert resolved["blast"]["path"] == str(database_dir / "core_nt")
    assert resolved["blast"]["input"] == {"kind": "single", "path": str(database_dir)}
    assert resolved["blast"]["resolved"] == {"default": str(database_dir / "core_nt")}
    _assert_resolution_contract(
        resolved["blast"],
        input_path=database_dir,
        entry_path=database_dir / "core_nt",
        path_mode="prefix",
    )


def test_file_template_directory_selection_injects_resolved_file_path(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = tmp_path / "diamond"
    database_dir.mkdir()
    database_file = database_dir / "nr.dmnd"
    database_file.write_text("diamond", encoding="utf-8")

    add_reference_database(
        cfg,
        {
            "id": "diamond-nr",
            "name": "DIAMOND nr",
            "templateId": "diamond",
            "path": str(database_dir),
        },
    )

    checked = check_reference_database(cfg, "diamond-nr")
    assert checked["status"] == "available"
    assert checked["path"] == str(database_dir)
    assert checked["metadata"]["resolvedPath"]["path"] == str(database_file)
    _assert_resolution_contract(
        checked,
        input_path=database_dir,
        entry_path=database_file,
        path_mode="file",
        resolved_path=checked["metadata"]["resolvedPath"],
    )

    resolved = resolve_run_databases(cfg, {"databases": [{"id": "diamond-nr", "role": "protein"}]})
    assert resolved["protein"]["path"] == str(database_file)
    _assert_resolution_contract(
        resolved["protein"],
        input_path=database_dir,
        entry_path=database_file,
        path_mode="file",
    )


def test_mmseqs2_template_matches_createdb_prefix_outputs() -> None:
    from apps.remote_runner.database_templates import list_database_templates

    templates = {item["id"]: item for item in list_database_templates()}

    assert "prefix.dbtype + prefix_h + prefix_h.dbtype" in templates["mmseqs2"]["expectedFiles"]


def test_resolve_run_databases_revalidates_template_before_injection(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    database_dir = _make_kraken2_database(tmp_path / "taxonomy-db")
    add_reference_database(cfg, {"id": "taxonomy-db", "name": "Taxonomy DB", "templateId": "kraken2", "path": str(database_dir)})
    checked = check_reference_database(cfg, "taxonomy-db")
    assert checked["status"] == "available"

    (database_dir / "taxo.k2d").unlink()

    try:
        resolve_run_databases(cfg, {"databases": [{"id": "taxonomy-db", "role": "taxonomy"}]})
    except ValueError as exc:
        assert "DATABASE_UNAVAILABLE" in str(exc)
    else:
        raise AssertionError("database injection should revalidate template files before use")
