from __future__ import annotations

import fnmatch
import asyncio
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import (
    DATABASE_TEMPLATES,
    DatabaseRegistryError,
    add_reference_database,
    add_verified_reference_database,
    check_reference_database,
    list_database_templates,
    list_reference_databases,
    remove_reference_database,
    resolve_run_databases,
    update_reference_database,
)


def _patch_tool_probe_success(monkeypatch) -> list[str]:
    from apps.remote_runner import database_validation

    calls: list[str] = []

    monkeypatch.setattr(
        database_validation,
        "prepare_tool_probe_command",
        lambda cfg, template_id, template, command: command,
    )

    def fake_probe(command: str, *, timeout: int) -> database_validation.ToolProbeResult:
        calls.append(command)
        return database_validation.ToolProbeResult(ok=True, command=command, stdout="probe ok", stderr="", returncode=0)

    monkeypatch.setattr(database_validation, "run_tool_probe", fake_probe)
    return calls


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="database-registry-token",
        data_root=str(tmp_path / "shared"),
        db_path=str(tmp_path / "shared" / "data" / "runner.db"),
        uploads_dir=str(tmp_path / "shared" / "uploads"),
        results_dir=str(tmp_path / "shared" / "results"),
        work_dir=str(tmp_path / "shared" / "work"),
        logs_dir=str(tmp_path / "shared" / "logs"),
        release_dir=str(Path.cwd() / "apps" / "remote_runner"),
        managed_conda_command=str(tmp_path / "workflow-env" / "bin" / "conda"),
        snakemake_command=str(tmp_path / "workflow-env" / "bin" / "snakemake"),
    )


def _example_name_for_pattern(pattern: str) -> str:
    examples = {
        "*.amb": "ref.amb",
        "*.ann": "ref.ann",
        "*.bwt": "ref.bwt",
        "*.pac": "ref.pac",
        "*.sa": "ref.sa",
        "*.bt2": "index.bt2",
        "*.bt2l": "index.bt2l",
        "*.cf": "index.cf",
        "*.fmi": "proteins.fmi",
        "*.dmnd": "nr.dmnd",
        "*.db": "eggnog.db",
        "*.sqlite": "eggnog.sqlite",
        "*.sig": "sketch.sig",
        "*.sbt.zip": "sketch.sbt.zip",
        "*.zip": "archive.zip",
        "*.msh": "db.msh",
        "*.hmm": "Pfam-A.hmm",
        "*.h3f": "Pfam-A.h3f",
        "*.h3i": "Pfam-A.h3i",
        "*.h3m": "Pfam-A.h3m",
        "*.h3p": "Pfam-A.h3p",
        "*.idx": "transcriptome.idx",
        "*.qza": "silva.qza",
        "*.fasta": "reference.fasta",
        "*.fa": "reference.fa",
        "*.fna": "reference.fna",
        "*.ffn": "genes.ffn",
        "*.faa": "proteins.faa",
        "*.pkl": "db.pkl",
        "*.tsv": "table.tsv",
        "*.txt": "notes.txt",
        "*_h": "target_h",
        "*_seq": "target_seq",
        "*.dbtype": "target.dbtype",
        "*.ht2": "genome.ht2",
        "*.ht2l": "genome.ht2l",
        "database*.kmer_distrib": "database100mers.kmer_distrib",
        "chocophlan/**/*.ffn*": "chocophlan/genome.ffn.gz",
        "uniref/**/*.dmnd": "uniref/uniref90_201901.dmnd",
        "utility_mapping/map_*": "utility_mapping/map_uniref90_name.txt.gz",
        "uniref100.KO*.dmnd": "uniref100.KO.1.dmnd",
        "eggnog_proteins.dmnd": "eggnog_proteins.dmnd",
    }
    if pattern in examples:
        return examples[pattern]
    fallback = pattern.replace("*", "x").replace("?", "q")
    if fnmatch.fnmatch(fallback, pattern):
        return fallback
    return f"example-{abs(hash(pattern)) % 10000}"


def _materialize_template_path(base_dir: Path, template_id: str) -> Path:
    template = DATABASE_TEMPLATES[template_id]
    path_kind = str(template["pathKind"])
    if path_kind == "directory":
        target = base_dir / template_id
        target.mkdir(parents=True, exist_ok=True)
        if template_id == "custom":
            (target / "README.txt").write_text("custom", encoding="utf-8")
    elif path_kind == "prefix":
        target = base_dir / template_id / "index"
        target.parent.mkdir(parents=True, exist_ok=True)
    elif path_kind == "primary_with_sidecars":
        target = base_dir / template_id / "reference.fa"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(">ref\nACGT\n", encoding="utf-8")
    elif path_kind == "composite":
        target = base_dir / template_id
        target.mkdir(parents=True, exist_ok=True)
        fields = template.get("fields") or {}
        for field_key, field_spec in fields.items():
            hint_name = Path(str(field_spec.get("pathHint") or "")).name
            field_kind = str(field_spec.get("pathKind") or "directory")
            field_path = target if len(fields) == 1 and field_kind == "directory" else target / (hint_name or str(field_key))
            validation = field_spec.get("validation") or {}
            if field_kind == "file":
                filename = str((field_spec.get("resolve") or {}).get("fileName") or validation.get("requiredFileName") or field_path.name)
                if field_path.suffix:
                    file_path = field_path
                else:
                    field_path.mkdir(parents=True, exist_ok=True)
                    file_path = field_path / filename
                file_path.write_text("database", encoding="utf-8")
            else:
                field_path.mkdir(parents=True, exist_ok=True)
                for pattern in validation.get("requiredGlobs") or []:
                    path = field_path / _example_name_for_pattern(str(pattern))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(str(pattern), encoding="utf-8")
    else:
        file_patterns: list[str] = []
        file_patterns.extend(str(item) for item in template.get("anyPatterns", []) if str(item).strip())
        file_patterns.extend(str(item) for item in template.get("requiredPatterns", []) if str(item).strip())
        file_patterns.extend(str(item) for item in template.get("anyIndexPatterns", []) if str(item).strip())
        for pattern_set in template.get("anyPatternSets", []):
            file_patterns.extend(str(item) for item in pattern_set if str(item).strip())
        filename = _example_name_for_pattern(file_patterns[0]) if file_patterns else f"{template_id}.dat"
        target = base_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template_id, encoding="utf-8")
        if template_id == "custom":
            return target
    container = target if target.is_dir() else target.parent

    for filename in template.get("requiredFiles", []):
        path = container / str(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(filename, encoding="utf-8")
    for pattern in template.get("requiredPatterns", []):
        path = container / _example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pattern, encoding="utf-8")
    if not target.is_dir():
        base = target.with_suffix("")
        for suffix in template.get("companionSuffixes", []):
            Path(str(base) + str(suffix)).write_text(str(suffix), encoding="utf-8")
        for suffix in template.get("indexSuffixes", []):
            Path(str(target) + str(suffix)).write_text(str(suffix), encoding="utf-8")
    for pattern in template.get("anyPatterns", []):
        path = container / _example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pattern, encoding="utf-8")
        break
    for pattern_set in template.get("prefixPatternSets", []):
        for suffix in pattern_set:
            Path(str(target) + str(suffix)).write_text(str(suffix), encoding="utf-8")
        break
    for pattern in template.get("anyIndexPatterns", []):
        path = container / _example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pattern, encoding="utf-8")
        break
    for filename in template.get("anyFiles", []):
        path = container / str(filename)
        if "." not in str(filename):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(filename, encoding="utf-8")
        break
    for pattern_set in template.get("anyPatternSets", []):
        for pattern in pattern_set:
            path = container / _example_name_for_pattern(str(pattern))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(pattern, encoding="utf-8")
        break
    return target


def test_reference_database_registry_checks_remote_path(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2-mini"
    database_dir.mkdir()
    (database_dir / "hash.k2d").write_text("mini", encoding="utf-8")

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


def test_verified_reference_database_add_rejects_invalid_kraken2_database(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2-incomplete"
    database_dir.mkdir()
    (database_dir / "hash.k2d").write_text("mini", encoding="utf-8")

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
    probe_calls = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    valid_dir = tmp_path / "kraken2-valid"
    valid_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (valid_dir / filename).write_text("mini", encoding="utf-8")

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

    invalid_dir = tmp_path / "kraken2-invalid"
    invalid_dir.mkdir()
    (invalid_dir / "hash.k2d").write_text("mini", encoding="utf-8")

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
    assert len(probe_calls) >= 1


def test_verified_reference_database_add_requires_template(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
    probe_calls = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2-complete"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text("mini", encoding="utf-8")

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
    assert len(probe_calls) == 1
    assert "kraken2-inspect --db" in probe_calls[0]
    assert str(database_dir) in probe_calls[0]


def test_verified_reference_database_add_rejects_tool_probe_failure(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import database_validation

    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2-probe-fails"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text("mini", encoding="utf-8")

    def failing_probe(command: str, *, timeout: int) -> database_validation.ToolProbeResult:
        return database_validation.ToolProbeResult(ok=False, command=command, stdout="", stderr="bad database", returncode=2)

    monkeypatch.setattr(database_validation, "prepare_tool_probe_command", lambda cfg_arg, template_id, template, command: command)
    monkeypatch.setattr(database_validation, "run_tool_probe", failing_probe)

    try:
        add_verified_reference_database(
            cfg,
            {
                "id": "kraken2-probe-fails",
                "name": "Kraken2 Probe Fails",
                "templateId": "kraken2",
                "path": str(database_dir),
            },
        )
    except DatabaseRegistryError as exc:
        assert "Tool probe failed" in str(exc)
        assert "bad database" in str(exc)
    else:
        raise AssertionError("tool probe failure should reject verified add")

    assert list_reference_databases(cfg) == []


def test_remote_runner_database_post_returns_only_available_after_validation(tmp_path: Path, monkeypatch) -> None:
    probe_calls = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    monkeypatch.setattr("apps.remote_runner.main.load_remote_runner_config", lambda: cfg)
    database_dir = tmp_path / "kraken2-api"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text("mini", encoding="utf-8")

    from apps.remote_runner.main import DatabaseManifestRequest, add_database

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
    assert item["metadata"]["validation"]["toolProbe"]["returncode"] == 0
    assert probe_calls and "kraken2-inspect" in probe_calls[0]


def test_remote_runner_database_post_rejects_invalid_database_without_registering(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    monkeypatch.setattr("apps.remote_runner.main.load_remote_runner_config", lambda: cfg)
    database_dir = tmp_path / "kraken2-api-invalid"
    database_dir.mkdir()
    (database_dir / "hash.k2d").write_text("mini", encoding="utf-8")

    from fastapi import HTTPException

    from apps.remote_runner.main import DatabaseManifestRequest, add_database

    payload = DatabaseManifestRequest(
        id="kraken2-api-invalid",
        name="Kraken2 API Invalid",
        templateId="kraken2",
        path=str(database_dir),
    )

    try:
        asyncio.run(add_database(payload, authorization=f"Bearer {cfg.token}"))
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "opts.k2d" in str(exc.detail)
    else:
        raise AssertionError("invalid database should fail the add endpoint")
    assert list_reference_databases(cfg) == []


def test_verified_reference_database_add_restores_existing_record_when_replacement_is_invalid(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    valid_dir = tmp_path / "kraken2-valid"
    valid_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (valid_dir / filename).write_text("mini", encoding="utf-8")
    invalid_dir = tmp_path / "kraken2-invalid"
    invalid_dir.mkdir()
    (invalid_dir / "hash.k2d").write_text("mini", encoding="utf-8")

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
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2-mini"
    database_dir.mkdir()
    (database_dir / "hash.k2d").write_text("mini", encoding="utf-8")

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
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2-template"
    database_dir.mkdir()
    (database_dir / "hash.k2d").write_text("mini", encoding="utf-8")

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
        assert api_item["toolProbe"]["commandTemplate"], f"{template_id} should declare a real tool probe"
        assert api_item["toolProbe"]["packageSpec"], f"{template_id} should declare the package needed for real validation"


def test_builtin_templates_accept_directory_selection_and_resolve_tool_target(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)

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
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    fasta = tmp_path / "bwa" / "hg38.fa"
    fasta.parent.mkdir()
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in (".amb", ".ann", ".bwt", ".pac", ".sa"):
        Path(str(fasta) + suffix).write_text("index", encoding="utf-8")

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
    assert saved["inputPath"] == str(fasta)
    assert saved["entryPath"] == str(fasta)
    assert saved["pathMode"] == "primary_with_sidecars"
    assert saved["resolvedPath"] == saved["metadata"]["resolvedPath"]
    assert saved["metadata"]["inputPath"] == str(fasta)
    assert saved["metadata"]["entryPath"] == str(fasta)
    assert saved["metadata"]["pathMode"] == "primary_with_sidecars"

    resolved = resolve_run_databases(cfg, {"databases": [{"id": "bwa-hg38", "role": "bwa_ref"}]})
    assert resolved["bwa_ref"]["path"] == str(fasta)
    assert resolved["bwa_ref"]["inputPath"] == str(fasta)
    assert resolved["bwa_ref"]["entryPath"] == str(fasta)
    assert resolved["bwa_ref"]["pathMode"] == "primary_with_sidecars"


def test_bwa_template_rejects_selecting_index_file_instead_of_fasta(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    fasta = tmp_path / "bwa" / "hg38.fa"
    fasta.parent.mkdir()
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in (".amb", ".ann", ".bwt", ".pac", ".sa"):
        Path(str(fasta) + suffix).write_text("index", encoding="utf-8")

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
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
