from __future__ import annotations

import re
import tomllib
from pathlib import Path


PROJECT = Path("native/activation_fd_owner")
C_SOURCE = PROJECT / "src" / "activation_release_dir_owner.c"
SETUP = PROJECT / "setup.py"
PROOF_PROJECT = PROJECT / "proof"
PROOF_SETUP = PROOF_PROJECT / "setup.py"
CONSTRAINTS = PROJECT / "build-constraints.txt"
LINUX_TEST = Path("tests/test_native_activation_fd_owner_linux.py")


def test_native_owner_is_an_independent_private_build_project() -> None:
    payload = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))

    assert payload["build-system"] == {
        "requires": ["setuptools==83.0.0"],
        "build-backend": "setuptools.build_meta",
    }
    assert payload["project"]["requires-python"] == ">=3.12"
    assert "Private :: Do Not Upload" in payload["project"]["classifiers"]
    assert payload["tool"]["setuptools"]["packages"] == []

    proof_payload = tomllib.loads(
        (PROOF_PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert proof_payload["project"]["name"] == (
        "h2ometa-activation-release-dir-owner-proof"
    )
    assert "Private :: Do Not Upload" in proof_payload["project"]["classifiers"]
    assert proof_payload["tool"]["setuptools"]["packages"] == []


def test_native_owner_build_backend_is_hash_constrained() -> None:
    source = CONSTRAINTS.read_text(encoding="utf-8")

    assert source.count("setuptools==83.0.0") == 1
    hashes = re.findall(r"sha256:([0-9a-f]{64})", source)
    assert hashes == [
        "29b23c360f22f414dc7336bb39178cc7bcbf6021ed2733cde173f09dba19abb3",
        "025bccbbf0fa05b6192bc64ae1e7b16e001fd6d6d4d5de03c97b1c1ade523bef",
    ]


def test_native_owner_build_is_linux_x86_64_abi3_only() -> None:
    source = SETUP.read_text(encoding="utf-8")
    proof_source = PROOF_SETUP.read_text(encoding="utf-8")

    assert 'sys.platform != "linux"' in source
    assert 'platform.machine().lower() != "x86_64"' in source
    assert '"remote_runner._activation_release_dir_owner"' in source
    assert "py_limited_api=True" in source
    assert '"py_limited_api": "cp312"' in source
    assert "H2OMETA_NATIVE_TESTING" not in source
    assert '"remote_runner._activation_release_dir_owner_proof"' in proof_source
    assert 'define_macros=[("H2OMETA_NATIVE_TESTING", "1")]' in proof_source
    assert 'sources=["../src/activation_release_dir_owner.c"]' in proof_source
    assert '"py_limited_api": "cp312"' in proof_source


def test_native_owner_adopts_descriptor_before_any_python_handoff() -> None:
    source = C_SOURCE.read_text(encoding="utf-8")
    open_once = source.split("static long h2ometa_openat2_once", maxsplit=1)[1].split(
        "static PyObject *h2ometa_open_child", maxsplit=1
    )[0]
    open_child = source.split("static PyObject *h2ometa_open_child", maxsplit=1)[
        1
    ].split("static PyObject *h2ometa_require_live", maxsplit=1)[0]

    assert "#define Py_LIMITED_API 0x030C0000" in source
    assert source.count("Py_LIMITED_API") == 1
    assert "Py_BEGIN_ALLOW_THREADS" not in source
    assert "PyCapsule_New" in source
    assert "SYS_openat2" in source
    assert open_child.index("h2ometa_new_owner_capsule") < open_child.index(
        "h2ometa_openat2_once"
    )
    assert open_once.count("syscall(SYS_openat2") == 1
    assert open_once.index("h2ometa_test_record_attempt") < open_once.index(
        "syscall(SYS_openat2"
    )
    assert "parent->fd" in open_once
    assert open_child.index("h2ometa_openat2_once") < open_child.index(
        "child->fd = (int)result"
    )
    assert open_child.index("child->fd = (int)result") < open_child.index(
        "h2ometa_finish_adoption"
    )


def test_native_owner_production_surface_has_no_raw_fd_or_callback_api() -> None:
    source = C_SOURCE.read_text(encoding="utf-8")
    production_methods = source.split(
        "static PyMethodDef h2ometa_methods[]", maxsplit=1
    )[1].split("#ifdef H2OMETA_NATIVE_TESTING", maxsplit=1)[0]

    assert '"_open_child"' in production_methods
    assert '"_require_live"' in production_methods
    assert '"_close"' in production_methods
    for forbidden in (
        '"fileno"',
        '"take_fd"',
        '"borrow_fd"',
        '"replay"',
        '"callback"',
        "PyCapsule_Import",
        "PyObject_Call",
    ):
        assert forbidden not in production_methods


def test_native_owner_close_consumes_before_single_close_call() -> None:
    source = C_SOURCE.read_text(encoding="utf-8")
    consume = source.split("static int h2ometa_consume_owner_fd", maxsplit=1)[1].split(
        "static void h2ometa_capsule_destructor", maxsplit=1
    )[0]

    assert consume.index("owner->fd = -1") < consume.index("h2ometa_close_once(fd)")
    assert "while" not in consume
    assert "retry" not in consume.lower()
    assert "Py_DECREF" not in source
    assert "Py_DecRef" in source


def test_native_owner_child_inherits_parent_authority_uid() -> None:
    source = C_SOURCE.read_text(encoding="utf-8")

    assert "status.st_uid != authority_uid" in source
    assert "h2ometa_finish_adoption(child, parent->uid)" in source
    assert "h2ometa_finish_adoption(owner, geteuid())" in source
    assert "activation-release-dir-owner-proof.v1" in source
    assert "PyInit__activation_release_dir_owner_proof" in source


def test_native_owner_source_and_tests_remain_import_safe_on_windows() -> None:
    assert len(C_SOURCE.read_text(encoding="utf-8").splitlines()) < 800
    test_source = LINUX_TEST.read_text(encoding="utf-8")
    prefix = test_source.split("@pytest.fixture", maxsplit=1)[0]
    assert "remote_runner._activation_release_dir_owner" not in prefix
    assert _REQUIRED_ENV_LITERAL in test_source


_REQUIRED_ENV_LITERAL = "H2OMETA_REQUIRE_NATIVE_ACTIVATION_FD_OWNER_TESTS"
