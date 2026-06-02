from __future__ import annotations

from typing import Any

_PATH_KIND_DEFAULTS: dict[str, dict[str, str]] = {
    "directory": {"pathLabel": "数据库目录", "runtimeValue": "selected_path"},
    "file": {"pathLabel": "数据库文件", "runtimeValue": "resolved_file"},
    "prefix": {"pathLabel": "索引目录或索引文件", "runtimeValue": "resolved_prefix"},
    "primary_with_sidecars": {"pathLabel": "FASTA 主文件", "runtimeValue": "primary_file"},
    "composite": {"pathLabel": "复合数据库路径", "runtimeValue": "resolved_entries"},
}

_TYPE_CATEGORY_DEFAULTS = {
    "taxonomy": "taxonomy",
    "amr": "annotation",
    "sequence_index": "alignment",
    "functional_profile": "annotation",
    "profile_hmm": "annotation",
    "annotation": "annotation",
}

_TYPE_CAPABILITY_DEFAULTS = {
    "taxonomy": ["taxonomy_database"],
    "amr": ["amr_database"],
    "sequence_index": ["sequence_search_database"],
    "functional_profile": ["functional_profile_database"],
    "profile_hmm": ["profile_hmm_database"],
    "annotation": ["annotation_database"],
    "reference": ["reference_database"],
}

_RUNTIME_SHAPE_DEFAULTS = {
    "directory": {"kind": "scalarPath", "valueKey": "default", "jsonType": "string"},
    "file": {"kind": "scalarPath", "valueKey": "default", "jsonType": "string"},
    "prefix": {"kind": "prefix", "valueKey": "default", "jsonType": "string"},
    "primary_with_sidecars": {"kind": "primaryFile", "valueKey": "default", "jsonType": "string"},
    "composite": {"kind": "namedEntries", "valueKey": "resolved", "jsonType": "object"},
}

DATABASE_TEMPLATES: dict[str, dict[str, Any]] = {
    "kraken2": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "Kraken2",
        "icon": "taxonomy",
        "pathKind": "directory",
        "pathLabel": "数据库目录",
        "runtimeValue": "selected_path",
        "description": "宏基因组物种分类库",
        "pathHint": "~/.h2ometa/databases/kraken2/standard",
        "requiredFiles": ["hash.k2d", "opts.k2d", "taxo.k2d"],
    },
    "bracken": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "Bracken",
        "icon": "taxonomy",
        "pathKind": "directory",
        "pathLabel": "Kraken2/Bracken 数据库目录",
        "runtimeValue": "selected_path",
        "description": "Kraken2 丰度估计库",
        "pathHint": "~/.h2ometa/databases/bracken/standard",
        "requiredFiles": ["hash.k2d", "opts.k2d", "taxo.k2d"],
        "anyPatterns": ["database*.kmer_distrib"],
    },
    "metaphlan": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "MetaPhlAn",
        "icon": "taxonomy",
        "pathKind": "directory",
        "pathLabel": "MetaPhlAn 数据库目录",
        "runtimeValue": "selected_path",
        "description": "MetaPhlAn marker + Bowtie2 index",
        "pathHint": "~/.h2ometa/databases/metaphlan/mpa",
        "anyPatterns": ["*.pkl"],
        "anyIndexPatterns": ["*.bt2", "*.bt2l"],
    },
    "centrifuge": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "Centrifuge",
        "icon": "taxonomy",
        "pathKind": "prefix",
        "pathLabel": "Centrifuge 索引目录或索引文件",
        "runtimeValue": "resolved_prefix",
        "description": "Centrifuge 分类索引",
        "pathHint": "~/.h2ometa/databases/centrifuge/nt",
        "prefixPatternSets": [[".1.cf", ".2.cf", ".3.cf"]],
        "requiredSuffixes": [".1.cf", ".2.cf", ".3.cf"],
    },
    "kaiju": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "Kaiju",
        "icon": "taxonomy",
        "pathKind": "directory",
        "pathLabel": "Kaiju 数据库目录",
        "runtimeValue": "selected_path",
        "description": "蛋白级分类库",
        "pathHint": "~/.h2ometa/databases/kaiju/nr",
        "requiredFiles": ["nodes.dmp", "names.dmp"],
        "anyPatterns": ["*.fmi"],
    },
    "card_rgi": {
        "type": "amr",
        "category": "annotation",
        "label": "CARD / RGI",
        "icon": "amr",
        "pathKind": "composite",
        "pathLabel": "CARD/RGI 复合数据库",
        "runtimeValue": "resolved_entries",
        "description": "耐药基因识别库",
        "pathHint": "~/.h2ometa/databases/card/current/card.json",
        "fields": {
            "card_json": {
                "label": "CARD card.json",
                "pathKind": "file",
                "required": True,
                "pathHint": "~/.h2ometa/databases/card/current/card.json",
                "select": {"allowDirectory": True, "allowFile": True, "fileExtensions": [".json"]},
                "resolve": {"strategy": "find_named_file", "fileName": "card.json"},
                "validation": {"requiredFileName": "card.json", "minSizeBytes": 1},
            },
        },
    },
    "blast": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "BLAST",
        "icon": "index",
        "pathKind": "prefix",
        "pathLabel": "索引目录或索引文件",
        "runtimeValue": "resolved_prefix",
        "description": "BLAST nucleotide/protein 索引",
        "pathHint": "~/.h2ometa/databases/blast/nt",
        "prefixPatternSets": [[".nhr", ".nin", ".nsq"], [".phr", ".pin", ".psq"]],
        "requiredSuffixes": [".nhr", ".nin", ".nsq"],
        "prefixAliasPatterns": ["*.nal", "*.pal"],
    },
    "diamond": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "DIAMOND",
        "icon": "index",
        "pathKind": "file",
        "pathLabel": "DIAMOND 数据库文件",
        "runtimeValue": "resolved_file",
        "description": "DIAMOND 蛋白数据库",
        "pathHint": "~/.h2ometa/databases/diamond/nr.dmnd",
        "anyPatterns": ["*.dmnd"],
        "requiredSuffixes": [".dmnd"],
    },
    "bowtie2": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "Bowtie2",
        "icon": "index",
        "pathKind": "prefix",
        "pathLabel": "Bowtie2 索引目录或索引文件",
        "runtimeValue": "resolved_prefix",
        "description": "宿主去除或比对索引",
        "pathHint": "~/.h2ometa/databases/bowtie2/human",
        "prefixPatternSets": [
            [".1.bt2", ".2.bt2", ".3.bt2", ".4.bt2", ".rev.1.bt2", ".rev.2.bt2"],
            [".1.bt2l", ".2.bt2l", ".3.bt2l", ".4.bt2l", ".rev.1.bt2l", ".rev.2.bt2l"],
        ],
        "requiredSuffixes": [".1.bt2", ".2.bt2", ".3.bt2", ".4.bt2", ".rev.1.bt2", ".rev.2.bt2"],
    },
    "bwa": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "BWA",
        "icon": "index",
        "pathKind": "primary_with_sidecars",
        "pathLabel": "FASTA 主文件",
        "runtimeValue": "primary_file",
        "description": "BWA reference index",
        "pathHint": "~/.h2ometa/databases/bwa/hg38.fa",
        "anyPatterns": ["*.fa", "*.fasta", "*.fna"],
        "primaryExtensions": [".fa", ".fasta"],
        "sidecars": [".amb", ".ann", ".bwt", ".pac", ".sa"],
        "indexSuffixes": [".amb", ".ann", ".bwt", ".pac", ".sa"],
    },
    "humann": {
        "type": "functional_profile",
        "category": "annotation",
        "label": "HUMAnN",
        "icon": "taxonomy",
        "pathKind": "composite",
        "pathLabel": "HUMAnN 多组件数据库",
        "runtimeValue": "resolved_entries",
        "description": "HUMAnN ChocoPhlAn, UniRef, and utility mapping databases",
        "pathHint": "~/.h2ometa/databases/humann",
        "fields": {
            "nucleotide": {
                "label": "ChocoPhlAn 目录",
                "pathKind": "directory",
                "required": True,
                "pathHint": "~/.h2ometa/databases/humann/chocophlan",
                "validation": {"requiredGlobs": ["*.ffn*"]},
            },
            "protein": {
                "label": "UniRef 目录",
                "pathKind": "directory",
                "required": True,
                "pathHint": "~/.h2ometa/databases/humann/uniref",
                "validation": {"requiredGlobs": ["*.dmnd"]},
            },
            "utility_mapping": {
                "label": "utility_mapping 目录",
                "pathKind": "directory",
                "required": False,
                "pathHint": "~/.h2ometa/databases/humann/utility_mapping",
                "validation": {"requiredGlobs": ["map_*"]},
            },
        },
    },
    "gtdbtk": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "GTDB-Tk",
        "icon": "taxonomy",
        "pathKind": "directory",
        "pathLabel": "GTDB-Tk 数据目录",
        "runtimeValue": "selected_path",
        "description": "GTDB-Tk taxonomy reference",
        "pathHint": "~/.h2ometa/databases/gtdbtk/release",
        "requiredFiles": ["markers", "masks", "metadata", "mrca_red", "msa", "pplacer", "radii", "skani", "split", "taxonomy"],
        "anyFiles": ["metadata.txt", "VERSION"],
    },
    "sourmash": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "Sourmash",
        "icon": "index",
        "pathKind": "file",
        "pathLabel": "Sourmash sketch 文件",
        "runtimeValue": "resolved_file",
        "description": "Sourmash signature or SBT database",
        "pathHint": "~/.h2ometa/databases/sourmash/reference.sig",
        "anyPatterns": ["*.sig", "*.sbt.zip", "*.zip"],
        "requiredSuffixes": [".sig", ".sbt.zip", ".zip"],
    },
    "mmseqs2": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "MMseqs2",
        "icon": "index",
        "pathKind": "prefix",
        "pathLabel": "MMseqs2 数据库前缀或文件",
        "runtimeValue": "resolved_prefix",
        "description": "MMseqs2 sequence/profile database",
        "pathHint": "~/.h2ometa/databases/mmseqs2/uniref",
        "prefixPatternSets": [[".dbtype", "_h", "_h.dbtype"]],
        "requiredSuffixes": [".dbtype", "_h", "_h.dbtype"],
    },
    "hmmer_pfam": {
        "type": "profile_hmm",
        "category": "annotation",
        "label": "HMMER / Pfam",
        "icon": "index",
        "pathKind": "file",
        "pathLabel": "HMM profile 主文件",
        "runtimeValue": "resolved_file",
        "description": "HMMER profile database with hmmpress index",
        "pathHint": "~/.h2ometa/databases/pfam/Pfam-A.hmm",
        "anyPatterns": ["*.hmm"],
        "requiredSuffixes": [".hmm"],
        "companionSuffixes": [".h3f", ".h3i", ".h3m", ".h3p"],
    },
    "eggnog_mapper": {
        "type": "annotation",
        "category": "annotation",
        "label": "eggNOG-mapper",
        "icon": "index",
        "pathKind": "composite",
        "pathLabel": "eggNOG 复合数据库",
        "runtimeValue": "resolved_entries",
        "description": "eggNOG-mapper annotation database",
        "pathHint": "~/.h2ometa/databases/eggnog",
        "fields": {
            "data_dir": {
                "label": "eggNOG 数据目录",
                "pathKind": "directory",
                "required": True,
                "pathHint": "~/.h2ometa/databases/eggnog",
                "validation": {"requiredGlobs": ["*.db", "eggnog_proteins.dmnd"]},
            },
        },
    },
    "interproscan": {
        "type": "annotation",
        "category": "annotation",
        "label": "InterProScan",
        "icon": "index",
        "pathKind": "directory",
        "pathLabel": "InterProScan data 目录",
        "runtimeValue": "selected_path",
        "description": "InterProScan data directory",
        "pathHint": "~/.h2ometa/databases/interproscan/data",
        "anyFiles": ["interpro.xml", "match_complete.xml"],
    },
    "minimap2": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "minimap2",
        "icon": "index",
        "pathKind": "file",
        "pathLabel": "minimap2 .mmi 或 FASTA 文件",
        "runtimeValue": "resolved_file",
        "description": "minimap2 reference FASTA or .mmi index",
        "pathHint": "~/.h2ometa/databases/minimap2/reference.mmi",
        "anyPatterns": ["*.mmi", "*.fa", "*.fasta", "*.fna"],
        "requiredSuffixes": [".mmi", ".fa", ".fasta", ".fna"],
    },
    "star": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "STAR",
        "icon": "index",
        "pathKind": "directory",
        "pathLabel": "STAR genome index 目录",
        "runtimeValue": "selected_path",
        "description": "STAR genome index",
        "pathHint": "~/.h2ometa/databases/star/hg38",
        "requiredFiles": ["Genome", "SA", "SAindex"],
    },
    "hisat2": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "HISAT2",
        "icon": "index",
        "pathKind": "prefix",
        "pathLabel": "HISAT2 索引目录或索引文件",
        "runtimeValue": "resolved_prefix",
        "description": "HISAT2 genome index",
        "pathHint": "~/.h2ometa/databases/hisat2/hg38",
        "prefixPatternSets": [
            [".1.ht2", ".2.ht2", ".3.ht2", ".4.ht2", ".5.ht2", ".6.ht2", ".7.ht2", ".8.ht2"],
            [".1.ht2l", ".2.ht2l", ".3.ht2l", ".4.ht2l", ".5.ht2l", ".6.ht2l", ".7.ht2l", ".8.ht2l"],
        ],
        "requiredSuffixes": [".1.ht2", ".2.ht2", ".3.ht2", ".4.ht2", ".5.ht2", ".6.ht2", ".7.ht2", ".8.ht2"],
    },
    "salmon": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "Salmon",
        "icon": "index",
        "pathKind": "directory",
        "pathLabel": "Salmon transcriptome index 目录",
        "runtimeValue": "selected_path",
        "description": "Salmon transcriptome index",
        "pathHint": "~/.h2ometa/databases/salmon/transcriptome",
        "anyFiles": ["versionInfo.json", "info.json"],
    },
    "kallisto": {
        "type": "sequence_index",
        "category": "alignment",
        "label": "kallisto",
        "icon": "index",
        "pathKind": "file",
        "pathLabel": "kallisto index 文件",
        "runtimeValue": "resolved_file",
        "description": "kallisto transcriptome index",
        "pathHint": "~/.h2ometa/databases/kallisto/transcriptome.idx",
        "anyPatterns": ["*.idx"],
        "requiredSuffixes": [".idx"],
    },
    "silva_qiime": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "SILVA / QIIME",
        "icon": "taxonomy",
        "pathKind": "file",
        "pathLabel": "QIIME 2 classifier artifact",
        "runtimeValue": "resolved_file",
        "description": "SILVA QIIME 2 classifier artifact",
        "pathHint": "~/.h2ometa/databases/silva/classifier.qza",
        "anyPatterns": ["*.qza"],
        "requiredSuffixes": [".qza"],
    },
    "checkm": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "CheckM2",
        "icon": "taxonomy",
        "pathKind": "file",
        "pathLabel": "CheckM2 DIAMOND 数据库文件",
        "runtimeValue": "resolved_file",
        "description": "CheckM2 UniRef100 KO DIAMOND database",
        "pathHint": "~/.h2ometa/databases/checkm2/CheckM2_database/uniref100.KO.1.dmnd",
        "anyPatterns": ["uniref100.KO*.dmnd"],
        "requiredSuffixes": [".dmnd"],
    },
    "ncbi_taxonomy": {
        "type": "taxonomy",
        "category": "taxonomy",
        "label": "NCBI taxonomy",
        "icon": "taxonomy",
        "pathKind": "directory",
        "pathLabel": "NCBI taxdump 目录",
        "runtimeValue": "selected_path",
        "description": "NCBI taxdump taxonomy files",
        "pathHint": "~/.h2ometa/databases/ncbi_taxonomy/taxdump",
        "requiredFiles": ["nodes.dmp", "names.dmp"],
    },
    "custom": {
        "type": "reference",
        "category": "custom",
        "label": "Custom",
        "icon": "custom",
        "pathKind": "directory",
        "pathLabel": "自定义数据库目录",
        "runtimeValue": "selected_path",
        "description": "未内置模板的自定义库",
        "pathHint": "~/.h2ometa/databases/custom/name",
        "requiredFiles": [],
    },
}

def list_database_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template_id,
            "name": str(template.get("label") or template_id),
            "supportLevel": str(template.get("supportLevel") or "stable"),
            "type": str(template.get("type") or "reference"),
            "category": _template_category(template),
            "icon": str(template.get("icon") or "custom"),
            "pathKind": str(template.get("pathKind") or "directory"),
            "pathLabel": _template_path_label(template),
            "runtimeValue": _template_runtime_value(template),
            "runtimeShape": _template_runtime_shape(template),
            "capabilities": _template_capabilities(template),
            "selectorKind": str(template.get("pathKind") or "directory"),
            "selector": {
                "kind": str(template.get("pathKind") or "directory"),
                "hint": str(template.get("pathHint") or ""),
            },
            "description": str(template.get("description") or ""),
            "pathHint": str(template.get("pathHint") or ""),
            "expectedFiles": _template_expected_files(template),
            "anyPatterns": list(template.get("anyPatterns") or []),
            "primaryExtensions": list(template.get("primaryExtensions") or []),
            "sidecars": list(template.get("sidecars") or []),
            "indexSuffixes": list(template.get("indexSuffixes") or []),
            "companionSuffixes": list(template.get("companionSuffixes") or []),
            "prefixPatternSets": list(template.get("prefixPatternSets") or []),
            "prefixAliasPatterns": list(template.get("prefixAliasPatterns") or []),
            "fields": dict(template.get("fields") or {}),
            "select": _template_select(template),
            "resolve": _template_resolve(template),
            "validation": _template_validation(template),
            "output": _template_output(template),
            "runtime": _template_runtime(template),
        }
        for template_id, template in DATABASE_TEMPLATES.items()
    ]


def database_template_runtime_shape(template: dict[str, Any]) -> dict[str, Any]:
    return _template_runtime_shape(template)


def database_template_capabilities(template: dict[str, Any]) -> list[str]:
    return _template_capabilities(template)


def _template_category(template: dict[str, Any]) -> str:
    if template.get("category"):
        return str(template["category"])
    return _TYPE_CATEGORY_DEFAULTS.get(str(template.get("type") or ""), "custom")


def _template_path_label(template: dict[str, Any]) -> str:
    if template.get("pathLabel"):
        return str(template["pathLabel"])
    path_kind = str(template.get("pathKind") or "directory")
    return _PATH_KIND_DEFAULTS.get(path_kind, _PATH_KIND_DEFAULTS["directory"])["pathLabel"]


def _template_runtime_value(template: dict[str, Any]) -> str:
    if template.get("runtimeValue"):
        return str(template["runtimeValue"])
    path_kind = str(template.get("pathKind") or "directory")
    return _PATH_KIND_DEFAULTS.get(path_kind, _PATH_KIND_DEFAULTS["directory"])["runtimeValue"]


def _template_select(template: dict[str, Any]) -> dict[str, Any]:
    if isinstance(template.get("select"), dict):
        return dict(template["select"])
    path_kind = str(template.get("pathKind") or "directory")
    return {
        "allowDirectory": path_kind in {"directory", "prefix", "file", "composite"},
        "allowFile": path_kind in {"file", "prefix", "primary_with_sidecars"},
        "fileExtensions": _template_file_extensions(template),
    }


def _template_resolve(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("resolve"), dict):
        return {str(key): str(value) for key, value in template["resolve"].items()}
    path_kind = str(template.get("pathKind") or "directory")
    strategy = {
        "directory": "selected_directory",
        "file": "matching_file",
        "prefix": "index_prefix",
        "primary_with_sidecars": "primary_file_with_sidecars",
        "composite": "composite_fields",
    }.get(path_kind, "selected_path")
    return {"strategy": strategy}


def _template_validation(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("validation"), dict):
        return {str(key): str(value) for key, value in template["validation"].items()}
    path_kind = str(template.get("pathKind") or "directory")
    return {
        "structureCheck": {
            "directory": "required_files_and_patterns",
            "file": "file_pattern",
            "prefix": "complete_prefix_set",
            "primary_with_sidecars": "primary_file_and_sidecars",
            "composite": "field_paths_and_field_rules",
        }.get(path_kind, "path_exists"),
    }


def _template_output(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("output"), dict):
        return {str(key): str(value) for key, value in template["output"].items()}
    if str(template.get("pathKind") or "directory") == "composite":
        return {"valueFrom": "resolved"}
    return {"resolvedKey": "default"}


def _template_runtime(template: dict[str, Any]) -> dict[str, str]:
    if isinstance(template.get("runtime"), dict):
        return {str(key): str(value) for key, value in template["runtime"].items()}
    label = str(template.get("label") or "database")
    runtime_value = _template_runtime_value(template)
    examples = {
        "selected_path": f"{label} uses <数据库目录>",
        "resolved_file": f"{label} uses <解析后的文件>",
        "resolved_prefix": f"{label} uses <解析后的 prefix>",
        "primary_file": f"{label} uses <主文件>",
        "resolved_entries": f"{label} uses <resolved 字段对象>",
    }
    return {"example": examples.get(runtime_value, f"{label} uses <resolved.default>")}


def _template_runtime_shape(template: dict[str, Any]) -> dict[str, Any]:
    if isinstance(template.get("runtimeShape"), dict):
        return dict(template["runtimeShape"])
    path_kind = str(template.get("pathKind") or "directory")
    shape = dict(_RUNTIME_SHAPE_DEFAULTS.get(path_kind, _RUNTIME_SHAPE_DEFAULTS["directory"]))
    if path_kind == "composite":
        shape["entries"] = {
            str(key): {
                "pathKind": str((spec if isinstance(spec, dict) else {}).get("pathKind") or "directory"),
                "required": bool((spec if isinstance(spec, dict) else {}).get("required", True)),
            }
            for key, spec in dict(template.get("fields") or {}).items()
        }
    return shape


def _template_capabilities(template: dict[str, Any]) -> list[str]:
    raw = template.get("capabilities")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    db_type = str(template.get("type") or "reference")
    capabilities = list(_TYPE_CAPABILITY_DEFAULTS.get(db_type, ["reference_database"]))
    path_kind = str(template.get("pathKind") or "directory")
    if path_kind == "prefix":
        capabilities.append("indexed_database")
    if path_kind == "composite":
        capabilities.append("multi_asset_database")
    return capabilities


def _template_file_extensions(template: dict[str, Any]) -> list[str]:
    extensions: list[str] = []
    for key in ("requiredSuffixes", "primaryExtensions"):
        extensions.extend(str(value) for value in template.get(key, []) if str(value).startswith("."))
    for pattern in template.get("anyPatterns", []):
        text = str(pattern)
        if text.startswith("*."):
            extensions.append(text[1:])
    return sorted(set(extensions))

def _template_expected_files(template: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "requiredFiles",
        "requiredPatterns",
        "requiredSuffixes",
        "anyPatterns",
        "anyIndexPatterns",
        "anyFiles",
        "primaryExtensions",
        "sidecars",
        "indexSuffixes",
    ):
        values.extend(str(item) for item in template.get(key, []) if str(item).strip())
    for pattern_set in template.get("prefixPatternSets", []):
        values.append("prefix" + " + prefix".join(str(item) for item in pattern_set if str(item).strip()))
    values.extend(str(item) for item in template.get("prefixAliasPatterns", []) if str(item).strip())
    values.extend(str(item) for item in template.get("companionSuffixes", []) if str(item).strip())
    for pattern_set in template.get("anyPatternSets", []):
        values.append(" / ".join(str(item) for item in pattern_set if str(item).strip()))
    return values
