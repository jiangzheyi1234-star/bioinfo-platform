from __future__ import annotations

from collections.abc import Mapping
import fnmatch
from pathlib import Path

from .database_templates import DATABASE_TEMPLATES


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
        _materialize_composite_fields(target, template)
    else:
        target = _materialize_file_template(base_dir, template_id, template)
        if template_id == "custom":
            return target

    container = target if target.is_dir() else target.parent
    _write_template_directory_contract(container, template)
    if not target.is_dir():
        _write_template_file_companions(target, template)
    return target


def materialize_template_selection(base_dir: Path, template_id: str) -> tuple[Path, Path]:
    target = materialize_template_path(base_dir, template_id)
    selected_path = target if target.is_dir() else target.parent
    return target, selected_path


def expected_template_entry_path(template: Mapping[str, object], resolved: Mapping[str, object], selected_path: Path) -> str:
    if template["pathKind"] == "composite":
        return ""
    return str(resolved.get("prefix") or resolved.get("path") or selected_path)


def _materialize_file_template(base_dir: Path, template_id: str, template: Mapping[str, object]) -> Path:
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
    return target


def _materialize_composite_fields(target: Path, template: Mapping[str, object]) -> None:
    fields = template.get("fields") or {}
    for field_key, field_spec in fields.items():
        spec = field_spec if isinstance(field_spec, Mapping) else {}
        hint_name = Path(str(spec.get("pathHint") or "")).name
        field_kind = str(spec.get("pathKind") or "directory")
        field_path = target if len(fields) == 1 and field_kind == "directory" else target / (hint_name or str(field_key))
        validation = spec.get("validation") or {}
        if field_kind == "file":
            filename = str(
                (spec.get("resolve") or {}).get("fileName")
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


def _write_template_directory_contract(container: Path, template: Mapping[str, object]) -> None:
    for filename in template.get("requiredFiles", []):
        path = container / str(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(filename, encoding="utf-8")
    for pattern in template.get("requiredPatterns", []):
        path = container / example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pattern), encoding="utf-8")
    for pattern in template.get("anyPatterns", []):
        path = container / example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pattern), encoding="utf-8")
        break
    for pattern_set in template.get("prefixPatternSets", []):
        for suffix in pattern_set:
            Path(str(container / "index") + str(suffix)).write_text(str(suffix), encoding="utf-8")
        break
    for pattern in template.get("anyIndexPatterns", []):
        path = container / example_name_for_pattern(str(pattern))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pattern), encoding="utf-8")
        break
    for filename in template.get("anyFiles", []):
        path = container / str(filename)
        if "." not in str(filename):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(filename), encoding="utf-8")
        break
    for pattern_set in template.get("anyPatternSets", []):
        for pattern in pattern_set:
            path = container / example_name_for_pattern(str(pattern))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(pattern), encoding="utf-8")
        break


def _write_template_file_companions(target: Path, template: Mapping[str, object]) -> None:
    base = target.with_suffix("")
    for suffix in template.get("companionSuffixes", []):
        Path(str(base) + str(suffix)).write_text(str(suffix), encoding="utf-8")
    for suffix in template.get("indexSuffixes", []):
        Path(str(target) + str(suffix)).write_text(str(suffix), encoding="utf-8")
    for pattern_set in template.get("prefixPatternSets", []):
        for suffix in pattern_set:
            Path(str(target) + str(suffix)).write_text(str(suffix), encoding="utf-8")
        break
