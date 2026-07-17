from __future__ import annotations

import tarfile

import pytest

from apps.remote_runner import activation_release_tar_inspection as inspection
from tests.helpers.runner_activation_release_archive import (
    RawArchiveMember,
    archive_sha256,
    build_ustar,
    build_valid_archive,
    find_raw_tar_record,
    first_zero_header_offset,
    gzip_ustar,
    patch_header_field,
    patch_member_payload,
    replace_member,
    valid_archive_members,
)


def _inspect(
    archive: bytes,
    *,
    expected_sha256: str | None = None,
    archive_size: int | None = None,
):
    return inspection._inspect_archive_content(
        lambda offset, size: archive[offset : offset + size],
        archive_size=len(archive) if archive_size is None else archive_size,
        expected_archive_sha256=(
            archive_sha256(archive) if expected_sha256 is None else expected_sha256
        ),
    )


def _rejected():
    return inspection._ArchivePolicyError


def _octal(value: int, width: int) -> bytes:
    return f"{value:0{width - 1}o}".encode("ascii") + b"\0"


def _name_field(value: bytes) -> bytes:
    if len(value) >= 100:
        raise ValueError("fixture name must fit the USTAR name field")
    return value + bytes(100 - len(value))


def _with_type(raw_tar: bytes, raw_name: bytes, type_flag: bytes) -> bytes:
    return patch_header_field(
        raw_tar,
        raw_name=raw_name,
        start=156,
        width=1,
        value=type_flag,
    )


def test_valid_archive_is_inspected_twice_from_independent_offsets() -> None:
    archive = build_valid_archive()
    offsets: list[int] = []

    def read_at(offset: int, size: int) -> bytes:
        offsets.append(offset)
        return archive[offset : offset + size]

    observed = inspection._inspect_archive_content(
        read_at,
        archive_size=len(archive),
        expected_archive_sha256=archive_sha256(archive),
    )

    assert observed is not None
    assert offsets.count(0) >= 2


def test_archive_identity_is_not_self_asserted_by_the_inspector() -> None:
    archive = build_valid_archive()

    with pytest.raises(_rejected()):
        _inspect(archive, expected_sha256="sha256:" + "0" * 64)
    with pytest.raises(_rejected()):
        _inspect(archive, archive_size=len(archive) - 1)
    with pytest.raises(_rejected()):
        _inspect(archive, archive_size=len(archive) + 1)


@pytest.mark.parametrize("root_name", [b".", b"./"])
def test_root_header_policy_accepts_exactly_one_root_directory(
    root_name: bytes,
) -> None:
    raw = build_ustar()
    raw = patch_header_field(
        raw,
        raw_name=b"./",
        start=0,
        width=100,
        value=_name_field(root_name),
    )

    assert _inspect(gzip_ustar(raw)) is not None


def test_archive_without_a_root_header_is_valid() -> None:
    members = valid_archive_members()[1:]

    assert _inspect(gzip_ustar(build_ustar(members))) is not None


def test_duplicate_root_header_is_rejected() -> None:
    members = valid_archive_members()
    members.insert(1, members[0])

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(build_ustar(members)))


@pytest.mark.parametrize(
    "raw_name",
    [
        b"././bin/runner",
        b"/bin/runner",
        b"../bin/runner",
        b"./bin//runner",
        b"./bin/../runner",
        b"./bin\\runner",
    ],
)
def test_raw_member_name_policy_removes_only_one_prefix(raw_name: bytes) -> None:
    raw = patch_header_field(
        build_ustar(),
        raw_name=b"./bin/runner",
        start=0,
        width=100,
        value=_name_field(raw_name),
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


@pytest.mark.parametrize("raw_name", [b"./bin", b"./bin//"])
def test_directory_requires_exactly_one_trailing_slash(raw_name: bytes) -> None:
    raw = patch_header_field(
        build_ustar(),
        raw_name=b"./bin/",
        start=0,
        width=100,
        value=_name_field(raw_name),
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


def test_non_directory_rejects_a_trailing_slash() -> None:
    raw = patch_header_field(
        build_ustar(),
        raw_name=b"./bin/runner",
        start=0,
        width=100,
        value=_name_field(b"./bin/runner/"),
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


def test_duplicate_and_normalization_collision_are_rejected() -> None:
    members = valid_archive_members()
    payload = next(member.payload for member in members if member.name == "./bin/runner")
    duplicate = RawArchiveMember(
        "bin/runner",
        tarfile.REGTYPE,
        0o755,
        payload=payload,
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(build_ustar([*members, duplicate])))
    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(build_ustar([*members, members[2]])))


def test_file_prefix_collision_and_implicit_parent_are_rejected() -> None:
    members = valid_archive_members()
    file_parent = replace_member(
        members,
        "./lib/",
        name="./lib",
        type=tarfile.REGTYPE,
        mode=0o644,
        payload=b"x",
    )
    no_parent = [member for member in members if member.name != "./lib/"]

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(build_ustar(file_parent)))
    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(build_ustar(no_parent)))


@pytest.mark.parametrize(
    ("field_start", "field_width", "value"),
    [
        (108, 8, _octal(1, 8)),
        (116, 8, _octal(1, 8)),
        (136, 12, _octal(1, 12)),
        (265, 32, b"owner" + bytes(27)),
        (297, 32, b"group" + bytes(27)),
        (329, 8, _octal(1, 8)),
        (337, 8, _octal(1, 8)),
    ],
)
def test_raw_owner_time_name_and_device_metadata_must_be_zero_or_empty(
    field_start: int,
    field_width: int,
    value: bytes,
) -> None:
    raw = patch_header_field(
        build_ustar(),
        raw_name=b"./bin/runner",
        start=field_start,
        width=field_width,
        value=value,
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


def test_numeric_fields_reject_noncanonical_but_equivalent_octal() -> None:
    raw = patch_header_field(
        build_ustar(),
        raw_name=b"./bin/runner",
        start=108,
        width=8,
        value=b"       \0",
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


def test_checksum_rejects_noncanonical_but_equivalent_octal() -> None:
    raw = bytearray(build_ustar())
    record = find_raw_tar_record(raw, b"./bin/runner")
    checksum_offset = record.header_offset + 148
    assert raw[checksum_offset] == ord("0")
    raw[checksum_offset] = ord(" ")

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(bytes(raw)))


@pytest.mark.parametrize(
    "mode",
    [0o600, 0o640, 0o775, 0o4755, 0o2755, 0o1755],
)
def test_raw_file_mode_must_match_the_exact_closed_policy(mode: int) -> None:
    raw = patch_header_field(
        build_ustar(),
        raw_name=b"./bin/runner",
        start=100,
        width=8,
        value=_octal(mode, 8),
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


@pytest.mark.parametrize(
    "type_flag",
    [b"x", b"g", b"L", b"K", b"S", b"3", b"4", b"6", b"7"],
)
def test_pax_gnu_extensions_sparse_devices_and_special_types_are_rejected(
    type_flag: bytes,
) -> None:
    raw = _with_type(build_ustar(), b"./lib/z-data", type_flag)

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


def test_legacy_nul_regular_typeflag_is_rejected() -> None:
    raw = _with_type(build_ustar(), b"./bin/runner", b"\0")

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw))


def test_invalid_tar_checksum_is_rejected() -> None:
    raw = bytearray(build_ustar())
    record = find_raw_tar_record(raw, b"./bin/runner")
    raw[record.header_offset + 10] ^= 1

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(bytes(raw)))


@pytest.mark.parametrize("zero_blocks", [0, 1])
def test_tar_requires_at_least_two_end_of_archive_blocks(zero_blocks: int) -> None:
    raw = build_ustar()
    end = first_zero_header_offset(raw) + zero_blocks * 512

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(raw[:end]))


def test_tar_rejects_nonzero_data_after_end_of_archive() -> None:
    raw = bytearray(build_ustar())
    raw[first_zero_header_offset(raw) + 2 * 512] = 1

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(bytes(raw)))


@pytest.mark.parametrize("cut", [1, 4, 8, 32])
def test_truncated_gzip_stream_is_rejected(cut: int) -> None:
    archive = build_valid_archive()

    with pytest.raises(_rejected()):
        _inspect(archive[:-cut])


def test_gzip_crc_corruption_is_rejected() -> None:
    archive = bytearray(build_valid_archive())
    archive[-8] ^= 1

    with pytest.raises(_rejected()):
        _inspect(bytes(archive))


def test_gzip_header_is_exact_flg_zero_and_mtime_zero() -> None:
    flagged = bytearray(build_valid_archive())
    flagged[3] = 0x08
    timestamped = bytearray(build_valid_archive())
    timestamped[4:8] = (1).to_bytes(4, "little")

    with pytest.raises(_rejected()):
        _inspect(bytes(flagged))
    with pytest.raises(_rejected()):
        _inspect(bytes(timestamped))


def test_gzip_rejects_trailing_bytes_and_a_second_member() -> None:
    archive = build_valid_archive()

    with pytest.raises(_rejected()):
        _inspect(archive + b"junk")
    with pytest.raises(_rejected()):
        _inspect(archive + archive)


def test_header_size_and_payload_framing_must_agree() -> None:
    raw = build_ustar()
    record = find_raw_tar_record(raw, b"./lib/z-data")
    enlarged = patch_header_field(
        raw,
        raw_name=b"./lib/z-data",
        start=124,
        width=12,
        value=_octal(record.size + 513, 12),
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(enlarged))


def test_forward_hardlink_and_unmodified_symlink_text_are_accepted() -> None:
    members = replace_member(
        valid_archive_members(),
        "./runner-link",
        linkname="./bin/runner",
    )

    assert _inspect(gzip_ustar(build_ustar(members))) is not None


@pytest.mark.parametrize(
    "target",
    ["././lib/z-data", "../lib/z-data", "./missing", "./runner-link"],
)
def test_hardlink_target_policy_and_graph_are_closed(target: str) -> None:
    members = replace_member(
        valid_archive_members(),
        "./lib/data-copy",
        linkname=target,
    )

    with pytest.raises(_rejected()):
        _inspect(gzip_ustar(build_ustar(members)))


def test_two_pass_reader_rejects_same_size_payload_drift() -> None:
    raw = build_ustar()
    record = find_raw_tar_record(raw, b"./lib/z-data")
    changed = patch_member_payload(
        raw,
        raw_name=b"./lib/z-data",
        payload=b"changed\n"[: record.size],
    )
    first = gzip_ustar(raw, compresslevel=0)
    second = gzip_ustar(changed, compresslevel=0)
    assert len(first) == len(second)
    pass_number = 0

    def drifting_read_at(offset: int, size: int) -> bytes:
        nonlocal pass_number
        if offset == 0:
            pass_number += 1
        selected = first if pass_number <= 1 else second
        return selected[offset : offset + size]

    with pytest.raises(_rejected()):
        inspection._inspect_archive_content(
            drifting_read_at,
            archive_size=len(first),
            expected_archive_sha256=archive_sha256(first),
        )


def test_highly_compressible_raw_tail_is_bounded_by_expansion_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = build_ustar() + bytes(128 * 1024)
    archive = gzip_ustar(raw)
    monkeypatch.setattr(
        inspection,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_COMPRESSION_RATIO_FLOOR_BYTES",
        0,
    )
    monkeypatch.setattr(
        inspection,
        "RUNNER_ACTIVATION_RELEASE_ARCHIVE_MAX_COMPRESSION_RATIO",
        2,
    )

    with pytest.raises(_rejected()):
        _inspect(archive)
