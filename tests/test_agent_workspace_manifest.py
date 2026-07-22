from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from apps.remote_runner import agent_workspace_manifest as manifest_module
from apps.remote_runner.agent_workspace_manifest import (
    AgentGenerationBundleManifest,
    AgentWorkspaceManifestError,
    revalidate_agent_generation_bundle,
    scan_agent_generation_bundle,
    seal_agent_generation_bundle,
)
from core.contracts.agent_workspace_proof import agent_workspace_manifest_hash


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    root = tmp_path / "managed-run"
    workflow = root / "workflow"
    scripts = workflow / "scripts"
    scripts.mkdir(parents=True)
    (root / "run-config.json").write_text('{"cores":2}\n', encoding="utf-8")
    (workflow / "Snakefile").write_text(
        'include: "scripts/rules.smk"\n', encoding="utf-8"
    )
    (scripts / "rules.smk").write_text(
        'rule all:\n    input: "results/done.txt"\n', encoding="utf-8"
    )
    yield root
    _restore_writable(root)


def test_scan_builds_canonical_relative_content_manifest(bundle: Path) -> None:
    (bundle / "runtime-output.log").write_text("mutable\n", encoding="utf-8")

    observed = scan_agent_generation_bundle(bundle)

    assert isinstance(observed, AgentGenerationBundleManifest)
    assert [entry.relativePath for entry in observed.entries] == [
        "run-config.json",
        "workflow/Snakefile",
        "workflow/scripts/rules.smk",
    ]
    assert observed.manifest_hash == agent_workspace_manifest_hash(observed.entries)
    payload = observed.runtime_payload()
    assert payload["manifestHash"] == observed.manifest_hash
    assert str(bundle) not in json.dumps(payload)
    assert "runtime-output.log" not in json.dumps(payload)


@pytest.mark.parametrize(
    ("relative_path", "expected_code"),
    [
        ("run-config.json", "AGENT_WORKSPACE_MANIFEST_REQUIRED_PATH_MISSING"),
        ("workflow", "AGENT_WORKSPACE_MANIFEST_REQUIRED_PATH_MISSING"),
        ("workflow/Snakefile", "AGENT_WORKSPACE_MANIFEST_SNAKEFILE_MISSING"),
    ],
)
def test_scan_requires_fixed_generation_bundle_paths(
    bundle: Path,
    relative_path: str,
    expected_code: str,
) -> None:
    target = bundle / Path(*relative_path.split("/"))
    if target.is_dir():
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()
    else:
        target.unlink()

    with pytest.raises(AgentWorkspaceManifestError) as raised:
        scan_agent_generation_bundle(bundle)

    assert raised.value.code == expected_code
    assert str(bundle) not in str(raised.value)


def test_scan_rejects_root_portable_alias(bundle: Path) -> None:
    (bundle / "workflow").rename(bundle / "Workflow")

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_PATH_ALIAS",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_rejects_nonportable_relative_name(bundle: Path) -> None:
    (bundle / "workflow" / "分析.smk").write_text("rule x:\n", encoding="utf-8")

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_PATH_INVALID",
    ):
        scan_agent_generation_bundle(bundle)


@pytest.mark.parametrize(
    ("relative_path", "replacement_kind", "expected_code"),
    [
        (
            "run-config.json",
            "directory",
            "AGENT_WORKSPACE_MANIFEST_RUN_CONFIG_INVALID",
        ),
        ("workflow", "file", "AGENT_WORKSPACE_MANIFEST_WORKFLOW_INVALID"),
    ],
)
def test_scan_requires_regular_fixed_path_types(
    bundle: Path,
    relative_path: str,
    replacement_kind: str,
    expected_code: str,
) -> None:
    target = bundle / relative_path
    if target.is_dir():
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()
    else:
        target.unlink()
    target.mkdir() if replacement_kind == "directory" else target.write_text(
        "not a directory\n", encoding="utf-8"
    )

    with pytest.raises(AgentWorkspaceManifestError, match=expected_code):
        scan_agent_generation_bundle(bundle)


def test_scan_rejects_casefold_aliases_when_filesystem_allows_them(
    bundle: Path,
) -> None:
    first = bundle / "workflow" / "Case.smk"
    second = bundle / "workflow" / "case.smk"
    first.write_text("first\n", encoding="utf-8")
    second.write_text("second\n", encoding="utf-8")
    if not first.exists() or not second.exists() or first.samefile(second):
        pytest.skip("filesystem is case-insensitive")

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_PATH_ALIAS",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_rejects_hardlinked_bundle_file(bundle: Path) -> None:
    alias = bundle / "hardlink-copy"
    try:
        os.link(bundle / "run-config.json", alias)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc.__class__.__name__}")

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_HARDLINK",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_rejects_symlinked_bundle_entry_when_supported(
    bundle: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "outside.smk"
    source.write_text("rule outside:\n", encoding="utf-8")
    link = bundle / "workflow" / "linked.smk"
    try:
        link.symlink_to(source)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc.__class__.__name__}")

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_REPARSE_POINT",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_rejects_empty_directory_not_representable_by_file_manifest(
    bundle: Path,
) -> None:
    (bundle / "workflow" / "empty").mkdir()

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_EMPTY_DIRECTORY",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_detects_replacement_after_first_enumeration(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = bundle / "workflow" / "Snakefile"
    replacement = bundle / "workflow" / "replacement.tmp"
    original = target.read_bytes()
    replaced = False

    def replace(stage: str, _relative_path: str) -> None:
        nonlocal replaced
        if stage == "after_first_enumeration" and not replaced:
            replacement.write_bytes(original)
            os.replace(replacement, target)
            replaced = True

    monkeypatch.setattr(manifest_module, "_scan_test_hook", replace)

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_detects_write_before_stable_read(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = bundle / "workflow" / "Snakefile"
    changed = False

    def mutate(stage: str, relative_path: str) -> None:
        nonlocal changed
        if stage == "before_file_read" and relative_path.endswith("Snakefile"):
            target.write_text("rule changed:\n", encoding="utf-8")
            changed = True

    monkeypatch.setattr(manifest_module, "_scan_test_hook", mutate)

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_FILE_UNSTABLE",
    ):
        scan_agent_generation_bundle(bundle)
    assert changed is True


@pytest.mark.parametrize("change", ["add", "delete"])
def test_scan_double_enumeration_detects_directory_drift(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    changed = False

    def mutate(stage: str, _relative_path: str) -> None:
        nonlocal changed
        if stage != "before_second_enumeration" or changed:
            return
        if change == "add":
            (bundle / "workflow" / "late.smk").write_text(
                "rule late:\n", encoding="utf-8"
            )
        else:
            (bundle / "workflow" / "scripts" / "rules.smk").unlink()
        changed = True

    monkeypatch.setattr(manifest_module, "_scan_test_hook", mutate)

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_DIRECTORY_UNSTABLE",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_enforces_per_file_and_total_byte_limits(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "MAX_AGENT_GENERATION_BUNDLE_FILE_BYTES", 8)
    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_FILE_BYTES_EXCEEDED",
    ):
        scan_agent_generation_bundle(bundle)

    monkeypatch.setattr(
        manifest_module, "MAX_AGENT_GENERATION_BUNDLE_FILE_BYTES", 1024 * 1024
    )
    monkeypatch.setattr(manifest_module, "MAX_AGENT_GENERATION_BUNDLE_TOTAL_BYTES", 16)
    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_TOTAL_BYTES_EXCEEDED",
    ):
        scan_agent_generation_bundle(bundle)


def test_scan_enforces_file_and_directory_count_limits(
    bundle: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "MAX_AGENT_GENERATION_BUNDLE_FILES", 2)
    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_FILE_LIMIT_EXCEEDED",
    ):
        scan_agent_generation_bundle(bundle)

    monkeypatch.setattr(manifest_module, "MAX_AGENT_GENERATION_BUNDLE_FILES", 50_000)
    monkeypatch.setattr(manifest_module, "MAX_AGENT_GENERATION_BUNDLE_DIRECTORIES", 1)
    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_DIRECTORY_LIMIT_EXCEEDED",
    ):
        scan_agent_generation_bundle(bundle)


def test_seal_clears_all_bundle_file_and_workflow_directory_write_bits(
    bundle: Path,
) -> None:
    before = scan_agent_generation_bundle(bundle)

    sealed = seal_agent_generation_bundle(bundle)

    assert sealed == before
    governed_paths = [
        bundle / "run-config.json",
        bundle / "workflow",
        bundle / "workflow" / "Snakefile",
        bundle / "workflow" / "scripts",
        bundle / "workflow" / "scripts" / "rules.smk",
    ]
    assert all(path.stat().st_mode & 0o222 == 0 for path in governed_paths)
    assert scan_agent_generation_bundle(bundle, require_sealed=True) == sealed
    assert revalidate_agent_generation_bundle(bundle, sealed) == sealed


def test_revalidate_is_read_only_and_rejects_extra_file(bundle: Path) -> None:
    sealed = seal_agent_generation_bundle(bundle)
    workflow = bundle / "workflow"
    _make_writable(workflow, directory=True)
    extra = workflow / "extra.smk"
    extra.write_text("rule extra:\n", encoding="utf-8")
    extra.chmod(stat.S_IMODE(extra.stat().st_mode) & ~0o222)
    workflow.chmod(stat.S_IMODE(workflow.stat().st_mode) & ~0o222)

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_MISMATCH",
    ):
        revalidate_agent_generation_bundle(bundle, sealed)

    assert extra.exists()


def test_revalidate_rejects_replaced_content(bundle: Path) -> None:
    sealed = seal_agent_generation_bundle(bundle)
    workflow = bundle / "workflow"
    target = workflow / "Snakefile"
    _make_writable(workflow, directory=True)
    _make_writable(target)
    replacement = workflow / "replacement.tmp"
    replacement.write_text("rule replaced:\n", encoding="utf-8")
    replacement.chmod(stat.S_IMODE(replacement.stat().st_mode) & ~0o222)
    os.replace(replacement, target)
    workflow.chmod(stat.S_IMODE(workflow.stat().st_mode) & ~0o222)

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_MISMATCH",
    ):
        revalidate_agent_generation_bundle(bundle, sealed)


def test_revalidate_rejects_unsealed_bundle_without_mutating_it(bundle: Path) -> None:
    observed = scan_agent_generation_bundle(bundle)
    before_mode = (bundle / "workflow" / "Snakefile").stat().st_mode

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_WRITE_BIT_PRESENT",
    ):
        revalidate_agent_generation_bundle(bundle, observed)

    assert (bundle / "workflow" / "Snakefile").stat().st_mode == before_mode


def test_revalidate_rejects_internally_invalid_expected_hash(bundle: Path) -> None:
    sealed = seal_agent_generation_bundle(bundle)
    invalid = AgentGenerationBundleManifest(sealed.entries, "f" * 64)

    with pytest.raises(
        AgentWorkspaceManifestError,
        match="AGENT_WORKSPACE_MANIFEST_EXPECTED_HASH_MISMATCH",
    ):
        revalidate_agent_generation_bundle(bundle, invalid)


def _restore_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        _make_writable(path, directory=path.is_dir())
    _make_writable(root, directory=True)


def _make_writable(path: Path, *, directory: bool = False) -> None:
    if not path.exists() and not path.is_symlink():
        return
    try:
        mode = stat.S_IMODE(path.lstat().st_mode)
        path.chmod(mode | stat.S_IWUSR | (stat.S_IXUSR if directory else 0))
    except OSError:
        pass
