from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from scripts.validate_native_activation_fd_owner_wheel import (
    EXPECTED_PRODUCTION_EXTENSION,
    EXPECTED_PRODUCTION_MODULE,
    EXPECTED_PRODUCTION_WHEEL,
    EXPECTED_PROOF_EXTENSION,
    EXPECTED_PROOF_MODULE,
    EXPECTED_PROOF_WHEEL,
    _safe_wheel_members,
)


def _write_wheel(path: Path, member: str, payload: bytes) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, payload)


def test_production_and_proof_wheels_have_distinct_identities() -> None:
    production = (
        "h2ometa_activation_release_dir_owner-0.1.0-cp312-abi3-linux_x86_64.whl"
    )
    proof = (
        "h2ometa_activation_release_dir_owner_proof-0.1.0-cp312-abi3-linux_x86_64.whl"
    )

    assert EXPECTED_PRODUCTION_WHEEL.fullmatch(production)
    assert EXPECTED_PROOF_WHEEL.fullmatch(proof)
    assert not EXPECTED_PRODUCTION_WHEEL.fullmatch(proof)
    assert not EXPECTED_PROOF_WHEEL.fullmatch(production)
    assert EXPECTED_PRODUCTION_EXTENSION != EXPECTED_PROOF_EXTENSION
    assert EXPECTED_PRODUCTION_MODULE != EXPECTED_PROOF_MODULE


@pytest.mark.parametrize(
    ("member", "payload"),
    [
        ("remote_runner/libpayload.so.1", b"not-elf"),
        ("remote_runner/PAYLOAD.DLL", b"not-pe"),
        ("remote_runner/payload.bin", b"\x7fELF\x02\x01\x01\x00"),
        ("remote_runner/payload.data", b"\x00asm\x01\x00\x00\x00"),
        ("remote_runner/payload.a", b"!<arch>\n"),
    ],
)
def test_wheel_validator_rejects_extra_native_payloads(
    tmp_path: Path,
    member: str,
    payload: bytes,
) -> None:
    wheel = tmp_path / "payload.whl"
    _write_wheel(wheel, member, payload)

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(RuntimeError, match="extra native payload"):
            _safe_wheel_members(archive)


def test_wheel_validator_rejects_symlinks(tmp_path: Path) -> None:
    wheel = tmp_path / "symlink.whl"
    link = zipfile.ZipInfo("remote_runner/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(link, b"target")

    with zipfile.ZipFile(wheel) as archive:
        with pytest.raises(RuntimeError, match="contains a symlink"):
            _safe_wheel_members(archive)


def test_wheel_validator_allows_only_expected_native_member(tmp_path: Path) -> None:
    wheel = tmp_path / "expected.whl"
    _write_wheel(
        wheel,
        EXPECTED_PRODUCTION_EXTENSION,
        b"\x7fELF\x02\x01\x01\x00",
    )

    with zipfile.ZipFile(wheel) as archive:
        assert _safe_wheel_members(archive) == [EXPECTED_PRODUCTION_EXTENSION]
