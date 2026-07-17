"""Bounded two-pass inspection of one deterministic USTAR gzip byte stream.

This module parses the raw gzip and 512-byte USTAR envelopes itself.  It never
extracts a member, follows a link, opens a path, or writes a filesystem object.
The caller supplies positional reads from one already-held regular file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import re
import zlib

from core.contracts.runner_activation_release_archive import (
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_SIZE_BYTES,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_UNCOMPRESSED_SIZE_BYTES,
)
from core.contracts.runner_activation_release_archive_graph import (
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS,
    RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES,
    require_runner_activation_release_archive_members,
)
from core.contracts.runner_activation_release_bootstrap_manifest import (
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES,
    RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH,
)
from core.contracts.runner_activation_validation import canonical_json


_BLOCK_BYTES = 512
_COMPRESSED_READ_BYTES = 64 * 1024
_DECOMPRESSED_CHUNK_BYTES = 64 * 1024
_ZERO_BLOCK = bytes(_BLOCK_BYTES)
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_USTAR_MAGIC = b"ustar\0"
_USTAR_VERSION = b"00"
_GZIP_HEADER_BYTES = 10
_GZIP_FIXED_PREFIX = b"\x1f\x8b\x08"


class _ArchivePolicyError(Exception):
    """Private detailed failure that is redacted at the public boundary."""


@dataclass(frozen=True, slots=True)
class _ArchiveContentInspection:
    artifact_archive_sha256: str
    artifact_archive_size_bytes: int
    members: tuple[dict[str, object], ...]
    bootstrap_manifest_bytes: bytes
    uncompressed_archive_size_bytes: int


@dataclass(frozen=True, slots=True)
class _ArchivePass:
    members: tuple[dict[str, object], ...]
    bootstrap_manifest_bytes: bytes
    uncompressed_archive_size_bytes: int
    compressed_sha256: str


@dataclass(frozen=True, slots=True)
class _RawHeader:
    path: str
    member_type: str
    mode: str
    size_bytes: int
    link_target: str
    is_root: bool


class _SingleMemberGzipReader:
    """Sequential bounded gzip reader backed by private positional reads."""

    def __init__(
        self,
        read_at: Callable[[int, int], bytes],
        *,
        archive_size: int,
        raw_limit: int,
    ) -> None:
        self._read_at = read_at
        self._archive_size = archive_size
        self._raw_limit = raw_limit
        self._compressed_offset = 0
        self._compressed_sha256 = hashlib.sha256()
        self._decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self._pending_compressed = b""
        self._output = bytearray()
        self._raw_generated = 0
        self._gzip_header = bytearray()
        self._gzip_header_validated = False
        self._complete = False

    def read(self, size: int) -> bytes:
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("gzip read size must be a positive integer")
        while not self._output and not self._complete:
            self._pump()
        if not self._output:
            return b""
        count = min(size, len(self._output))
        result = bytes(self._output[:count])
        del self._output[:count]
        return result

    @property
    def raw_size(self) -> int:
        if not self._complete or self._output:
            raise _ArchivePolicyError("gzip stream was not fully consumed")
        return self._raw_generated

    @property
    def compressed_sha256(self) -> str:
        if not self._complete or self._output:
            raise _ArchivePolicyError("gzip stream was not fully consumed")
        return f"sha256:{self._compressed_sha256.hexdigest()}"

    def _pump(self) -> None:
        while not self._output and not self._complete:
            compressed = self._next_compressed_input()
            if compressed is None:
                if not self._decompressor.eof:
                    raise _ArchivePolicyError("gzip stream is truncated")
                self._finish()
                continue
            limit = min(
                _DECOMPRESSED_CHUNK_BYTES,
                max(1, self._raw_limit - self._raw_generated + 1),
            )
            try:
                output = self._decompressor.decompress(compressed, limit)
            except zlib.error as exc:
                raise _ArchivePolicyError("gzip stream is invalid") from exc
            self._pending_compressed = self._decompressor.unconsumed_tail
            self._append_output(output)
            if self._decompressor.eof:
                if (
                    self._decompressor.unused_data
                    or self._pending_compressed
                    or self._compressed_offset != self._archive_size
                ):
                    raise _ArchivePolicyError(
                        "gzip stream has a second member or trailing bytes"
                    )
                self._finish()

    def _next_compressed_input(self) -> bytes | None:
        if self._pending_compressed:
            result = self._pending_compressed
            self._pending_compressed = b""
            return result
        if self._compressed_offset == self._archive_size:
            return None
        requested = min(
            _COMPRESSED_READ_BYTES,
            self._archive_size - self._compressed_offset,
        )
        chunk = self._read_at(self._compressed_offset, requested)
        if (
            not isinstance(chunk, bytes)
            or not chunk
            or len(chunk) > requested
        ):
            raise _ArchivePolicyError("compressed archive read is unstable")
        self._compressed_offset += len(chunk)
        self._compressed_sha256.update(chunk)
        if not self._gzip_header_validated:
            needed = _GZIP_HEADER_BYTES - len(self._gzip_header)
            self._gzip_header.extend(chunk[:needed])
            if len(self._gzip_header) == _GZIP_HEADER_BYTES:
                _require_deterministic_gzip_header(bytes(self._gzip_header))
                self._gzip_header_validated = True
        return chunk

    def _append_output(self, value: bytes) -> None:
        if not value:
            return
        self._raw_generated += len(value)
        if self._raw_generated > self._raw_limit:
            raise _ArchivePolicyError("decompressed archive exceeds policy")
        self._output.extend(value)

    def _finish(self) -> None:
        if not self._gzip_header_validated:
            raise _ArchivePolicyError("gzip header is truncated")
        try:
            tail = self._decompressor.flush()
        except zlib.error as exc:
            raise _ArchivePolicyError("gzip trailer is invalid") from exc
        self._append_output(tail)
        self._complete = True


def _inspect_archive_content(
    read_at: Callable[[int, int], bytes],
    *,
    archive_size: int,
    expected_archive_sha256: str,
    between_passes: Callable[[], None] | None = None,
) -> _ArchiveContentInspection:
    """Return exact semantic evidence only when two raw passes are identical."""

    if not callable(read_at):
        raise ValueError("archive positional reader is required")
    if (
        isinstance(archive_size, bool)
        or not isinstance(archive_size, int)
        or not 0 < archive_size <= RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_SIZE_BYTES
    ):
        raise ValueError("archive size is invalid")
    if (
        not isinstance(expected_archive_sha256, str)
        or _SHA256_PATTERN.fullmatch(expected_archive_sha256) is None
    ):
        raise ValueError("archive SHA-256 is invalid")
    if between_passes is not None and not callable(between_passes):
        raise ValueError("between-pass proof must be callable")

    raw_limit = min(
        RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_UNCOMPRESSED_SIZE_BYTES,
        max(
            RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES,
            archive_size * RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO,
        ),
    )
    first = _scan_archive_pass(
        read_at,
        archive_size=archive_size,
        raw_limit=raw_limit,
        expected_archive_sha256=expected_archive_sha256,
    )
    if between_passes is not None:
        between_passes()
    second = _scan_archive_pass(
        read_at,
        archive_size=archive_size,
        raw_limit=raw_limit,
        expected_archive_sha256=expected_archive_sha256,
    )
    if first != second:
        raise _ArchivePolicyError("archive observations differ between passes")
    return _ArchiveContentInspection(
        artifact_archive_sha256=expected_archive_sha256,
        artifact_archive_size_bytes=archive_size,
        members=second.members,
        bootstrap_manifest_bytes=second.bootstrap_manifest_bytes,
        uncompressed_archive_size_bytes=second.uncompressed_archive_size_bytes,
    )


def _scan_archive_pass(
    read_at: Callable[[int, int], bytes],
    *,
    archive_size: int,
    raw_limit: int,
    expected_archive_sha256: str,
) -> _ArchivePass:
    stream = _SingleMemberGzipReader(
        read_at,
        archive_size=archive_size,
        raw_limit=raw_limit,
    )
    members: list[dict[str, object]] = []
    paths: set[str] = set()
    bootstrap_bytes: bytes | None = None
    root_seen = False
    end_blocks = 0
    total_payload_bytes = 0
    total_metadata_bytes = 0

    while True:
        block = _read_exact_or_eof(stream, _BLOCK_BYTES)
        if block is None:
            break
        if block == _ZERO_BLOCK:
            end_blocks += 1
            continue
        if end_blocks:
            raise _ArchivePolicyError("tar stream has data after an end block")
        header = _parse_raw_header(block)
        if header.is_root:
            if root_seen:
                raise _ArchivePolicyError("tar stream repeats the root header")
            root_seen = True
            continue
        if len(members) >= RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBERS:
            raise _ArchivePolicyError("tar member count exceeds policy")
        if header.path in paths:
            raise _ArchivePolicyError("tar member normalization collides")
        paths.add(header.path)

        content_sha256 = ""
        payload = b""
        if header.member_type == "file":
            if header.size_bytes > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_BYTES:
                raise _ArchivePolicyError("tar member size exceeds policy")
            total_payload_bytes += header.size_bytes
            if total_payload_bytes > RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_TOTAL_BYTES:
                raise _ArchivePolicyError("tar payload size exceeds policy")
            keep_payload = header.path == RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_PATH
            if keep_payload and (
                header.size_bytes > RUNNER_ACTIVATION_RELEASE_BOOTSTRAP_MANIFEST_MAX_BYTES
            ):
                raise _ArchivePolicyError("bootstrap manifest exceeds policy")
            content_sha256, payload = _consume_regular_payload(
                stream,
                size_bytes=header.size_bytes,
                keep_payload=keep_payload,
            )
            if keep_payload:
                bootstrap_bytes = payload
        member = {
            "contentSha256": content_sha256,
            "linkTarget": header.link_target,
            "mode": header.mode,
            "path": header.path,
            "sizeBytes": header.size_bytes,
            "type": header.member_type,
        }
        total_metadata_bytes += len(canonical_json(member).encode("utf-8"))
        if total_metadata_bytes > (
            RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_MEMBER_METADATA_BYTES
        ):
            raise _ArchivePolicyError("tar member metadata exceeds policy")
        members.append(member)

    if end_blocks < 2:
        raise _ArchivePolicyError("tar stream lacks two end-of-archive blocks")
    if bootstrap_bytes is None:
        raise _ArchivePolicyError("bootstrap manifest member is absent")
    raw_size = stream.raw_size
    compressed_sha256 = stream.compressed_sha256
    if compressed_sha256 != expected_archive_sha256:
        raise _ArchivePolicyError("compressed archive digest does not match")
    members.sort(key=lambda item: str(item["path"]))
    try:
        normalized_members, _metadata_bytes = (
            require_runner_activation_release_archive_members(members)
        )
    except ValueError as exc:
        raise _ArchivePolicyError("tar member graph is outside policy") from exc
    return _ArchivePass(
        members=tuple(normalized_members),
        bootstrap_manifest_bytes=bootstrap_bytes,
        uncompressed_archive_size_bytes=raw_size,
        compressed_sha256=compressed_sha256,
    )


def _parse_raw_header(block: bytes) -> _RawHeader:
    if len(block) != _BLOCK_BYTES:
        raise _ArchivePolicyError("tar header is truncated")
    expected_checksum = _parse_checksum(block[148:156])
    actual_checksum = sum(block[:148]) + (8 * 0x20) + sum(block[156:])
    if expected_checksum != actual_checksum:
        raise _ArchivePolicyError("tar header checksum is invalid")
    if block[257:263] != _USTAR_MAGIC or block[263:265] != _USTAR_VERSION:
        raise _ArchivePolicyError("tar header is not deterministic USTAR")
    if block[500:512] != bytes(12):
        raise _ArchivePolicyError("tar header padding is nonzero")
    if _parse_octal(block[108:116], field="uid") != 0:
        raise _ArchivePolicyError("tar uid is outside policy")
    if _parse_octal(block[116:124], field="gid") != 0:
        raise _ArchivePolicyError("tar gid is outside policy")
    if _parse_octal(block[136:148], field="mtime") != 0:
        raise _ArchivePolicyError("tar mtime is outside policy")
    if _parse_tar_text(block[265:297], field="uname"):
        raise _ArchivePolicyError("tar uname is outside policy")
    if _parse_tar_text(block[297:329], field="gname"):
        raise _ArchivePolicyError("tar gname is outside policy")
    if block[329:345] != bytes(16):
        raise _ArchivePolicyError("tar device metadata is outside policy")

    name = _parse_tar_text(block[0:100], field="name")
    prefix = _parse_tar_text(block[345:500], field="prefix")
    if not name:
        raise _ArchivePolicyError("tar member name is empty")
    raw_path = f"{prefix}/{name}" if prefix else name
    link_target = _parse_tar_text(block[157:257], field="linkname")
    size_bytes = _parse_octal(block[124:136], field="size")
    mode_value = _parse_octal(block[100:108], field="mode")
    type_flag = block[156:157]
    if type_flag == b"0":
        member_type = "file"
        allowed_modes = {0o644, 0o755}
    elif type_flag == b"5":
        member_type = "directory"
        allowed_modes = {0o755}
    elif type_flag == b"2":
        member_type = "symlink"
        allowed_modes = {0o777}
    elif type_flag == b"1":
        member_type = "hardlink"
        allowed_modes = {0o644, 0o755}
    else:
        raise _ArchivePolicyError("tar member type is outside policy")
    if mode_value not in allowed_modes:
        raise _ArchivePolicyError("tar member mode is outside policy")
    if member_type != "file" and size_bytes != 0:
        raise _ArchivePolicyError("non-file tar member has a payload")
    if member_type in {"file", "directory"} and link_target:
        raise _ArchivePolicyError("non-link tar member has a link target")
    if member_type in {"symlink", "hardlink"} and not link_target:
        raise _ArchivePolicyError("link tar member lacks a target")

    normalized_path, is_root = _normalize_raw_member_path(
        raw_path,
        is_directory=member_type == "directory",
    )
    normalized_target = link_target
    if member_type == "hardlink" and normalized_target.startswith("./"):
        normalized_target = normalized_target[2:]
    return _RawHeader(
        path=normalized_path,
        member_type=member_type,
        mode=f"{mode_value:04o}",
        size_bytes=size_bytes,
        link_target=normalized_target,
        is_root=is_root,
    )


def _normalize_raw_member_path(
    raw_path: str,
    *,
    is_directory: bool,
) -> tuple[str, bool]:
    if is_directory and raw_path in {".", "./"}:
        return "", True
    if is_directory:
        if not raw_path.endswith("/") or raw_path.endswith("//"):
            raise _ArchivePolicyError(
                "tar directory name lacks one canonical trailing slash"
            )
        raw_path = raw_path[:-1]
    elif raw_path.endswith("/"):
        raise _ArchivePolicyError("non-directory tar name has a trailing slash")
    if raw_path.startswith("./"):
        raw_path = raw_path[2:]
    if not raw_path:
        raise _ArchivePolicyError("tar member name is empty after normalization")
    return raw_path, False


def _consume_regular_payload(
    stream: _SingleMemberGzipReader,
    *,
    size_bytes: int,
    keep_payload: bool,
) -> tuple[str, bytes]:
    digest = hashlib.sha256()
    retained = bytearray()
    remaining = size_bytes
    while remaining:
        chunk = _read_exact(stream, min(_DECOMPRESSED_CHUNK_BYTES, remaining))
        digest.update(chunk)
        if keep_payload:
            retained.extend(chunk)
        remaining -= len(chunk)
    padding_size = (-size_bytes) % _BLOCK_BYTES
    if padding_size and _read_exact(stream, padding_size) != bytes(padding_size):
        raise _ArchivePolicyError("tar payload padding is nonzero")
    return f"sha256:{digest.hexdigest()}", bytes(retained)


def _read_exact_or_eof(
    stream: _SingleMemberGzipReader,
    size: int,
) -> bytes | None:
    chunks: list[bytes] = []
    total = 0
    while total < size:
        chunk = stream.read(size - total)
        if not chunk:
            if total == 0:
                return None
            raise _ArchivePolicyError("decompressed tar record is truncated")
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _read_exact(stream: _SingleMemberGzipReader, size: int) -> bytes:
    result = _read_exact_or_eof(stream, size)
    if result is None:
        raise _ArchivePolicyError("decompressed tar payload is truncated")
    return result


def _parse_octal(value: bytes, *, field: str) -> int:
    if (
        len(value) < 2
        or value[-1:] != b"\0"
        or any(byte < ord("0") or byte > ord("7") for byte in value[:-1])
    ):
        raise _ArchivePolicyError(f"tar {field} is non-octal")
    return int(value[:-1], 8)


def _parse_checksum(value: bytes) -> int:
    if (
        len(value) != 8
        or value[6:] != b"\0 "
        or any(byte < ord("0") or byte > ord("7") for byte in value[:6])
    ):
        raise _ArchivePolicyError("tar checksum is non-octal")
    return int(value[:6], 8)


def _parse_tar_text(value: bytes, *, field: str) -> str:
    terminator = value.find(b"\0")
    if terminator >= 0:
        if value[terminator + 1 :] != bytes(len(value) - terminator - 1):
            raise _ArchivePolicyError(f"tar {field} has data after NUL")
        value = value[:terminator]
    if any(byte < 0x20 or byte > 0x7E for byte in value):
        raise _ArchivePolicyError(f"tar {field} is not printable ASCII")
    return value.decode("ascii")


def _require_deterministic_gzip_header(value: bytes) -> None:
    if (
        len(value) != _GZIP_HEADER_BYTES
        or value[:3] != _GZIP_FIXED_PREFIX
        or value[3] != 0
        or value[4:8] != bytes(4)
    ):
        raise _ArchivePolicyError("gzip header is outside deterministic policy")


__all__: list[str] = []
