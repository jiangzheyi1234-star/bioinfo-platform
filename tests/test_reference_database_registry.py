from __future__ import annotations

import json
import fnmatch
from pathlib import Path
from typing import Any

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import (
    DATABASE_TEMPLATES,
    DatabaseRegistryError,
    add_reference_database,
    check_reference_database,
    list_database_templates,
    list_reference_databases,
    remove_reference_database,
    resolve_run_databases,
)
from apps.remote_runner.executor import run_snakemake_execution
from apps.remote_runner.generated_workflow import GENERATED_TOOL_RUN_PIPELINE_ID
from apps.remote_runner.storage import persist_upload, upsert_tool
from core.remote_runner.manager import RemoteRunnerManager


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
        assert api_item["name"] == template["label"]
        assert api_item["pathHint"] == template["pathHint"]
        assert isinstance(api_item["expectedFiles"], list)
        assert api_item["selector"]["kind"] in {"directory", "file", "prefix"}
        assert api_item["selectorKind"] == api_item["selector"]["kind"]
        assert template["pathKind"] in {"directory", "file", "prefix"}

        has_validation_rule = any(
            template.get(key)
            for key in (
                "requiredFiles",
                "requiredPatterns",
                "anyPatterns",
                "anyIndexPatterns",
                "anyFiles",
                "anyPatternSets",
                "prefixPatternSets",
                "companionSuffixes",
            )
        )
        if template_id == "custom":
            assert template["pathKind"] in {"directory", "file"}
            continue
        assert has_validation_rule, f"{template_id} should declare at least one validation rule"
        assert api_item["toolProbe"]["commandTemplate"], f"{template_id} should declare a real tool probe"
        assert api_item["toolProbe"]["packageSpec"], f"{template_id} should declare the package needed for real validation"


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


def test_hmmer_pfam_template_accepts_hmmpress_index(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "pfam"
    database_dir.mkdir()
    hmm_path = database_dir / "Pfam-A.hmm"
    hmm_path.write_text("hmm", encoding="utf-8")
    for suffix in ("h3f", "h3i", "h3m"):
        (database_dir / f"Pfam-A.{suffix}").write_text("index", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "pfam",
            "name": "Pfam",
            "templateId": "hmmer_pfam",
            "path": str(hmm_path),
        },
    )

    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "h3p" in missing["message"]

    (database_dir / "Pfam-A.h3p").write_text("index", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_directory_templates_accept_required_files_with_matching_pattern(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kaiju"
    database_dir.mkdir()
    (database_dir / "nodes.dmp").write_text("nodes", encoding="utf-8")
    (database_dir / "names.dmp").write_text("names", encoding="utf-8")
    (database_dir / "proteins.fmi").write_text("fmi", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "kaiju-db",
            "name": "Kaiju DB",
            "templateId": "kaiju",
            "path": str(database_dir),
        },
    )

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_single_file_database_templates_validate_file_suffix(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    wrong_file = tmp_path / "random.txt"
    wrong_file.write_text("not a diamond database", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "diamond-file",
            "name": "DIAMOND file",
            "templateId": "diamond",
            "path": str(wrong_file),
        },
    )
    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "*.dmnd" in missing["message"]

    diamond_file = tmp_path / "nr.dmnd"
    diamond_file.write_text("diamond", encoding="utf-8")
    updated = add_reference_database(
        cfg,
        {
            "id": "diamond-file",
            "name": "DIAMOND file",
            "templateId": "diamond",
            "path": str(diamond_file),
        },
    )
    checked = check_reference_database(cfg, updated["id"])
    assert checked["status"] == "available"


def test_directory_database_templates_reject_file_paths(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    file_path = tmp_path / "hash.k2d"
    file_path.write_text("kraken", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "kraken-file",
            "name": "Kraken file",
            "templateId": "kraken2",
            "path": str(file_path),
        },
    )

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "missing"
    assert "requires a directory" in checked["message"]


def test_declared_database_cannot_be_resolved_for_generated_workflow(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "taxonomy-db"
    database_dir.mkdir()
    add_reference_database(
        cfg,
        {
            "id": "taxonomy-db",
            "name": "Taxonomy DB",
            "type": "taxonomy",
            "path": str(database_dir),
            "status": "declared",
        },
    )
    try:
        resolve_run_databases(cfg, {"databases": [{"id": "taxonomy-db", "role": "taxonomy"}]})
    except ValueError as exc:
        assert "DATABASE_UNAVAILABLE" in str(exc)
    else:
        raise AssertionError("declared database should not be usable without validation")


def test_generated_workflow_rejects_legacy_single_database_field(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "taxonomy-db"
    database_dir.mkdir()
    add_reference_database(
        cfg,
        {
            "id": "taxonomy-db",
            "name": "Taxonomy DB",
            "type": "taxonomy",
            "path": str(database_dir),
            "status": "available",
        },
    )

    assert resolve_run_databases(cfg, {"database": {"id": "taxonomy-db", "role": "taxonomy"}}) == {}


def test_legacy_dbtype_field_is_rejected(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "legacy-dbtype"
    database_dir.mkdir()

    try:
        add_reference_database(
            cfg,
            {
                "id": "legacy-dbtype",
                "name": "Legacy dbType",
                "dbType": "taxonomy",
                "path": str(database_dir),
            },
        )
    except DatabaseRegistryError as exc:
        assert "DATABASE_FIELD_UNSUPPORTED" in str(exc)
    else:
        raise AssertionError("legacy dbType alias should be rejected")


def test_custom_database_template_uses_declared_expected_files(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "custom-db"
    database_dir.mkdir()
    (database_dir / "README.txt").write_text("custom", encoding="utf-8")

    saved = add_reference_database(
        cfg,
        {
            "id": "custom-db",
            "name": "Custom DB",
            "templateId": "custom",
            "path": str(database_dir),
            "metadata": {"expectedFiles": ["manifest.json"]},
        },
    )
    missing = check_reference_database(cfg, saved["id"])
    assert missing["status"] == "missing"
    assert "manifest.json" in missing["message"]

    (database_dir / "manifest.json").write_text("{}", encoding="utf-8")
    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "available"


def test_generated_workflow_writes_database_config_and_path_token(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "taxonomy-db"
    database_dir.mkdir()
    (database_dir / "manifest.txt").write_text("taxonomy", encoding="utf-8")
    add_reference_database(
        cfg,
        {
            "id": "taxonomy-db",
            "name": "Taxonomy DB",
            "type": "taxonomy",
            "version": "v1",
            "path": str(database_dir),
            "status": "available",
        },
    )
    upsert_tool(
        cfg,
        {
            "id": "conda-forge::coreutils-db",
            "name": "coreutils",
            "source": "conda-forge",
            "sourceLabel": "conda-forge",
            "version": "9.5",
            "packageSpec": "conda-forge::coreutils=9.5",
            "targetPlatform": "linux-64",
            "targetPlatformSupported": True,
            "ruleTemplate": {
                "commandTemplate": "printf '%s\\n' {database.taxonomy.path:q} > {output.tool_output:q}",
                "inputs": [{"name": "primary", "type": "file", "required": True}],
                "outputs": [{"name": "tool_output", "path": "database-path.txt", "kind": "log", "mimeType": "text/plain"}],
            },
        },
    )
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    run_snakemake_execution(
        cfg,
        run_id="run_database_config",
        request_id="req_database_config",
        run_spec={
            "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
            "projectId": "proj_demo",
            "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
            "databases": [{"id": "taxonomy-db", "role": "taxonomy"}],
            "tool": {"id": "conda-forge::coreutils-db"},
        },
    )

    work_dir = Path(cfg.work_dir) / "run_database_config"
    run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
    snakefile = (work_dir / "Snakefile").read_text(encoding="utf-8")

    assert run_config["databases"]["taxonomy"]["path"] == str(database_dir)
    assert str(database_dir) in snakefile
    assert "{database.taxonomy.path:q}" not in snakefile


def test_every_database_template_can_be_checked_and_injected_into_generated_workflow(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    upload = persist_upload(
        cfg,
        filename="reads.txt",
        content_base64="QUJDREVGCg==",
        mime_type="text/plain",
    )

    class Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr("apps.remote_runner.executor.subprocess.run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr("apps.remote_runner.executor._collect_artifacts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("apps.remote_runner.executor.update_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.remote_runner.executor.append_log_lines", lambda *args, **kwargs: None)

    for template_id, template in DATABASE_TEMPLATES.items():
        path = _materialize_template_path(tmp_path / "template-fixtures", template_id)
        database_id = f"{template_id}-fixture"
        role = "db"
        add_reference_database(
            cfg,
            {
                "id": database_id,
                "name": f"{template_id} fixture",
                "templateId": template_id,
                "path": str(path),
                "status": "declared",
                "metadata": {"templateId": template_id},
            },
        )
        checked = check_reference_database(cfg, database_id)
        assert checked["status"] == "available", f"{template_id} should validate with fixture path {path}"

        tool_id = f"conda-forge::coreutils-{template_id}"
        upsert_tool(
            cfg,
            {
                "id": tool_id,
                "name": "coreutils",
                "source": "conda-forge",
                "sourceLabel": "conda-forge",
                "version": "9.5",
                "packageSpec": "conda-forge::coreutils=9.5",
                "targetPlatform": "linux-64",
                "targetPlatformSupported": True,
                "ruleTemplate": {
                    "commandTemplate": f"printf '%s\\n' {{database.{role}.path:q}} > {{output.tool_output:q}}",
                    "inputs": [{"name": "primary", "type": "file", "required": True}],
                    "outputs": [{"name": "tool_output", "path": f"{template_id}-database-path.txt", "kind": "log", "mimeType": "text/plain"}],
                },
            },
        )

        run_id = f"run_{template_id}_database_path"
        run_snakemake_execution(
            cfg,
            run_id=run_id,
            request_id=f"req_{template_id}",
            run_spec={
                "pipelineId": GENERATED_TOOL_RUN_PIPELINE_ID,
                "projectId": "proj_template_matrix",
                "inputs": [{"uploadId": upload["uploadId"], "filename": "reads.txt", "role": "input"}],
                "databases": [{"id": database_id, "role": role}],
                "tool": {"id": tool_id},
            },
        )

        work_dir = Path(cfg.work_dir) / run_id
        run_config = json.loads((work_dir / "run-config.json").read_text(encoding="utf-8"))
        snakefile = (work_dir / "Snakefile").read_text(encoding="utf-8")
        assert run_config["databases"][role]["path"] == str(path)
        assert str(path) in snakefile
        assert f"{{database.{role}.path:q}}" not in snakefile


def test_remote_runner_manager_database_catalog_routes(monkeypatch) -> None:
    manager = RemoteRunnerManager()
    calls: list[tuple[str, str, Any]] = []

    class FakeClient:
        def get_json(self, path: str) -> dict[str, Any]:
            calls.append(("GET", path, None))
            return {"data": {"items": [{"id": "db1"}]}}

        def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            calls.append(("POST", path, payload))
            return {"data": {"id": "db1", **payload}}

        def delete_json(self, path: str) -> dict[str, Any]:
            calls.append(("DELETE", path, None))
            return {"data": {"id": "db1", "deleted": True}}

    monkeypatch.setattr(manager, "_get_client", lambda **_kwargs: FakeClient())
    kwargs = {"server_id": "srv", "ssh_service": object(), "server_record": {}}

    assert manager.list_databases(**kwargs) == [{"id": "db1"}]
    assert manager.list_database_templates(**kwargs) == [{"id": "db1"}]
    assert manager.add_database(**kwargs, payload={"name": "db1"})["name"] == "db1"
    assert manager.check_database(**kwargs, database_id="db1")["id"] == "db1"
    assert manager.delete_database(**kwargs, database_id="db1")["deleted"] is True
    assert calls == [
        ("GET", "/api/v1/databases", None),
        ("GET", "/api/v1/database-templates", None),
        ("POST", "/api/v1/databases", {"name": "db1"}),
        ("POST", "/api/v1/databases/db1/check", {}),
        ("DELETE", "/api/v1/databases/db1", None),
    ]
