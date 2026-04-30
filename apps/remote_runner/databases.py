from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import database_validation
from .config import RemoteRunnerConfig
from .storage import get_connection, now_iso


class DatabaseRegistryError(ValueError):
    pass


DATABASE_TEMPLATES: dict[str, dict[str, Any]] = {
    "kraken2": {
        "type": "taxonomy",
        "label": "Kraken2",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "宏基因组物种分类库",
        "pathHint": "~/.h2ometa/databases/kraken2/standard",
        "requiredFiles": ["hash.k2d", "opts.k2d", "taxo.k2d"],
        "toolProbe": {
            "packageSpec": "bioconda::kraken2",
            "commandTemplate": "kraken2-inspect --db {path:q} >/dev/null",
        },
    },
    "bracken": {
        "type": "taxonomy",
        "label": "Bracken",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "Kraken2 丰度估计库",
        "pathHint": "~/.h2ometa/databases/bracken/standard",
        "requiredFiles": ["hash.k2d", "opts.k2d", "taxo.k2d"],
        "anyPatterns": ["database*.kmer_distrib"],
        "toolProbe": {
            "packageSpec": "bioconda::bracken",
            "commandTemplate": "kraken2-inspect --db {path:q} >/dev/null",
        },
    },
    "metaphlan": {
        "type": "taxonomy",
        "label": "MetaPhlAn",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "MetaPhlAn marker + Bowtie2 index",
        "pathHint": "~/.h2ometa/databases/metaphlan/mpa",
        "anyPatterns": ["*.pkl"],
        "anyIndexPatterns": ["*.bt2", "*.bt2l"],
        "toolProbe": {
            "packageSpec": "bioconda::metaphlan",
            "commandTemplate": "bowtie2-inspect -n {firstIndexPrefix:q} >/dev/null",
        },
    },
    "centrifuge": {
        "type": "taxonomy",
        "label": "Centrifuge",
        "icon": "taxonomy",
        "pathKind": "prefix",
        "description": "Centrifuge 分类索引",
        "pathHint": "~/.h2ometa/databases/centrifuge/nt",
        "prefixPatternSets": [[".1.cf", ".2.cf", ".3.cf"]],
        "toolProbe": {
            "packageSpec": "bioconda::centrifuge",
            "commandTemplate": "centrifuge-inspect -n {prefix:q} >/dev/null",
        },
    },
    "kaiju": {
        "type": "taxonomy",
        "label": "Kaiju",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "蛋白级分类库",
        "pathHint": "~/.h2ometa/databases/kaiju/nr",
        "requiredFiles": ["nodes.dmp", "names.dmp"],
        "anyPatterns": ["*.fmi"],
        "toolProbe": {
            "packageSpec": "bioconda::kaiju",
            "commandTemplate": "kaiju -t {path:q}/nodes.dmp -f {firstMatch:q} -i /dev/null >/dev/null",
        },
    },
    "card_rgi": {
        "type": "amr",
        "label": "CARD / RGI",
        "icon": "amr",
        "pathKind": "directory",
        "description": "耐药基因识别库",
        "pathHint": "~/.h2ometa/databases/card/current",
        "anyFiles": ["card.json"],
        "toolProbe": {
            "packageSpec": "bioconda::rgi",
            "commandTemplate": "rgi card_annotation -i {path:q}/card.json >/dev/null",
        },
    },
    "blast": {
        "type": "sequence_index",
        "label": "BLAST",
        "icon": "index",
        "pathKind": "prefix",
        "description": "BLAST nucleotide/protein 索引",
        "pathHint": "~/.h2ometa/databases/blast/nt",
        "prefixPatternSets": [[".nhr", ".nin", ".nsq"], [".phr", ".pin", ".psq"]],
        "prefixAliasPatterns": ["*.nal", "*.pal"],
        "toolProbe": {
            "packageSpec": "bioconda::blast",
            "commandTemplate": "blastdbcmd -db {prefix:q} -info >/dev/null",
        },
    },
    "diamond": {
        "type": "sequence_index",
        "label": "DIAMOND",
        "icon": "index",
        "pathKind": "file",
        "description": "DIAMOND 蛋白数据库",
        "pathHint": "~/.h2ometa/databases/diamond/nr.dmnd",
        "anyPatterns": ["*.dmnd"],
        "toolProbe": {
            "packageSpec": "bioconda::diamond",
            "commandTemplate": "diamond dbinfo --db {path:q} >/dev/null",
        },
    },
    "bowtie2": {
        "type": "sequence_index",
        "label": "Bowtie2",
        "icon": "index",
        "pathKind": "prefix",
        "description": "宿主去除或比对索引",
        "pathHint": "~/.h2ometa/databases/bowtie2/human",
        "prefixPatternSets": [
            [".1.bt2", ".2.bt2", ".3.bt2", ".4.bt2", ".rev.1.bt2", ".rev.2.bt2"],
            [".1.bt2l", ".2.bt2l", ".3.bt2l", ".4.bt2l", ".rev.1.bt2l", ".rev.2.bt2l"],
        ],
        "toolProbe": {
            "packageSpec": "bioconda::bowtie2",
            "commandTemplate": "bowtie2-inspect -n {prefix:q} >/dev/null",
        },
    },
    "bwa": {
        "type": "sequence_index",
        "label": "BWA",
        "icon": "index",
        "pathKind": "prefix",
        "description": "BWA reference index",
        "pathHint": "~/.h2ometa/databases/bwa/hg38",
        "prefixPatternSets": [[".amb", ".ann", ".bwt", ".pac", ".sa"]],
        "toolProbe": {
            "packageSpec": "bioconda::bwa",
            "commandTemplate": "bwa mem {prefix:q} /dev/null >/dev/null",
        },
    },
    "humann": {
        "type": "functional_profile",
        "label": "HUMAnN",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "HUMAnN ChocoPhlAn, UniRef, and utility mapping databases",
        "pathHint": "~/.h2ometa/databases/humann",
        "requiredPatterns": [
            "chocophlan/**/*.ffn*",
            "uniref/**/*.dmnd",
            "utility_mapping/map_*",
        ],
        "toolProbe": {
            "packageSpec": "bioconda::humann",
            "commandTemplate": "humann_config --update database_folders nucleotide {path:q}/chocophlan >/dev/null && humann_config --update database_folders protein {path:q}/uniref >/dev/null && humann_config --update database_folders utility_mapping {path:q}/utility_mapping >/dev/null && humann_config --print >/dev/null",
        },
    },
    "gtdbtk": {
        "type": "taxonomy",
        "label": "GTDB-Tk",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "GTDB-Tk taxonomy reference",
        "pathHint": "~/.h2ometa/databases/gtdbtk/release",
        "requiredFiles": [
            "markers",
            "masks",
            "metadata",
            "mrca_red",
            "msa",
            "pplacer",
            "radii",
            "skani",
            "split",
            "taxonomy",
        ],
        "anyFiles": ["metadata.txt", "VERSION"],
        "toolProbe": {
            "packageSpec": "bioconda::gtdbtk",
            "commandTemplate": "GTDBTK_DATA_PATH={path:q} gtdbtk check_install >/dev/null",
        },
    },
    "sourmash": {
        "type": "sequence_index",
        "label": "Sourmash / Mash",
        "icon": "index",
        "pathKind": "file",
        "description": "MinHash sketch 数据库",
        "pathHint": "~/.h2ometa/databases/sourmash",
        "anyPatterns": ["*.sig", "*.sbt.zip", "*.zip", "*.msh"],
        "toolProbe": {
            "packageSpec": "bioconda::sourmash",
            "commandTemplate": "sourmash sig describe {path:q} >/dev/null",
        },
    },
    "mmseqs2": {
        "type": "sequence_index",
        "label": "MMseqs2",
        "icon": "index",
        "pathKind": "prefix",
        "description": "MMseqs2 sequence/profile database",
        "pathHint": "~/.h2ometa/databases/mmseqs2/uniref",
        "prefixPatternSets": [[".dbtype", "_h", "_h.dbtype"]],
        "toolProbe": {
            "packageSpec": "bioconda::mmseqs2",
            "commandTemplate": "tmp=$(mktemp) && mmseqs convert2fasta {prefix:q} \"$tmp\" >/dev/null && rm -f \"$tmp\"",
        },
    },
    "hmmer_pfam": {
        "type": "profile_hmm",
        "label": "HMMER / Pfam",
        "icon": "index",
        "pathKind": "file",
        "description": "HMMER profile database with hmmpress index",
        "pathHint": "~/.h2ometa/databases/pfam/Pfam-A.hmm",
        "anyPatterns": ["*.hmm"],
        "companionSuffixes": [".h3f", ".h3i", ".h3m", ".h3p"],
        "toolProbe": {
            "packageSpec": "bioconda::hmmer",
            "commandTemplate": "hmmstat {path:q} >/dev/null",
        },
    },
    "eggnog_mapper": {
        "type": "annotation",
        "label": "eggNOG-mapper",
        "icon": "index",
        "pathKind": "directory",
        "description": "eggNOG-mapper annotation database",
        "pathHint": "~/.h2ometa/databases/eggnog",
        "requiredFiles": ["eggnog.db"],
        "anyPatternSets": [["eggnog_proteins.dmnd"], ["*.dmnd"], ["mmseqs.dbtype", "mmseqs_h", "mmseqs_h.dbtype"]],
        "toolProbe": {
            "packageSpec": "bioconda::eggnog-mapper",
            "commandTemplate": "tmp=$(mktemp -d) && printf '>probe\\nMAIVMGR\\n' > \"$tmp/probe.faa\" && emapper.py --data_dir {path:q} -i \"$tmp/probe.faa\" -o h2ometa-eggnog-probe --output_dir \"$tmp\" --cpu 1 >/dev/null",
        },
    },
    "interproscan": {
        "type": "annotation",
        "label": "InterProScan",
        "icon": "index",
        "pathKind": "directory",
        "description": "InterProScan data directory",
        "pathHint": "~/.h2ometa/databases/interproscan/data",
        "anyFiles": ["interpro.xml", "match_complete.xml"],
        "toolProbe": {
            "packageSpec": "bioconda::interproscan",
            "commandTemplate": "tmp=$(mktemp -d) && printf '>probe\\nMAIVMGR\\n' > \"$tmp/probe.faa\" && interproscan.sh --input \"$tmp/probe.faa\" --datadir {path:q} --output-dir \"$tmp\" --formats TSV --disable-precalc >/dev/null",
        },
    },
    "minimap2": {
        "type": "sequence_index",
        "label": "minimap2",
        "icon": "index",
        "pathKind": "file",
        "description": "minimap2 reference FASTA or .mmi index",
        "pathHint": "~/.h2ometa/databases/minimap2/reference.mmi",
        "anyPatterns": ["*.mmi", "*.fa", "*.fasta", "*.fna"],
        "toolProbe": {
            "packageSpec": "bioconda::minimap2",
            "commandTemplate": "minimap2 {path:q} /dev/null >/dev/null",
        },
    },
    "star": {
        "type": "sequence_index",
        "label": "STAR",
        "icon": "index",
        "pathKind": "directory",
        "description": "STAR genome index",
        "pathHint": "~/.h2ometa/databases/star/hg38",
        "requiredFiles": ["Genome", "SA", "SAindex"],
        "toolProbe": {
            "packageSpec": "bioconda::star",
            "commandTemplate": "STAR --genomeDir {path:q} --genomeLoad NoSharedMemory --runMode alignReads --readFilesIn /dev/null --outFileNamePrefix /tmp/h2ometa-star-probe- >/dev/null",
        },
    },
    "hisat2": {
        "type": "sequence_index",
        "label": "HISAT2",
        "icon": "index",
        "pathKind": "prefix",
        "description": "HISAT2 genome index",
        "pathHint": "~/.h2ometa/databases/hisat2/hg38",
        "prefixPatternSets": [
            [".1.ht2", ".2.ht2", ".3.ht2", ".4.ht2", ".5.ht2", ".6.ht2", ".7.ht2", ".8.ht2"],
            [".1.ht2l", ".2.ht2l", ".3.ht2l", ".4.ht2l", ".5.ht2l", ".6.ht2l", ".7.ht2l", ".8.ht2l"],
        ],
        "toolProbe": {
            "packageSpec": "bioconda::hisat2",
            "commandTemplate": "hisat2-inspect -s {prefix:q} >/dev/null",
        },
    },
    "salmon": {
        "type": "sequence_index",
        "label": "Salmon",
        "icon": "index",
        "pathKind": "directory",
        "description": "Salmon transcriptome index",
        "pathHint": "~/.h2ometa/databases/salmon/transcriptome",
        "anyFiles": ["versionInfo.json", "info.json"],
        "toolProbe": {
            "packageSpec": "bioconda::salmon",
            "commandTemplate": "salmon inspect -i {path:q} >/dev/null",
        },
    },
    "kallisto": {
        "type": "sequence_index",
        "label": "kallisto",
        "icon": "index",
        "pathKind": "file",
        "description": "kallisto transcriptome index",
        "pathHint": "~/.h2ometa/databases/kallisto/transcriptome.idx",
        "anyPatterns": ["*.idx"],
        "toolProbe": {
            "packageSpec": "bioconda::kallisto",
            "commandTemplate": "kallisto inspect {path:q} >/dev/null",
        },
    },
    "silva_qiime": {
        "type": "taxonomy",
        "label": "SILVA / QIIME",
        "icon": "taxonomy",
        "pathKind": "file",
        "description": "SILVA QIIME 2 classifier artifact",
        "pathHint": "~/.h2ometa/databases/silva/classifier.qza",
        "anyPatterns": ["*.qza"],
        "toolProbe": {
            "packageSpec": "qiime2::qiime2",
            "commandTemplate": "qiime tools validate {path:q} >/dev/null",
        },
    },
    "checkm": {
        "type": "taxonomy",
        "label": "CheckM2",
        "icon": "taxonomy",
        "pathKind": "file",
        "description": "CheckM2 UniRef100 KO DIAMOND database",
        "pathHint": "~/.h2ometa/databases/checkm2/CheckM2_database/uniref100.KO.1.dmnd",
        "anyPatterns": ["uniref100.KO*.dmnd"],
        "toolProbe": {
            "packageSpec": "bioconda::checkm2",
            "commandTemplate": "diamond dbinfo --db {path:q} >/dev/null && CHECKM2DB={path:q} checkm2 predict --help >/dev/null",
        },
    },
    "ncbi_taxonomy": {
        "type": "taxonomy",
        "label": "NCBI taxonomy",
        "icon": "taxonomy",
        "pathKind": "directory",
        "description": "NCBI taxdump taxonomy files",
        "pathHint": "~/.h2ometa/databases/ncbi_taxonomy/taxdump",
        "requiredFiles": ["nodes.dmp", "names.dmp"],
        "toolProbe": {
            "packageSpec": "bioconda::taxonkit",
            "commandTemplate": "printf '1\\n' | taxonkit --data-dir {path:q} list >/dev/null",
        },
    },
    "custom": {
        "type": "reference",
        "label": "Custom",
        "icon": "custom",
        "pathKind": "directory",
        "description": "未内置模板的自定义库",
        "pathHint": "~/.h2ometa/databases/custom/name",
        "requiredFiles": [],
    },
}


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reference_databases (
    database_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    db_type TEXT NOT NULL,
    version TEXT NOT NULL,
    path TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    size_bytes INTEGER,
    checksum TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT
);
"""


def list_database_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template_id,
            "name": str(template.get("label") or template_id),
            "type": str(template.get("type") or "reference"),
            "icon": str(template.get("icon") or "custom"),
            "pathKind": str(template.get("pathKind") or "directory"),
            "selectorKind": str(template.get("pathKind") or "directory"),
            "selector": {
                "kind": str(template.get("pathKind") or "directory"),
                "hint": str(template.get("pathHint") or ""),
            },
            "description": str(template.get("description") or ""),
            "pathHint": str(template.get("pathHint") or ""),
            "expectedFiles": _template_expected_files(template),
            "toolProbe": dict(template.get("toolProbe") or {}),
        }
        for template_id, template in DATABASE_TEMPLATES.items()
    ]


def list_reference_databases(cfg: RemoteRunnerConfig) -> list[dict[str, Any]]:
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            "SELECT * FROM reference_databases ORDER BY updated_at DESC, name ASC"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def fetch_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> dict[str, Any] | None:
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT * FROM reference_databases WHERE database_id = ?",
            (database_id,),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def add_reference_database(cfg: RemoteRunnerConfig, payload: dict[str, Any]) -> dict[str, Any]:
    item = _normalize_payload(payload)
    now = now_iso()
    existing = fetch_reference_database(cfg, item["id"])
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO reference_databases (
                database_id, name, db_type, version, path, description, source,
                manifest_path, size_bytes, checksum, metadata_json, status, message,
                created_at, updated_at, last_checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(database_id) DO UPDATE SET
                name = excluded.name,
                db_type = excluded.db_type,
                version = excluded.version,
                path = excluded.path,
                description = excluded.description,
                source = excluded.source,
                manifest_path = excluded.manifest_path,
                size_bytes = excluded.size_bytes,
                checksum = excluded.checksum,
                metadata_json = excluded.metadata_json,
                status = excluded.status,
                message = excluded.message,
                updated_at = excluded.updated_at
            """,
            (
                item["id"],
                item["name"],
                item["type"],
                item["version"],
                item["path"],
                item["description"],
                item["source"],
                item["manifestPath"],
                item.get("sizeBytes"),
                item["checksum"],
                json.dumps(item["metadata"], ensure_ascii=False),
                item["status"],
                item["message"],
                (existing or {}).get("createdAt") or now,
                now,
                (existing or {}).get("lastCheckedAt"),
            ),
        )
        connection.commit()
    saved = fetch_reference_database(cfg, item["id"])
    if saved is None:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
    return saved


def remove_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> None:
    normalized = str(database_id or "").strip()
    if not normalized:
        raise DatabaseRegistryError("DATABASE_ID_REQUIRED")
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        cursor = connection.execute("DELETE FROM reference_databases WHERE database_id = ?", (normalized,))
        connection.commit()
    if cursor.rowcount == 0:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")


def check_reference_database(cfg: RemoteRunnerConfig, database_id: str) -> dict[str, Any]:
    normalized = str(database_id or "").strip()
    if not normalized:
        raise DatabaseRegistryError("DATABASE_ID_REQUIRED")
    item = fetch_reference_database(cfg, normalized)
    if item is None:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")

    data_path = Path(str(item.get("path") or ""))
    manifest_path = Path(str(item.get("manifestPath") or "")) if item.get("manifestPath") else None
    metadata = dict(item.get("metadata") or {})
    template_id = str(metadata.get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id)
    path_kind = str((template or {}).get("pathKind") or "directory")
    if path_kind == "prefix":
        if not data_path.parent.exists():
            return _update_status(cfg, normalized, "missing", f"Database prefix parent does not exist: {data_path.parent}")
    elif not data_path.exists():
        return _update_status(cfg, normalized, "missing", f"Database path does not exist: {data_path}")
    if manifest_path is not None and not manifest_path.exists():
        return _update_status(cfg, normalized, "missing", f"Manifest path does not exist: {manifest_path}")
    if data_path.is_dir() and not any(data_path.iterdir()):
        return _update_status(cfg, normalized, "missing", f"Database directory is empty: {data_path}")
    resolved = database_validation.resolve_template_path(data_path, template or {})
    template_error = database_validation.validate_template_files(data_path, item, template, resolved=resolved)
    if template_error:
        return _update_status(cfg, normalized, "missing", template_error)
    if template is not None:
        metadata["resolvedPath"] = resolved
        probe = dict(template.get("toolProbe") or {})
        command = database_validation.render_tool_probe_command(template, data_path, resolved)
        if command:
            try:
                command = database_validation.prepare_tool_probe_command(cfg, template_id, template, command)
            except RuntimeError as exc:
                metadata.setdefault("validation", {})["toolProbe"] = {
                    "ok": False,
                    "command": command,
                    "returncode": 127,
                    "stdout": "",
                    "stderr": str(exc),
                }
                return _update_status(
                    cfg,
                    normalized,
                    "failed",
                    f"Tool probe failed for database template {template_id}: {exc}",
                    metadata=metadata,
                )
            result = database_validation.run_tool_probe(command, timeout=int(probe.get("timeoutSeconds") or 60))
            metadata.setdefault("validation", {})["toolProbe"] = database_validation.probe_metadata(result)
            if not result.ok:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
                return _update_status(
                    cfg,
                    normalized,
                    "failed",
                    f"Tool probe failed for database template {template_id}: {detail}",
                    metadata=metadata,
                )
    return _update_status(
        cfg,
        normalized,
        "available",
        "Database path and tool probe are available on the remote runner.",
        metadata=metadata,
    )


def resolve_run_databases(cfg: RemoteRunnerConfig, run_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    requested = run_spec.get("databases")
    if requested is None:
        return {}
    entries = requested if isinstance(requested, list) else [requested]
    resolved: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError("DATABASE_REFERENCE_INVALID")
        database_id = str(entry.get("id") or entry.get("databaseId") or "").strip()
        if not database_id:
            raise ValueError("DATABASE_ID_REQUIRED")
        database = fetch_reference_database(cfg, database_id)
        if database is None:
            raise ValueError("DATABASE_NOT_FOUND")
        if str((database.get("metadata") or {}).get("templateId") or "").strip():
            database = check_reference_database(cfg, database_id)
        role = str(entry.get("role") or entry.get("name") or database.get("type") or f"database_{index + 1}").strip()
        if not role:
            raise ValueError("DATABASE_ROLE_REQUIRED")
        status = str(database.get("status") or "")
        if status != "available":
            raise ValueError("DATABASE_UNAVAILABLE")
        data_path = Path(str(database.get("path") or ""))
        template_id = str((database.get("metadata") or {}).get("templateId") or "").strip().lower()
        template = DATABASE_TEMPLATES.get(template_id)
        metadata = dict(database.get("metadata") or {})
        resolved_path = dict(metadata.get("resolvedPath") or {})
        if str((template or {}).get("pathKind") or "") == "prefix":
            prefix_path = Path(str(resolved_path.get("prefix") or data_path))
            if database_validation.prefix_structure_error(prefix_path, template or {}):
                raise ValueError("DATABASE_PATH_MISSING")
        elif not data_path.exists():
            raise ValueError("DATABASE_PATH_MISSING")
        injected_path = str(resolved_path.get("prefix") or database["path"])
        if injected_path != database["path"]:
            metadata.setdefault("selectedPath", database["path"])
        resolved[role] = {
            "id": database["id"],
            "name": database["name"],
            "type": database["type"],
            "templateId": str((database.get("metadata") or {}).get("templateId") or ""),
            "version": database["version"],
            "path": injected_path,
            "manifestPath": database["manifestPath"],
            "checksum": database["checksum"],
            "metadata": metadata,
        }
    return resolved


def _ensure_schema(connection) -> None:
    connection.executescript(_SCHEMA_SQL)


def _row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["database_id"],
        "name": row["name"],
        "type": row["db_type"],
        "version": row["version"],
        "path": row["path"],
        "description": row["description"],
        "source": row["source"],
        "manifestPath": row["manifest_path"],
        "sizeBytes": row["size_bytes"],
        "checksum": row["checksum"],
        "metadata": json.loads(row["metadata_json"] or "{}"),
        "status": row["status"],
        "message": row["message"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "lastCheckedAt": row["last_checked_at"],
    }


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "dbType" in payload:
        raise DatabaseRegistryError("DATABASE_FIELD_UNSUPPORTED: dbType")
    name = str(payload.get("name") or "").strip()
    data_path = str(payload.get("path") or "").strip()
    if not name:
        raise DatabaseRegistryError("DATABASE_NAME_REQUIRED")
    if not data_path:
        raise DatabaseRegistryError("DATABASE_PATH_REQUIRED")
    metadata = dict(payload.get("metadata") or {})
    template_id = str(payload.get("templateId") or metadata.get("templateId") or "").strip().lower()
    template = DATABASE_TEMPLATES.get(template_id) if template_id else None
    if template_id and template is None:
        raise DatabaseRegistryError("DATABASE_TEMPLATE_UNSUPPORTED")
    if template_id:
        metadata["templateId"] = template_id
        metadata["templateLabel"] = str(template.get("label") or template_id)
    db_type = str(payload.get("type") or (template or {}).get("type") or "reference").strip()
    version = str(payload.get("version") or "").strip()
    database_id = str(payload.get("id") or "").strip() or _default_id(name=name, version=version, db_type=db_type)
    return {
        "id": database_id,
        "name": name,
        "type": db_type,
        "version": version,
        "path": data_path,
        "description": str(payload.get("description") or ""),
        "source": str(payload.get("source") or "manual"),
        "manifestPath": str(payload.get("manifestPath") or ""),
        "sizeBytes": payload.get("sizeBytes"),
        "checksum": str(payload.get("checksum") or ""),
        "metadata": metadata,
        "status": str(payload.get("status") or "declared"),
        "message": str(payload.get("message") or "Database declared."),
    }


def _update_status(
    cfg: RemoteRunnerConfig,
    database_id: str,
    status: str,
    message: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checked_at = now_iso()
    with get_connection(cfg) as connection:
        _ensure_schema(connection)
        if metadata is None:
            cursor = connection.execute(
                """
                UPDATE reference_databases
                SET status = ?, message = ?, updated_at = ?, last_checked_at = ?
                WHERE database_id = ?
                """,
                (status, message, checked_at, checked_at, database_id),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE reference_databases
                SET status = ?, message = ?, metadata_json = ?, updated_at = ?, last_checked_at = ?
                WHERE database_id = ?
                """,
                (status, message, json.dumps(metadata, ensure_ascii=False), checked_at, checked_at, database_id),
            )
        connection.commit()
    if cursor.rowcount == 0:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
    item = fetch_reference_database(cfg, database_id)
    if item is None:
        raise DatabaseRegistryError("DATABASE_NOT_FOUND")
    return item


def _default_id(*, name: str, version: str, db_type: str) -> str:
    raw = "::".join(part for part in [db_type, name, version] if part)
    return "".join(char.lower() if char.isalnum() else "-" for char in raw).strip("-") or "database"


def _template_expected_files(template: dict[str, Any]) -> list[str]:
    values: list[str] = []
    values.extend(str(item) for item in template.get("requiredFiles", []) if str(item).strip())
    values.extend(str(item) for item in template.get("requiredPatterns", []) if str(item).strip())
    values.extend(str(item) for item in template.get("anyPatterns", []) if str(item).strip())
    values.extend(str(item) for item in template.get("anyIndexPatterns", []) if str(item).strip())
    values.extend(str(item) for item in template.get("anyFiles", []) if str(item).strip())
    for pattern_set in template.get("prefixPatternSets", []):
        values.append("prefix" + " + prefix".join(str(item) for item in pattern_set if str(item).strip()))
    values.extend(str(item) for item in template.get("prefixAliasPatterns", []) if str(item).strip())
    values.extend(str(item) for item in template.get("companionSuffixes", []) if str(item).strip())
    for pattern_set in template.get("anyPatternSets", []):
        values.append(" / ".join(str(item) for item in pattern_set if str(item).strip()))
    return values
