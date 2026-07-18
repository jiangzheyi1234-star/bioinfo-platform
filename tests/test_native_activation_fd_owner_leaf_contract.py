from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from scripts import validate_native_activation_fd_owner_wheel as validator


PROJECT = Path("native/activation_fd_owner")
SOURCE_DIR = PROJECT / "src"
HEADER = SOURCE_DIR / "activation_release_dir_owner_internal.h"
CORE_SOURCE = SOURCE_DIR / "activation_release_dir_owner_core.c"
LEAF_SOURCE = SOURCE_DIR / "activation_release_dir_owner_leaf.c"
MODULE_SOURCE = SOURCE_DIR / "activation_release_dir_owner_module.c"
RUNTIME_ROOTS = (Path("apps"), Path("core"))
RUNTIME_SUFFIXES = {
    ".bat",
    ".js",
    ".json",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
}
IGNORED_RUNTIME_DIRS = {
    ".next",
    ".tmp",
    "__pycache__",
    "node_modules",
    "out",
    "test-results",
}

EXPECTED_PRODUCTION_METHODS = {
    "_close",
    "_fsync_directory",
    "_mkdir_child",
    "_open_child",
    "_require_live",
}
EXPECTED_PROOF_HOOKS = {
    "_test_arm_sigint_for_next_eintr",
    "_test_attempt_snapshot",
    "_test_duplicate_directory",
    "_test_fail_next_capsule_creation",
    "_test_leaf_snapshot",
    "_test_lifecycle_snapshot",
    "_test_note_signal_handler_dispatch",
    "_test_raise_sigint_after_adopt",
    "_test_reset",
    "_test_set_close_report_errno",
    "_test_set_fchmod_errno",
    "_test_set_fsync_errno",
    "_test_set_mkdirat_errno",
    "_test_set_openat2_errnos",
    "_test_set_reproof_errno",
    "_test_snapshot",
}
FORBIDDEN_NAMESPACE_CALLS = {
    "link",
    "linkat",
    "mkdir",
    "mkdirat",
    "remove",
    "rename",
    "renameat",
    "renameat2",
    "rmdir",
    "symlink",
    "symlinkat",
    "unlink",
    "unlinkat",
}


def _between(source: str, start: str, end: str) -> str:
    return source.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]


def _native_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (HEADER, CORE_SOURCE, LEAF_SOURCE, MODULE_SOURCE)
    )


def _runtime_files() -> list[Path]:
    files: list[Path] = []
    for root in RUNTIME_ROOTS:
        for directory, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in dirnames if name not in IGNORED_RUNTIME_DIRS
            ]
            parent = Path(directory)
            files.extend(
                parent / name
                for name in filenames
                if Path(name).suffix.lower() in RUNTIME_SUFFIXES
            )
    return files


def test_leaf_wheel_identity_and_exact_surfaces_are_versioned_together() -> None:
    assert validator.EXPECTED_PRODUCTION_WHEEL.fullmatch(
        "h2ometa_activation_release_dir_owner-0.1.1-cp312-abi3-linux_x86_64.whl"
    )
    assert validator.EXPECTED_PROOF_WHEEL.fullmatch(
        "h2ometa_activation_release_dir_owner_proof-0.1.1-cp312-abi3-linux_x86_64.whl"
    )
    assert not validator.EXPECTED_PRODUCTION_WHEEL.fullmatch(
        "h2ometa_activation_release_dir_owner-0.1.0-cp312-abi3-linux_x86_64.whl"
    )
    assert validator.EXPECTED_PRODUCTION_METHODS == EXPECTED_PRODUCTION_METHODS
    assert validator.EXPECTED_PROOF_HOOKS == EXPECTED_PROOF_HOOKS


def test_leaf_uses_one_direct_fixed_mkdirat_syscall_and_no_name_cleanup() -> None:
    header = HEADER.read_text(encoding="utf-8")
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    source = _native_source()
    mkdir_once = _between(
        leaf,
        "static long h2ometa_mkdirat_once",
        "static int h2ometa_fchmod_private_once",
    )

    assert "#if !defined(SYS_mkdirat)" in leaf
    assert "_Static_assert(SYS_mkdirat == 258" in leaf
    assert "#define H2OMETA_PRIVATE_DIRECTORY_MODE ((mode_t)0700)" in header
    assert len(re.findall(r"\bsyscall\s*\(\s*SYS_mkdirat\b", mkdir_once)) == 1
    assert "H2OMETA_PRIVATE_DIRECTORY_MODE" in mkdir_once
    assert "while" not in mkdir_once
    assert "for (" not in mkdir_once
    zero_issued = mkdir_once.index("*syscall_issued_out = 0")
    injected_return = mkdir_once.index("if (injected_errno != 0)")
    one_issued = mkdir_once.index("*syscall_issued_out = 1")
    syscall = mkdir_once.index("syscall(")
    assert zero_issued < injected_return < one_issued < syscall
    for name in FORBIDDEN_NAMESPACE_CALLS:
        assert re.search(rf"\b{re.escape(name)}\s*\(", source) is None


def test_leaf_mkdir_sequence_preallocates_then_immediately_adopts_and_reproves() -> (
    None
):
    header = HEADER.read_text(encoding="utf-8")
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    mkdir_child = _between(
        leaf,
        "PyObject *h2ometa_mkdir_child",
        "PyObject *h2ometa_fsync_directory",
    )
    tokens = (
        "h2ometa_require_component",
        "H2OMETA_REPROOF_MKDIR_PARENT_PRE",
        "h2ometa_new_owner_capsule",
        "h2ometa_mkdirat_once",
        "h2ometa_openat2_once",
        "child->fd = (int)result",
        "h2ometa_child_baseline_error",
        "h2ometa_fchmod_private_once",
    )
    positions = [mkdir_child.index(token) for token in tokens]

    assert positions == sorted(positions)
    assert mkdir_child.rindex("h2ometa_mkdir_postproof_error") > positions[-1]
    assert mkdir_child.rindex("return child_capsule") > mkdir_child.rindex(
        "h2ometa_mkdir_postproof_error"
    )
    assert mkdir_child.count("h2ometa_mkdirat_once(") == 1
    assert "saved_errno == EINTR && mkdirat_issued ? -1 : 0" in mkdir_child
    assert mkdir_child.count("h2ometa_fchmod_private_once(") == 1
    assert mkdir_child.count("h2ometa_openat2_once(") == 1
    assert "attempt < H2OMETA_OPENAT2_MAX_ATTEMPTS" in mkdir_child
    assert "saved_errno != EAGAIN" in mkdir_child
    assert "attempt + 1 == H2OMETA_OPENAT2_MAX_ATTEMPTS" in mkdir_child
    assert "#define H2OMETA_OPENAT2_MAX_ATTEMPTS 3" in header


def test_leaf_fchmod_is_single_attempt_and_postproof_checks_exact_mode() -> None:
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    fchmod_once = _between(
        leaf,
        "static int h2ometa_fchmod_private_once",
        "static int h2ometa_fsync_once",
    )
    child_postproof = _between(
        leaf,
        "static int h2ometa_child_postproof_error",
        "static int h2ometa_mkdir_postproof_error",
    )

    assert len(re.findall(r"\bfchmod\s*\(", fchmod_once)) == 1
    assert "H2OMETA_PRIVATE_DIRECTORY_MODE" in fchmod_once
    assert "while" not in fchmod_once
    assert "for (" not in fchmod_once
    assert "h2ometa_live_owner_status_error(child, &status)" in child_postproof
    assert "status.st_dev != parent->device" in child_postproof
    assert "status.st_uid != parent->uid" in child_postproof
    assert "(status.st_mode & 07777) != H2OMETA_PRIVATE_DIRECTORY_MODE" in (
        child_postproof
    )


def test_leaf_failure_precedence_reproves_both_identities_before_cleanup() -> None:
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    postproof = _between(
        leaf,
        "static int h2ometa_mkdir_postproof_error",
        "static long h2ometa_mkdirat_once",
    )
    discard = _between(
        leaf,
        "static PyObject *h2ometa_discard_child_with_error",
        "PyObject *h2ometa_mkdir_child",
    )
    mkdir_child = _between(
        leaf,
        "PyObject *h2ometa_mkdir_child",
        "PyObject *h2ometa_fsync_directory",
    )

    parent_call = postproof.index("h2ometa_parent_reproof_error")
    child_call = postproof.index("h2ometa_child_postproof_error")
    parent_precedence = postproof.index("if (parent_error != 0)")
    assert parent_call < child_call < parent_precedence
    assert "return parent_error;" in postproof
    assert "return child_error;" in postproof
    assert discard.index("Py_DecRef(child_capsule)") < discard.index(
        "h2ometa_set_errno_error(error_number)"
    )
    assert (
        mkdir_child.count("postproof_error != 0 ? postproof_error : saved_errno") >= 3
    )


def test_leaf_fsync_is_one_call_with_postproof_error_precedence() -> None:
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    fsync_once = _between(
        leaf,
        "static int h2ometa_fsync_once",
        "static PyObject *h2ometa_discard_child_with_error",
    )
    fsync_directory = leaf.split("PyObject *h2ometa_fsync_directory", maxsplit=1)[1]

    assert len(re.findall(r"\bfsync\s*\(", fsync_once)) == 1
    assert "while" not in fsync_once
    assert "for (" not in fsync_once
    preproof = fsync_directory.index("H2OMETA_REPROOF_FSYNC_PRE")
    syscall = fsync_directory.index("h2ometa_fsync_once(owner)")
    save_errno = fsync_directory.index("saved_errno = errno", syscall)
    postproof = fsync_directory.index("H2OMETA_REPROOF_FSYNC_POST")
    precedence = fsync_directory.index(
        "postproof_error != 0 ? postproof_error : saved_errno"
    )
    assert preproof < syscall < save_errno < postproof < precedence
    assert fsync_directory.count("h2ometa_fsync_once(owner)") == 1


def test_leaf_proof_state_covers_syscalls_reproof_lifecycle_and_boundaries() -> None:
    header = HEADER.read_text(encoding="utf-8")
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    required_fields = {
        "arm_sigint_for_next_eintr",
        "boundary_namespace_state",
        "boundary_owner_state",
        "capsule_creation_successes",
        "destructor_calls",
        "destructor_owner_frees",
        "fd_adoptions",
        "fd_consumptions",
        "fchmod_calls",
        "fchmod_errno",
        "fsync_calls",
        "fsync_errno",
        "handler_dispatch_inside",
        "handler_dispatch_outside",
        "mkdirat_calls",
        "mkdirat_errno",
        "namespace_mutations",
        "owner_allocations",
        "pretransfer_owner_frees",
        "reproof_calls[H2OMETA_REPROOF_PHASE_COUNT]",
        "reproof_errnos[H2OMETA_REPROOF_PHASE_COUNT]",
    }

    for field in required_fields:
        assert field in header
    assert "H2OMETA_REPROOF_PHASE_COUNT = 6" in header
    assert leaf.count("h2ometa_test_state.mkdirat_calls += 1") == 1
    assert leaf.count("h2ometa_test_state.fchmod_calls += 1") == 1
    assert leaf.count("h2ometa_test_state.fsync_calls += 1") == 1
    assert "h2ometa_test_state.reproof_calls[phase] += 1" in leaf


@pytest.mark.parametrize("symbol", ["mkdir", "mkdirat", "unlinkat", "renameat2"])
def test_validator_rejects_libc_namespace_symbols(
    monkeypatch: pytest.MonkeyPatch,
    symbol: str,
) -> None:
    def fake_symbols(_extension: Path, *, defined: bool) -> set[str]:
        if defined:
            return {validator.EXPECTED_PRODUCTION_INIT_SYMBOL}
        return {symbol}

    monkeypatch.setattr(validator, "_nm_symbols", fake_symbols)
    with pytest.raises(RuntimeError, match="forbidden namespace libc symbols"):
        validator._validate_symbols(Path("owner.abi3.so"), testing=False)


def test_runtime_and_release_workflows_have_no_native_owner_consumer() -> None:
    forbidden = (
        "_activation_release_dir_owner",
        "h2ometa-activation-release-dir-owner",
        "h2ometa_activation_release_dir_owner",
    )
    runtime_files = _runtime_files()
    release_workflows = list(Path(".github/workflows").glob("*release*.yml"))

    for path in (*runtime_files, *release_workflows):
        source = path.read_text(encoding="utf-8", errors="ignore")
        assert not any(needle in source for needle in forbidden), path
