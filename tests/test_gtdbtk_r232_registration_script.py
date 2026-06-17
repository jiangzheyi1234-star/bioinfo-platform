from apps.remote_runner.database_pack_catalog import list_downloadable_database_packs
from scripts.register_gtdbtk_r232_database import (
    DEFAULT_DATABASE_ID,
    DEFAULT_PACK_ID,
    GTDBTK_R232_ARCHIVE_BYTES,
    GTDBTK_R232_MD5,
    GTDBTK_R232_SOURCE_URL,
    build_database_payload,
    parse_status_tsv,
    validate_remote_status_ready,
)


def test_parse_status_tsv_reads_ready_state_and_paths() -> None:
    parsed = parse_status_tsv(
        "state\tready\t2026-06-16T18:00:00+08:00\n"
        "archive\t/home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz\n"
        "ready_dir\t/home/zyserver/databases/gtdbtk-r232-official/extracted/release\n"
        f"md5\t{GTDBTK_R232_MD5}\n"
    )

    assert parsed["state"] == "ready"
    assert parsed["stateAt"] == "2026-06-16T18:00:00+08:00"
    assert parsed["ready_dir"].endswith("/extracted/release")
    assert parsed["md5"] == GTDBTK_R232_MD5


def test_build_database_payload_uses_official_gtdbtk_contract() -> None:
    payload = build_database_payload(
        database_id=DEFAULT_DATABASE_ID,
        ready_dir="/home/zyserver/databases/gtdbtk-r232-official/extracted/release",
        archive_path="/home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz",
    )

    assert payload["id"] == DEFAULT_DATABASE_ID
    assert payload["templateId"] == "gtdbtk"
    assert payload["version"] == "R232"
    assert payload["path"].endswith("/extracted/release")
    assert payload["databaseLayer"] == "production_full"
    assert payload["sizeBytes"] == GTDBTK_R232_ARCHIVE_BYTES
    assert payload["checksum"] == f"md5:{GTDBTK_R232_MD5}"
    assert payload["metadata"]["databaseLayer"] == "production_full"
    assert payload["metadata"]["archiveMd5"] == GTDBTK_R232_MD5


def test_gtdbtk_registration_payload_matches_downloadable_pack_catalog() -> None:
    pack = {item["packId"]: item for item in list_downloadable_database_packs()}[DEFAULT_PACK_ID]
    payload = build_database_payload(
        database_id=DEFAULT_DATABASE_ID,
        ready_dir="/home/zyserver/databases/gtdbtk-r232-official/extracted/release",
        archive_path="/home/zyserver/databases/gtdbtk-r232-official/download/gtdbtk_r232_data.tar.gz",
    )
    metadata = payload["metadata"]

    assert pack["sourceUrl"] == payload["source"] == GTDBTK_R232_SOURCE_URL
    assert pack["checksum"] == payload["checksum"] == f"md5:{GTDBTK_R232_MD5}"
    assert pack["archiveSizeBytes"] == payload["sizeBytes"] == GTDBTK_R232_ARCHIVE_BYTES
    assert pack["installedLayer"] == payload["databaseLayer"] == "production_full"
    assert metadata["packId"] == metadata["installedFromPackId"] == pack["packId"]
    assert metadata["packVersion"] == pack["version"]
    assert metadata["packSourceUrl"] == pack["sourceUrl"]
    assert metadata["packChecksum"] == pack["checksum"]
    assert metadata["packArchiveSizeBytes"] == pack["archiveSizeBytes"]
    assert metadata["installationMethod"] == pack["installMode"] == "manual_external"


def test_validate_remote_status_ready_rejects_missing_structure_checks() -> None:
    try:
        validate_remote_status_ready(
            {
                "state": "ready",
                "readyDir": "/db/gtdbtk",
                "md5": GTDBTK_R232_MD5,
                "checks": {
                    "archiveExists": True,
                    "readyDirExists": True,
                    "requiredDirsPresent": False,
                    "metadataTxtPresent": True,
                },
            }
        )
    except SystemExit as exc:
        assert "requiredDirsPresent" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("missing GTDB-Tk required directories must block registration")


def test_validate_remote_status_ready_accepts_complete_structure_checks() -> None:
    validate_remote_status_ready(
        {
            "state": "ready",
            "readyDir": "/db/gtdbtk",
            "md5": GTDBTK_R232_MD5,
            "checks": {
                "archiveExists": True,
                "readyDirExists": True,
                "requiredDirsPresent": True,
                "metadataTxtPresent": True,
            },
        }
    )
