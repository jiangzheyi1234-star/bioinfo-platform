#!/usr/bin/env python3
"""Validate a quarantined activation directory-owner proof wheel."""

from __future__ import annotations

import argparse
import re
import stat
import struct
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_PRODUCTION_WHEEL = re.compile(
    r"^h2ometa_activation_release_dir_owner-0[.]1[.]0-"
    r"cp312-abi3-linux_x86_64[.]whl$"
)
EXPECTED_PROOF_WHEEL = re.compile(
    r"^h2ometa_activation_release_dir_owner_proof-0[.]1[.]0-"
    r"cp312-abi3-linux_x86_64[.]whl$"
)
EXPECTED_PRODUCTION_EXTENSION = "remote_runner/_activation_release_dir_owner.abi3.so"
EXPECTED_PROOF_EXTENSION = "remote_runner/_activation_release_dir_owner_proof.abi3.so"
EXPECTED_PRODUCTION_INIT_SYMBOL = "PyInit__activation_release_dir_owner"
EXPECTED_PROOF_INIT_SYMBOL = "PyInit__activation_release_dir_owner_proof"
EXPECTED_PRODUCTION_MODULE = "remote_runner._activation_release_dir_owner"
EXPECTED_PROOF_MODULE = "remote_runner._activation_release_dir_owner_proof"
EXPECTED_TAG = "Tag: cp312-abi3-linux_x86_64"
ALLOWED_UNDERSCORE_STABLE_ABI_SYMBOLS = frozenset(
    {
        "_PyArg_ParseTuple_SizeT",
        "_Py_BuildValue_SizeT",
        "_Py_NoneStruct",
    }
)
FORBIDDEN_PATH_FALLBACK_SYMBOLS = frozenset(
    {
        "__lxstat",
        "__open64_2",
        "__open_2",
        "__openat64_2",
        "__openat_2",
        "__xstat",
        "canonicalize_file_name",
        "chdir",
        "faccessat",
        "fchdir",
        "fopen",
        "fopen64",
        "fstatat",
        "glob",
        "lstat",
        "open",
        "open64",
        "openat",
        "openat64",
        "opendir",
        "readlink",
        "readlinkat",
        "realpath",
        "scandir",
        "stat",
    }
)
NATIVE_SUFFIXES = frozenset(
    {".a", ".dll", ".dylib", ".exe", ".lib", ".o", ".obj", ".pyd", ".so", ".wasm"}
)
NATIVE_MAGICS = (
    b"\x7fELF",
    b"MZ",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"!<arch>\n",
    b"\x00asm",
)


def _run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def _safe_wheel_members(
    archive: zipfile.ZipFile,
    *,
    expected_extension: str = EXPECTED_PRODUCTION_EXTENSION,
) -> list[str]:
    names: list[str] = []
    for info in archive.infolist():
        name = info.filename
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            raise RuntimeError(f"native owner wheel has unsafe member: {name}")
        names.append(name)
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(unix_mode):
            raise RuntimeError(f"native owner wheel contains a symlink: {name}")
        if info.is_dir() or name == expected_extension:
            continue
        suffixes = {suffix.lower() for suffix in path.suffixes}
        with archive.open(info) as handle:
            prefix = handle.read(8)
        if suffixes & NATIVE_SUFFIXES or any(
            prefix.startswith(magic) for magic in NATIVE_MAGICS
        ):
            raise RuntimeError(
                f"native owner wheel contains an extra native payload: {name}"
            )
    return names


def _extract_and_validate_wheel(wheel: Path, site: Path, *, testing: bool) -> Path:
    expected_wheel = EXPECTED_PROOF_WHEEL if testing else EXPECTED_PRODUCTION_WHEEL
    expected_extension = (
        EXPECTED_PROOF_EXTENSION if testing else EXPECTED_PRODUCTION_EXTENSION
    )
    if not expected_wheel.fullmatch(wheel.name):
        raise RuntimeError(f"native owner wheel filename is invalid: {wheel.name}")
    site.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(wheel) as archive:
        names = _safe_wheel_members(
            archive,
            expected_extension=expected_extension,
        )
        extensions = [name for name in names if name.endswith((".so", ".pyd"))]
        if extensions != [expected_extension]:
            raise RuntimeError(
                f"native owner wheel extension set is invalid: {extensions}"
            )
        if any(".cpython-" in name for name in names):
            raise RuntimeError(
                "native owner wheel contains a versioned CPython extension"
            )
        wheel_metadata = [name for name in names if name.endswith(".dist-info/WHEEL")]
        if len(wheel_metadata) != 1:
            raise RuntimeError("native owner wheel metadata is invalid")
        metadata = archive.read(wheel_metadata[0]).decode("utf-8")
        tags = [line for line in metadata.splitlines() if line.startswith("Tag: ")]
        if tags != [EXPECTED_TAG]:
            raise RuntimeError(f"native owner wheel tag is invalid: {tags}")
        builds = [line for line in metadata.splitlines() if line.startswith("Build: ")]
        if builds:
            raise RuntimeError(
                f"native owner wheel build identity is invalid: {builds}"
            )
        archive.extractall(site)
    return site / PurePosixPath(expected_extension)


def _validate_elf(extension: Path) -> None:
    with extension.open("rb") as handle:
        header = handle.read(64)
    if len(header) < 64 or header[:4] != b"\x7fELF":
        raise RuntimeError("native owner extension is not ELF")
    if header[4:6] != b"\x02\x01":
        raise RuntimeError("native owner extension is not little-endian ELF64")
    elf_type, machine = struct.unpack_from("<HH", header, 16)
    if elf_type != 3 or machine != 62:
        raise RuntimeError(
            f"native owner ELF identity is invalid: type={elf_type} machine={machine}"
        )

    dynamic = _run(["readelf", "--dynamic", "--wide", str(extension)])
    program_headers = _run(["readelf", "--program-headers", "--wide", str(extension)])
    if "TEXTREL" in dynamic or "BIND_NOW" not in dynamic:
        raise RuntimeError("native owner ELF hardening flags are invalid")
    if "GNU_RELRO" not in program_headers:
        raise RuntimeError("native owner ELF is missing GNU_RELRO")


def _nm_symbols(extension: Path, *, defined: bool) -> set[str]:
    mode = "--defined-only" if defined else "--undefined-only"
    output = _run(["nm", "-D", mode, "--format=posix", str(extension)])
    return {
        line.split()[0].split("@", maxsplit=1)[0]
        for line in output.splitlines()
        if line.split()
    }


def _validate_symbols(extension: Path, *, testing: bool) -> None:
    expected_init_symbol = (
        EXPECTED_PROOF_INIT_SYMBOL if testing else EXPECTED_PRODUCTION_INIT_SYMBOL
    )
    defined = _nm_symbols(extension, defined=True)
    if defined != {expected_init_symbol}:
        raise RuntimeError(f"native owner exported symbols are invalid: {defined}")
    undefined = _nm_symbols(extension, defined=False)
    private_python = {
        symbol
        for symbol in undefined
        if symbol.startswith("_Py")
        and symbol not in ALLOWED_UNDERSCORE_STABLE_ABI_SYMBOLS
    }
    if private_python:
        raise RuntimeError(
            f"native owner references private CPython symbols: {private_python}"
        )
    path_fallbacks = undefined & FORBIDDEN_PATH_FALLBACK_SYMBOLS
    if path_fallbacks:
        raise RuntimeError(
            f"native owner references path fallback symbols: {path_fallbacks}"
        )


def _validate_import(python: str, site: Path, *, testing: bool) -> None:
    expected_testing = "True" if testing else "False"
    module_name = EXPECTED_PROOF_MODULE if testing else EXPECTED_PRODUCTION_MODULE
    script = f"""
import importlib
import sys
sys.path.insert(0, sys.argv[1])
module = importlib.import_module({module_name!r})
required = {{'_open_child', '_require_live', '_close'}}
assert required <= set(dir(module))
hooks = {{name for name in dir(module) if name.startswith('_test_')}}
assert bool(hooks) is {expected_testing}, hooks
try:
    module._close(object())
except TypeError as exc:
    assert str(exc) == 'invalid directory capability'
else:
    raise AssertionError('invalid capability was accepted')
"""
    subprocess.run(
        [python, "-I", "-c", script, str(site)],
        check=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--python", action="append", required=True)
    parser.add_argument("--testing", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    extension = _extract_and_validate_wheel(
        args.wheel,
        args.site,
        testing=args.testing,
    )
    _validate_elf(extension)
    _validate_symbols(extension, testing=args.testing)
    for python in args.python:
        _validate_import(python, args.site, testing=args.testing)
    print(
        "NATIVE_ACTIVATION_FD_OWNER_WHEEL_OK "
        f"wheel={args.wheel.name} testing={args.testing}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
