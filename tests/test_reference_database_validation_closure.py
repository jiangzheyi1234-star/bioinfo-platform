from __future__ import annotations

import os
import shlex
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import add_reference_database, check_reference_database, resolve_run_databases


def _cfg(tmp_path: Path) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token="database-validation-token",
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


def _patch_tool_probe_success(monkeypatch) -> list[str]:
    from apps.remote_runner import database_validation

    calls: list[str] = []
    monkeypatch.setattr(database_validation, "prepare_tool_probe_command", lambda cfg, template_id, template, command: command)

    def fake_probe(command: str, *, timeout: int) -> database_validation.ToolProbeResult:
        calls.append(command)
        return database_validation.ToolProbeResult(ok=True, command=command, stdout="probe ok", stderr="", returncode=0)

    monkeypatch.setattr(database_validation, "run_tool_probe", fake_probe)
    return calls


def test_prefix_database_templates_require_complete_index_sets(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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


def test_template_tool_probe_must_succeed_before_database_is_available(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import database_validation

    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "kraken2"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text(filename, encoding="utf-8")

    commands: list[str] = []

    def failing_probe(command: str, *, timeout: int) -> database_validation.ToolProbeResult:
        commands.append(command)
        return database_validation.ToolProbeResult(ok=False, command=command, stdout="", stderr="bad database", returncode=2)

    monkeypatch.setattr(database_validation, "prepare_tool_probe_command", lambda cfg_arg, template_id, template, command: command)
    monkeypatch.setattr(database_validation, "run_tool_probe", failing_probe)
    saved = add_reference_database(
        cfg,
        {"id": "kraken2-real-probe", "name": "Kraken2 real probe", "templateId": "kraken2", "path": str(database_dir)},
    )

    checked = check_reference_database(cfg, saved["id"])
    assert checked["status"] == "failed"
    assert "Tool probe failed" in checked["message"]
    assert commands and "kraken2-inspect" in commands[0]
    assert checked["metadata"]["validation"]["toolProbe"]["returncode"] == 2


def test_template_tool_probe_runs_inside_template_conda_environment(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import database_validation

    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    conda = Path(cfg.managed_conda_command)
    conda.parent.mkdir(parents=True, exist_ok=True)
    conda.write_text("conda", encoding="utf-8")
    database_dir = tmp_path / "kraken2"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text(filename, encoding="utf-8")

    envs: list[tuple[str, str]] = []
    commands: list[str] = []

    def fake_ensure(cfg_arg, *, template_id: str, package_spec: str) -> Path:
        envs.append((template_id, package_spec))
        env_dir = Path(cfg_arg.data_root) / "probe-envs" / template_id
        env_dir.mkdir(parents=True, exist_ok=True)
        return env_dir

    def fake_probe(command: str, *, timeout: int) -> database_validation.ToolProbeResult:
        commands.append(command)
        return database_validation.ToolProbeResult(ok=True, command=command, stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr(database_validation, "ensure_probe_environment", fake_ensure)
    monkeypatch.setattr(database_validation, "run_tool_probe", fake_probe)
    saved = add_reference_database(cfg, {"id": "kraken2-env-probe", "name": "Kraken2 env probe", "templateId": "kraken2", "path": str(database_dir)})

    checked = check_reference_database(cfg, saved["id"])

    assert checked["status"] == "available"
    assert envs == [("kraken2", "bioconda::kraken2")]
    assert str(conda) in commands[0]
    assert f"PATH={shlex.quote(str(conda.parent))}:$PATH" in commands[0]
    assert f"CONDA_EXE={shlex.quote(str(conda))}" in commands[0]
    assert " run -p " in commands[0]
    assert "kraken2-inspect" in commands[0]


def test_probe_environment_creation_exports_conda_bin_on_path(tmp_path: Path, monkeypatch) -> None:
    from apps.remote_runner import database_validation

    cfg = _cfg(tmp_path)
    conda = Path(cfg.managed_conda_command)
    conda.parent.mkdir(parents=True, exist_ok=True)
    conda.write_text("conda", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class Completed:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append({"args": args, "env": kwargs.get("env")})
        env_path = Path(args[4])
        env_path.mkdir(parents=True, exist_ok=True)
        return Completed()

    monkeypatch.setattr(database_validation.subprocess, "run", fake_run)

    env_path = database_validation.ensure_probe_environment(cfg, template_id="blast", package_spec="bioconda::blast")

    assert env_path == Path(cfg.data_root) / "database-probe-envs" / "blast"
    assert calls
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert str(conda.parent) == str(env["PATH"]).split(os.pathsep)[0]
    assert env["CONDA_EXE"] == str(conda)


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


def test_blast_directory_selection_resolves_alias_prefix_for_probe_and_injection(tmp_path: Path, monkeypatch) -> None:
    commands = _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
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
    assert commands and "blastdbcmd -db" in commands[-1]
    assert str(database_dir / "core_nt") in commands[-1]

    resolved = resolve_run_databases(cfg, {"databases": [{"id": "blast-core-nt", "role": "blast"}]})
    assert resolved["blast"]["path"] == str(database_dir / "core_nt")
    assert resolved["blast"]["metadata"]["selectedPath"] == str(database_dir)


def test_mmseqs2_template_matches_createdb_prefix_outputs() -> None:
    from apps.remote_runner.databases import list_database_templates

    templates = {item["id"]: item for item in list_database_templates()}

    assert "prefix.dbtype + prefix_h + prefix_h.dbtype" in templates["mmseqs2"]["expectedFiles"]
    assert "mmseqs convert2fasta" in templates["mmseqs2"]["toolProbe"]["commandTemplate"]


def test_resolve_run_databases_revalidates_template_before_injection(tmp_path: Path, monkeypatch) -> None:
    _patch_tool_probe_success(monkeypatch)
    cfg = _cfg(tmp_path)
    ensure_runtime_layout(cfg)
    database_dir = tmp_path / "taxonomy-db"
    database_dir.mkdir()
    for filename in ("hash.k2d", "opts.k2d", "taxo.k2d"):
        (database_dir / filename).write_text(filename, encoding="utf-8")
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
