from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.database_template_fixtures import (
    example_name_for_pattern,
    expected_template_entry_path,
    materialize_template_path,
    materialize_template_selection,
)
from apps.remote_runner.databases import DATABASE_TEMPLATES
from core.governance_policy import SUPPORTED_ROLES


__all__ = [
    "DATABASE_TEMPLATES",
    "DatabaseContractCase",
    "assert_resolution_contract",
    "example_name_for_pattern",
    "expected_template_entry_path",
    "iter_workflow_resource_contract_cases",
    "make_blast_prefix_database",
    "make_bwa_reference",
    "make_configured_remote_runner",
    "make_kraken2_database",
    "make_remote_runner_config",
    "materialize_template_path",
    "materialize_template_selection",
    "write_files",
]


@dataclass(frozen=True, slots=True)
class DatabaseContractCase:
    case_id: str
    template_id: str
    database_id: str
    database_name: str
    resource_key: str
    config_key: str
    database_path: str
    entry_path: Path | str
    expected_path_mode: str
    expected_input_kind: str
    expected_input: object
    expected_resolved: object
    expected_config_value: object


def make_remote_runner_config(
    tmp_path: Path,
    *,
    token: str = "database-registry-token",
    api_token_roles: tuple[str, ...] | None = None,
) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token=token,
        api_token_roles=tuple(sorted(SUPPORTED_ROLES)) if api_token_roles is None else api_token_roles,
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


def make_configured_remote_runner(
    tmp_path: Path,
    *,
    token: str = "database-registry-token",
    api_token_roles: tuple[str, ...] | None = None,
) -> RemoteRunnerConfig:
    cfg = make_remote_runner_config(tmp_path, token=token, api_token_roles=api_token_roles)
    ensure_runtime_layout(cfg)
    return cfg


def write_files(base_dir: Path, names: Iterable[str], content: str = "index") -> None:
    for name in names:
        path = base_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def make_kraken2_database(base_dir: Path, *, complete: bool = True) -> Path:
    files = ["hash.k2d"]
    if complete:
        files.extend(["opts.k2d", "taxo.k2d"])
    write_files(base_dir, files, "mini")
    return base_dir


def make_bwa_reference(base_dir: Path, filename: str = "hg38.fa") -> Path:
    fasta = base_dir / filename
    fasta.parent.mkdir(parents=True, exist_ok=True)
    fasta.write_text(">chr1\nACGT\n", encoding="utf-8")
    for suffix in (".amb", ".ann", ".bwt", ".pac", ".sa"):
        Path(str(fasta) + suffix).write_text("index", encoding="utf-8")
    return fasta


def make_blast_prefix_database(base_dir: Path, prefix: str = "nt") -> Path:
    write_files(base_dir, (f"{prefix}{suffix}" for suffix in (".nhr", ".nin", ".nsq")))
    return base_dir


def iter_workflow_resource_contract_cases(tmp_path: Path) -> list[DatabaseContractCase]:
    blast_dir = make_blast_prefix_database(tmp_path / "blast")
    bwa_fasta = make_bwa_reference(tmp_path / "bwa")
    kraken_dir = make_kraken2_database(tmp_path / "kraken2")
    nucleotide = tmp_path / "humann" / "chocophlan"
    protein = tmp_path / "humann" / "uniref"
    mapping = tmp_path / "humann" / "utility_mapping"
    for path in (nucleotide, protein, mapping):
        path.mkdir(parents=True, exist_ok=True)
    (nucleotide / "genome.ffn.gz").write_text("nucleotide", encoding="utf-8")
    (protein / "uniref90.dmnd").write_text("protein", encoding="utf-8")
    (mapping / "map_uniref90_name.txt.gz").write_text("mapping", encoding="utf-8")

    humann_fields = {
        "nucleotide": str(nucleotide),
        "protein": str(protein),
        "utility_mapping": str(mapping),
    }
    return [
        DatabaseContractCase(
            case_id="directory-kraken2",
            template_id="kraken2",
            database_id="db_kraken2",
            database_name="Kraken2",
            resource_key="kraken_db",
            config_key="kraken_db",
            database_path=str(kraken_dir),
            entry_path=str(kraken_dir),
            expected_path_mode="directory",
            expected_input_kind="single",
            expected_input={"kind": "single", "path": str(kraken_dir)},
            expected_resolved={"default": str(kraken_dir)},
            expected_config_value=str(kraken_dir),
        ),
        DatabaseContractCase(
            case_id="prefix-blast",
            template_id="blast",
            database_id="db_ncbi_nt",
            database_name="NCBI nt",
            resource_key="blast_nt_db",
            config_key="blast_nt_db",
            database_path=str(blast_dir),
            entry_path=str(blast_dir / "nt"),
            expected_path_mode="prefix",
            expected_input_kind="single",
            expected_input={"kind": "single", "path": str(blast_dir)},
            expected_resolved={"default": str(blast_dir / "nt")},
            expected_config_value=str(blast_dir / "nt"),
        ),
        DatabaseContractCase(
            case_id="primary-with-sidecars-bwa",
            template_id="bwa",
            database_id="db_bwa",
            database_name="BWA hg38",
            resource_key="bwa_db",
            config_key="bwa_db",
            database_path=str(bwa_fasta),
            entry_path=str(bwa_fasta),
            expected_path_mode="primary_with_sidecars",
            expected_input_kind="single",
            expected_input={"kind": "single", "path": str(bwa_fasta)},
            expected_resolved={"default": str(bwa_fasta)},
            expected_config_value=str(bwa_fasta),
        ),
        DatabaseContractCase(
            case_id="composite-humann",
            template_id="humann",
            database_id="db_humann",
            database_name="HUMAnN",
            resource_key="humann_db",
            config_key="humann",
            database_path=str(nucleotide.parent),
            entry_path="",
            expected_path_mode="composite",
            expected_input_kind="multi",
            expected_input={"kind": "multi", "fields": humann_fields},
            expected_resolved=humann_fields,
            expected_config_value=humann_fields,
        ),
    ]


def assert_resolution_contract(
    record: Mapping[str, object],
    *,
    input_path: Path | str,
    entry_path: Path | str,
    path_mode: str,
    resolved_path: object | None = None,
    input_value: object | None = None,
    input_kind: str | None = None,
    require_metadata: bool = True,
) -> None:
    expected_input = str(input_path)
    expected_entry = str(entry_path)
    metadata = record.get("metadata")

    assert record["inputPath"] == expected_input
    assert record["entryPath"] == expected_entry
    assert record["pathMode"] == path_mode
    if input_value is not None:
        assert record["input"] == input_value
    if input_kind is not None:
        input_record = record["input"]
        assert isinstance(input_record, Mapping)
        assert input_record["kind"] == input_kind
    if require_metadata:
        assert isinstance(metadata, Mapping)
        assert metadata["inputPath"] == expected_input
        assert metadata["entryPath"] == expected_entry
        assert metadata["pathMode"] == path_mode
        if input_value is not None:
            assert metadata["input"] == input_value
        if input_kind is not None:
            metadata_input = metadata["input"]
            assert isinstance(metadata_input, Mapping)
            assert metadata_input["kind"] == input_kind
    elif isinstance(metadata, Mapping):
        if "inputPath" in metadata:
            assert metadata["inputPath"] == expected_input
        if "entryPath" in metadata:
            assert metadata["entryPath"] == expected_entry
        if "pathMode" in metadata:
            assert metadata["pathMode"] == path_mode
        if input_value is not None and "input" in metadata:
            assert metadata["input"] == input_value
        if input_kind is not None and "input" in metadata:
            metadata_input = metadata["input"]
            assert isinstance(metadata_input, Mapping)
            assert metadata_input["kind"] == input_kind
    if resolved_path is not None:
        assert record["resolvedPath"] == resolved_path
        if require_metadata:
            assert isinstance(metadata, Mapping)
            assert metadata["resolvedPath"] == resolved_path
        elif isinstance(metadata, Mapping) and "resolvedPath" in metadata:
            assert metadata["resolvedPath"] == resolved_path
