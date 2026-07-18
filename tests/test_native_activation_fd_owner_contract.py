from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path


PROJECT = Path("native/activation_fd_owner")
SOURCE_DIR = PROJECT / "src"
INTERNAL_HEADER = SOURCE_DIR / "activation_release_dir_owner_internal.h"
CORE_SOURCE = SOURCE_DIR / "activation_release_dir_owner_core.c"
LEAF_SOURCE = SOURCE_DIR / "activation_release_dir_owner_leaf.c"
MODULE_SOURCE = SOURCE_DIR / "activation_release_dir_owner_module.c"
NATIVE_SOURCES = (INTERNAL_HEADER, CORE_SOURCE, LEAF_SOURCE, MODULE_SOURCE)
SETUP = PROJECT / "setup.py"
PROOF_PROJECT = PROJECT / "proof"
PROOF_SETUP = PROOF_PROJECT / "setup.py"
CONSTRAINTS = PROJECT / "build-constraints.txt"
LINUX_TEST = Path("tests/test_native_activation_fd_owner_linux.py")
BOUNDARY_PROBE = Path("tests/native_activation_fd_owner_boundary_probe.py")
EXPECTED_PRODUCTION_METHODS = [
    "_open_child",
    "_mkdir_child",
    "_fsync_directory",
    "_require_live",
    "_close",
]
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


def _extension_paths(source: str, keyword_name: str) -> tuple[str, ...]:
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Extension"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg == keyword_name:
                value = ast.literal_eval(keyword.value)
                assert isinstance(value, list)
                assert all(isinstance(path, str) for path in value)
                return tuple(value)
    raise AssertionError(f"Extension keyword is missing: {keyword_name}")


def _native_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in NATIVE_SOURCES)


def test_native_owner_is_an_independent_private_build_project() -> None:
    payload = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))

    assert payload["build-system"] == {
        "requires": ["setuptools==83.0.0"],
        "build-backend": "setuptools.build_meta",
    }
    assert payload["project"]["version"] == "0.1.1"
    assert payload["project"]["requires-python"] == ">=3.12"
    assert "Private :: Do Not Upload" in payload["project"]["classifiers"]
    assert payload["tool"]["setuptools"]["packages"] == []

    proof_payload = tomllib.loads(
        (PROOF_PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert proof_payload["project"]["name"] == (
        "h2ometa-activation-release-dir-owner-proof"
    )
    assert proof_payload["project"]["version"] == "0.1.1"
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
    expected_sources = (
        "src/activation_release_dir_owner_core.c",
        "src/activation_release_dir_owner_leaf.c",
        "src/activation_release_dir_owner_module.c",
    )
    expected_proof_sources = tuple(f"../{path}" for path in expected_sources)

    assert 'sys.platform != "linux"' in source
    assert 'platform.machine().lower() != "x86_64"' in source
    assert '"remote_runner._activation_release_dir_owner"' in source
    assert "py_limited_api=True" in source
    assert '"py_limited_api": "cp312"' in source
    assert "H2OMETA_NATIVE_TESTING" not in source
    assert _extension_paths(source, "sources") == expected_sources
    assert _extension_paths(source, "depends") == (
        "src/activation_release_dir_owner_internal.h",
    )

    assert '"remote_runner._activation_release_dir_owner_proof"' in proof_source
    assert 'define_macros=[("H2OMETA_NATIVE_TESTING", "1")]' in proof_source
    assert _extension_paths(proof_source, "sources") == expected_proof_sources
    assert tuple(path.removeprefix("../") for path in expected_proof_sources) == (
        expected_sources
    )
    assert _extension_paths(proof_source, "depends") == (
        "../src/activation_release_dir_owner_internal.h",
    )
    assert '"py_limited_api": "cp312"' in proof_source


def test_native_owner_adopts_descriptor_before_any_python_handoff() -> None:
    header = INTERNAL_HEADER.read_text(encoding="utf-8")
    core = CORE_SOURCE.read_text(encoding="utf-8")
    module = MODULE_SOURCE.read_text(encoding="utf-8")
    source = _native_source()
    open_once = core.split("long h2ometa_openat2_once", maxsplit=1)[1]
    open_child = module.split("static PyObject *h2ometa_open_child", maxsplit=1)[
        1
    ].split("static PyObject *h2ometa_require_live", maxsplit=1)[0]

    assert "#define Py_LIMITED_API 0x030C0000" in header
    assert source.count("Py_LIMITED_API") == 1
    assert "Py_BEGIN_ALLOW_THREADS" not in source
    assert "PyCapsule_New" in core
    assert "SYS_openat2" in source
    assert "H2OMetaDirOwner *child = NULL;" in open_child
    assert "H2OMetaDirOwner *owner = NULL;" in module
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
    module = MODULE_SOURCE.read_text(encoding="utf-8")
    method_table = module.split("static PyMethodDef h2ometa_methods[]", maxsplit=1)[
        1
    ].split("{NULL, NULL, 0, NULL}", maxsplit=1)[0]
    production_methods, proof_methods = method_table.split(
        "#ifdef H2OMETA_NATIVE_TESTING", maxsplit=1
    )
    method_entry = r'\{\s*"([^"]+)",\s*[A-Za-z_][A-Za-z0-9_]*,'
    production_names = re.findall(method_entry, production_methods)
    proof_names = re.findall(method_entry, proof_methods)

    assert production_names == EXPECTED_PRODUCTION_METHODS
    assert set(proof_names) == EXPECTED_PROOF_HOOKS
    assert len(proof_names) == len(EXPECTED_PROOF_HOOKS)
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
    core = CORE_SOURCE.read_text(encoding="utf-8")
    source = _native_source()
    consume = core.split("int h2ometa_consume_owner_fd", maxsplit=1)[1].split(
        "static void h2ometa_capsule_destructor", maxsplit=1
    )[0]

    assert consume.index("owner->fd = -1") < consume.index("h2ometa_close_once(fd)")
    assert "while" not in consume
    assert "retry" not in consume.lower()
    assert "Py_DECREF" not in source
    assert "Py_DecRef" in source


def test_native_owner_child_inherits_parent_authority_uid() -> None:
    source = _native_source()

    assert "status.st_uid != authority_uid" in source
    assert "h2ometa_finish_adoption(child, parent->uid)" in source
    assert "h2ometa_finish_adoption(owner, geteuid())" in source
    assert "activation-release-dir-owner-proof.v1" in source
    assert "PyInit__activation_release_dir_owner_proof" in source


def test_native_owner_split_keeps_one_module_and_hidden_internal_api() -> None:
    header = INTERNAL_HEADER.read_text(encoding="utf-8")
    core = CORE_SOURCE.read_text(encoding="utf-8")
    leaf = LEAF_SOURCE.read_text(encoding="utf-8")
    module = MODULE_SOURCE.read_text(encoding="utf-8")

    assert header.startswith(
        "#ifndef H2OMETA_ACTIVATION_RELEASE_DIR_OWNER_INTERNAL_H\n"
    )
    assert core.startswith('#include "activation_release_dir_owner_internal.h"\n')
    assert leaf.startswith('#include "activation_release_dir_owner_internal.h"\n')
    assert module.startswith('#include "activation_release_dir_owner_internal.h"\n')
    assert "PyMethodDef" not in core
    assert "PyMethodDef" not in leaf
    assert module.count("static PyMethodDef") == 1
    assert "PyMODINIT_FUNC" not in core
    assert "PyMODINIT_FUNC" not in leaf
    assert module.count("PyMODINIT_FUNC") == 1
    assert "static H2OMetaNativeTestState h2ometa_test_state" not in header
    assert "extern H2OMetaNativeTestState h2ometa_test_state" in header
    assert core.count("H2OMetaNativeTestState h2ometa_test_state;") == 1


def test_native_owner_source_and_tests_remain_import_safe_on_windows() -> None:
    expected = {
        "activation_release_dir_owner_core.c",
        "activation_release_dir_owner_internal.h",
        "activation_release_dir_owner_leaf.c",
        "activation_release_dir_owner_module.c",
    }
    actual = {
        path.name
        for path in SOURCE_DIR.iterdir()
        if path.is_file() and path.suffix in {".c", ".h"}
    }

    assert actual == expected
    assert not (SOURCE_DIR / "activation_release_dir_owner.c").exists()
    for path in NATIVE_SOURCES:
        assert len(path.read_text(encoding="utf-8").splitlines()) < 800

    test_source = LINUX_TEST.read_text(encoding="utf-8")
    prefix = test_source.split("@pytest.fixture", maxsplit=1)[0]
    assert "remote_runner._activation_release_dir_owner" not in prefix
    assert _REQUIRED_ENV_LITERAL in test_source

    probe_source = BOUNDARY_PROBE.read_text(encoding="utf-8")
    probe_tree = ast.parse(probe_source)
    acquisition_functions = [
        node
        for node in ast.walk(probe_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "acquire_child"
    ]
    assert "sys.settrace" not in probe_source
    assert "monitoring.events.INSTRUCTION" in probe_source
    assert "monitoring.set_local_events" in probe_source
    assert "instruction_offset == store_offset" in probe_source
    assert len(acquisition_functions) == 2
    for function in acquisition_functions:
        owner_stores = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id == "child_owner"
        ]
        assert len(owner_stores) == 1


_REQUIRED_ENV_LITERAL = "H2OMETA_REQUIRE_NATIVE_ACTIVATION_FD_OWNER_TESTS"
