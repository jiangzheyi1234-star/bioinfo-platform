"""Deterministic raw archives for release-inspector acceptance tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
import gzip
import hashlib
import io
import json
import tarfile
from typing import Final

from core.contracts.runner_activation_target import RUNNER_ACTIVATION_SERVICE
from core.contracts.runner_protocol import (
    build_runner_protocol_descriptor,
    runner_protocol_descriptor_fingerprint,
)


TAR_BLOCK_BYTES: Final = 512


@dataclass(frozen=True, slots=True)
class RawArchiveMember:
    """One semantic USTAR member with deliberately explicit raw metadata."""

    name: str
    type: bytes
    mode: int
    payload: bytes = b""
    linkname: str = ""
    uid: int = 0
    gid: int = 0
    mtime: int = 0
    uname: str = ""
    gname: str = ""
    devmajor: int = 0
    devminor: int = 0
    pax_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RawTarRecord:
    """Location and decoded structural fields for one physical tar record."""

    header_offset: int
    payload_offset: int
    padded_payload_size: int
    name: bytes
    size: int
    type: bytes


def bootstrap_manifest_bytes(
    *,
    version: str = "0.2.0",
    platform: str = "linux-64",
) -> bytes:
    descriptor = build_runner_protocol_descriptor()
    return json.dumps(
        {
            "platform": platform,
            "runnerProtocol": descriptor,
            "runnerProtocolFingerprint": runner_protocol_descriptor_fingerprint(
                descriptor
            ),
            "runtime": {
                "provider": "bundled",
                "python": "runtime/bin/python",
                "sqlite": {"minimumVersion": "3.51.3"},
            },
            "service": RUNNER_ACTIVATION_SERVICE,
            "version": version,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def valid_archive_members() -> list[RawArchiveMember]:
    bootstrap = bootstrap_manifest_bytes()
    return [
        RawArchiveMember("./", tarfile.DIRTYPE, 0o755),
        RawArchiveMember("./bin/", tarfile.DIRTYPE, 0o755),
        RawArchiveMember(
            "./bin/runner",
            tarfile.REGTYPE,
            0o755,
            payload=b"#!/bin/sh\nexit 0\n",
        ),
        RawArchiveMember(
            "./bootstrap_manifest.json",
            tarfile.REGTYPE,
            0o644,
            payload=bootstrap,
        ),
        RawArchiveMember("./lib/", tarfile.DIRTYPE, 0o755),
        RawArchiveMember(
            "./lib/data-copy",
            tarfile.LNKTYPE,
            0o644,
            linkname="./lib/z-data",
        ),
        RawArchiveMember(
            "./lib/z-data",
            tarfile.REGTYPE,
            0o644,
            payload=b"payload\n",
        ),
        RawArchiveMember(
            "./runner-link",
            tarfile.SYMTYPE,
            0o777,
            linkname="bin/runner",
        ),
    ]


def build_ustar(
    members: list[RawArchiveMember] | tuple[RawArchiveMember, ...] | None = None,
) -> bytes:
    """Build a deterministic USTAR stream, including its zero record padding."""

    selected = valid_archive_members() if members is None else list(members)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for member in selected:
            info = tarfile.TarInfo(member.name)
            info.type = member.type
            info.mode = member.mode
            info.uid = member.uid
            info.gid = member.gid
            info.mtime = member.mtime
            info.uname = member.uname
            info.gname = member.gname
            info.linkname = member.linkname
            info.devmajor = member.devmajor
            info.devminor = member.devminor
            info.pax_headers = dict(member.pax_headers)
            info.size = (
                len(member.payload) if member.type in tarfile.REGULAR_TYPES else 0
            )
            payload = io.BytesIO(member.payload) if info.isreg() else None
            archive.addfile(info, payload)
    return output.getvalue()


def gzip_ustar(raw_tar: bytes, *, compresslevel: int = 9) -> bytes:
    """Wrap a raw tar in the frozen one-member, FLG=0, mtime=0 gzip shape."""

    encoded = gzip.compress(raw_tar, compresslevel=compresslevel, mtime=0)
    assert encoded[:4] == b"\x1f\x8b\x08\x00"
    assert encoded[4:8] == b"\x00\x00\x00\x00"
    return encoded


def build_valid_archive() -> bytes:
    return gzip_ustar(build_ustar())


def archive_sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def iter_raw_tar_records(raw_tar: bytes) -> list[RawTarRecord]:
    """Return physical records up to the first zero header."""

    records: list[RawTarRecord] = []
    offset = 0
    while offset + TAR_BLOCK_BYTES <= len(raw_tar):
        header = raw_tar[offset : offset + TAR_BLOCK_BYTES]
        if header == bytes(TAR_BLOCK_BYTES):
            break
        size = _parse_octal(header[124:136])
        padded_size = _padded_size(size)
        records.append(
            RawTarRecord(
                header_offset=offset,
                payload_offset=offset + TAR_BLOCK_BYTES,
                padded_payload_size=padded_size,
                name=header[:100].split(b"\0", 1)[0],
                size=size,
                type=header[156:157],
            )
        )
        offset += TAR_BLOCK_BYTES + padded_size
    return records


def find_raw_tar_record(raw_tar: bytes, raw_name: bytes) -> RawTarRecord:
    matches = [
        record for record in iter_raw_tar_records(raw_tar) if record.name == raw_name
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected one raw member {raw_name!r}, found {len(matches)}"
        )
    return matches[0]


def replace_member(
    members: list[RawArchiveMember],
    selected_name: str,
    **changes: object,
) -> list[RawArchiveMember]:
    replaced = False
    result: list[RawArchiveMember] = []
    for member in members:
        if member.name == selected_name:
            member = replace(member, **changes)
            replaced = True
        result.append(member)
    if not replaced:
        raise AssertionError(f"missing fixture member {selected_name}")
    return result


def patch_header_field(
    raw_tar: bytes,
    *,
    raw_name: bytes,
    start: int,
    width: int,
    value: bytes,
) -> bytes:
    """Patch one raw field and restore the containing header checksum."""

    if len(value) != width:
        raise ValueError("patched field has the wrong width")
    record = find_raw_tar_record(raw_tar, raw_name)
    mutable = bytearray(raw_tar)
    absolute = record.header_offset + start
    mutable[absolute : absolute + width] = value
    _write_checksum(mutable, record.header_offset)
    return bytes(mutable)


def patch_member_payload(
    raw_tar: bytes,
    *,
    raw_name: bytes,
    payload: bytes,
) -> bytes:
    record = find_raw_tar_record(raw_tar, raw_name)
    if len(payload) != record.size:
        raise ValueError("replacement payload must preserve the declared size")
    mutable = bytearray(raw_tar)
    mutable[record.payload_offset : record.payload_offset + record.size] = payload
    return bytes(mutable)


def first_zero_header_offset(raw_tar: bytes) -> int:
    records = iter_raw_tar_records(raw_tar)
    if not records:
        return 0
    final = records[-1]
    return final.payload_offset + final.padded_payload_size


def _padded_size(size: int) -> int:
    return ((size + TAR_BLOCK_BYTES - 1) // TAR_BLOCK_BYTES) * TAR_BLOCK_BYTES


def _parse_octal(field: bytes) -> int:
    stripped = field.rstrip(b"\0 ").lstrip(b" ")
    return int(stripped or b"0", 8)


def _write_checksum(mutable: bytearray, header_offset: int) -> None:
    checksum_offset = header_offset + 148
    mutable[checksum_offset : checksum_offset + 8] = b"        "
    checksum = sum(mutable[header_offset : header_offset + TAR_BLOCK_BYTES])
    mutable[checksum_offset : checksum_offset + 8] = (
        f"{checksum:06o}".encode("ascii") + b"\0 "
    )


__all__ = [
    "RawArchiveMember",
    "RawTarRecord",
    "TAR_BLOCK_BYTES",
    "archive_sha256",
    "bootstrap_manifest_bytes",
    "build_ustar",
    "build_valid_archive",
    "find_raw_tar_record",
    "first_zero_header_offset",
    "gzip_ustar",
    "iter_raw_tar_records",
    "patch_header_field",
    "patch_member_payload",
    "replace_member",
    "valid_archive_members",
]
