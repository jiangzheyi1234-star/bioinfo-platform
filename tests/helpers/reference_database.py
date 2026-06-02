from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import fnmatch
from pathlib import Path

from apps.remote_runner.config import RemoteRunnerConfig, ensure_runtime_layout
from apps.remote_runner.databases import DATABASE_TEMPLATES


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
) -> RemoteRunnerConfig:
    return RemoteRunnerConfig(
        token=token,
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
) -> RemoteRunnerConfig:
    cfg = make_remote_runner_config(tmp_path, token=token)
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


def example_name_for_pattern(pattern: str) -> str:
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


def materialize_template_path(base_dir: Path, template_id: str) -> Path:
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
            field_path = (
                target
                if len(fields) == 1 and field_kind == "directory"
                else target / (hint_name or str(field_key))
            )
            validation = field_spec.get("validation") or {}
            if field_kind == "file":
                filename = str(
                    (field_spec.get("resolve") or {}).get("fileName")
                    or validation.get("requiredFileName")
                    or field_path.name
                )
                if field_path.suffix:
                    file_path = field_path
                else:
                    field_path.mkdir(parents=True, exist_ok=True)
                    file_path = field_path / filename
                file_path.write_text("database", encoding="utf-8")
            else:
                field_path.mkdir(parents=True, exist_ok=True)
                for pattern in validation.get("requiredGlobs") or []:
                    path = field_path / example_name_for_pattern(str(pattern))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(str(pattern), encoding="utf-8")
    else:
        file_patterns: list[str] = []
        file_patterns.extend(str(item) for item in template.get("anyPatterns", []) if str(item).strip())
        file_patterns.extend(str(item) for item in template.get("requiredPatterns", []) if str(item).strip())
        file_patterns.extend(str(item) for item in template.get("anyIndexPatterns", []) if str(item).strip())
        for pattern_set in template.get("anyPatternSets", []):
            file_patterns.extend(str(item) for item in pattern_set if str(item).strip())
        filename = example_name_for_pattern(file_patterns[0]) if file_patterns else f"{template_id}.dat"
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
        path = container / example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pattern, encoding="utf-8")
    if not target.is_dir():
        base = target.with_suffix("")
        for suffix in template.get("companionSuffixes", []):
            Path(str(base) + str(suffix)).write_text(str(suffix), encoding="utf-8")
        for suffix in template.get("indexSuffixes", []):
            Path(str(target) + str(suffix)).write_text(str(suffix), encoding="utf-8")
    for pattern in template.get("anyPatterns", []):
        path = container / example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pattern, encoding="utf-8")
        break
    for pattern_set in template.get("prefixPatternSets", []):
        for suffix in pattern_set:
            Path(str(target) + str(suffix)).write_text(str(suffix), encoding="utf-8")
        break
    for pattern in template.get("anyIndexPatterns", []):
        path = container / example_name_for_pattern(str(pattern))
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
            path = container / example_name_for_pattern(str(pattern))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(pattern, encoding="utf-8")
        break
    return target


def materialize_template_selection(base_dir: Path, template_id: str) -> tuple[Path, Path]:
    target = materialize_template_path(base_dir, template_id)
    selected_path = target if target.is_dir() else target.parent
    return target, selected_path


def expected_template_entry_path(template: Mapping[str, object], resolved: Mapping[str, object], selected_path: Path) -> str:
    if template["pathKind"] == "composite":
        return ""
    return str(resolved.get("prefix") or resolved.get("path") or selected_path)
