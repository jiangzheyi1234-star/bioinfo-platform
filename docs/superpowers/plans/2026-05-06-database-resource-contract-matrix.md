# Database Resource Contract Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the database workflow resource tests around a small, explicit contract matrix so new database surfaces stop relying on ad hoc case-by-case assertions and source-string contract tests.

**Architecture:** Center the next round on one narrow seam: `build_workflow_resource_config()` and the database records it consumes. Promote a shared case builder in `tests/helpers/reference_database.py`, then make `tests/test_workflow_resource_binding.py` consume that matrix for `directory`, `prefix`, `primary_with_sidecars`, and `composite` path kinds. Keep this round focused on test architecture, not production refactors.

**Tech Stack:** Python, pytest, PowerShell, `uv`, remote runner database/resource helpers

---

## File Structure

- Modify: `tests/helpers/reference_database.py`
  Responsibility: shared database contract fixtures, path materialization, shared contract assertions.
- Modify: `tests/test_workflow_resource_binding.py`
  Responsibility: workflow resource binding contract coverage for run config and emitted resource records.
- Read only: `apps/remote_runner/workflow_resources.py`
  Responsibility: implementation seam the tests are locking down.
- Read only: `apps/remote_runner/databases.py`
  Responsibility: current database record shape and path resolution behavior.

### Task 1: Define The Shared Contract Matrix

**Files:**
- Modify: `tests/helpers/reference_database.py`
- Test: `tests/test_workflow_resource_binding.py`

- [ ] **Step 1: Add a typed contract-case builder to the shared helper**

Add a small shared structure near the existing helper assertions so tests can describe cases by contract axes instead of re-creating each scenario inline.

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatabaseContractCase:
    case_id: str
    template_id: str
    database_id: str
    database_name: str
    resource_key: str
    config_key: str
    database_path: str
    entry_path: object
    expected_path_mode: str
    expected_input_kind: str
    expected_resolved: object
    expected_config_value: object
    metadata: dict[str, Any] | None = None
```

- [ ] **Step 2: Add a helper that materializes the minimum supported matrix**

Create one helper that returns the first four cases only:
- `directory`
- `prefix`
- `primary_with_sidecars`
- `composite`

The helper should produce the database payload plus expected outputs, not just file paths.

```python
def iter_workflow_resource_contract_cases(tmp_path: Path) -> list[DatabaseContractCase]:
    blast_dir = make_blast_prefix_database(tmp_path / "blast")
    bwa_fasta = make_bwa_reference(tmp_path / "bwa")
    kraken_dir = make_kraken2_database(tmp_path / "kraken2")
    nucleotide = tmp_path / "humann" / "chocophlan"
    protein = tmp_path / "humann" / "uniref"
    mapping = tmp_path / "humann" / "utility_mapping"
    for path in (nucleotide, protein, mapping):
        path.mkdir(parents=True, exist_ok=True)
    (nucleotide / "genome.ffn.gz").write_text("nucleotide", encoding="utf-8")
    (protein / "uniref90.dmnd").write_text("protein", encoding="utf-8")
    (mapping / "map_uniref90_name.txt.gz").write_text("mapping", encoding="utf-8")
    return [
        DatabaseContractCase(
            case_id="prefix-blast",
            template_id="blast",
            database_id="db_ncbi_nt",
            database_name="NCBI nt",
            resource_key="blast_nt_db",
            config_key="blast_nt_db",
            database_path=str(blast_dir),
            entry_path=str(blast_dir / "nt"),
            expected_path_mode="prefix",
            expected_input_kind="single",
            expected_resolved={"default": str(blast_dir / "nt")},
            expected_config_value=str(blast_dir / "nt"),
        ),
        DatabaseContractCase(
            case_id="directory-kraken2",
            template_id="kraken2",
            database_id="db_kraken2",
            database_name="Kraken2",
            resource_key="kraken_db",
            config_key="kraken_db",
            database_path=str(kraken_dir),
            entry_path=str(kraken_dir),
            expected_path_mode="directory",
            expected_input_kind="single",
            expected_resolved={"default": str(kraken_dir)},
            expected_config_value=str(kraken_dir),
        ),
        DatabaseContractCase(
            case_id="primary-with-sidecars-bwa",
            template_id="bwa",
            database_id="db_bwa",
            database_name="BWA hg38",
            resource_key="bwa_db",
            config_key="bwa_db",
            database_path=str(bwa_fasta),
            entry_path=str(bwa_fasta),
            expected_path_mode="primary_with_sidecars",
            expected_input_kind="single",
            expected_resolved={"default": str(bwa_fasta)},
            expected_config_value=str(bwa_fasta),
        ),
        DatabaseContractCase(
            case_id="composite-humann",
            template_id="humann",
            database_id="db_humann",
            database_name="HUMAnN",
            resource_key="humann_db",
            config_key="humann",
            database_path=str(nucleotide.parent),
            entry_path={
                "nucleotide": str(nucleotide),
                "protein": str(protein),
                "utility_mapping": str(mapping),
            },
            expected_path_mode="composite",
            expected_input_kind="multi",
            expected_resolved={
                "nucleotide": str(nucleotide),
                "protein": str(protein),
                "utility_mapping": str(mapping),
            },
            expected_config_value={
                "nucleotide": str(nucleotide),
                "protein": str(protein),
                "utility_mapping": str(mapping),
            },
            metadata={
                "input": {
                    "kind": "multi",
                    "fields": {
                        "nucleotide": str(nucleotide),
                        "protein": str(protein),
                        "utility_mapping": str(mapping),
                    },
                }
            },
        ),
    ]
```

- [ ] **Step 3: Extend the existing shared assertion instead of duplicating local ones**

Upgrade `assert_resolution_contract` so it can validate both the top-level record and the mirrored `metadata` payload, then reuse it everywhere.

```python
def assert_resolution_contract(
    record: Mapping[str, object],
    *,
    input_path: Path | str,
    entry_path: Path | str,
    path_mode: str,
    resolved_path: object | None = None,
    input_kind: str | None = None,
) -> None:
    expected_input = str(input_path)
    expected_entry = entry_path if isinstance(entry_path, dict) else str(entry_path)
    metadata = record["metadata"]
    assert isinstance(metadata, Mapping)
    assert record["inputPath"] == expected_input
    assert record["entryPath"] == expected_entry
    assert record["pathMode"] == path_mode
    assert metadata["inputPath"] == expected_input
    assert metadata["entryPath"] == expected_entry
    assert metadata["pathMode"] == path_mode
    if input_kind is not None:
        assert record["input"]["kind"] == input_kind
    if resolved_path is not None:
        assert record["resolvedPath"] == resolved_path
        assert metadata["resolvedPath"] == resolved_path
```

- [ ] **Step 4: Verify the helper file still imports and the old helper API still works**

Run:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
$env:UV_PYTHON='python'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run python -m pytest tests/test_workflow_resource_binding.py -q
```

Expected:
- The file imports successfully.
- Tests may still fail because the matrix is not wired in yet.
- No new import or syntax errors from the helper refactor.

### Task 2: Rebuild Workflow Resource Binding Tests Around The Matrix

**Files:**
- Modify: `tests/test_workflow_resource_binding.py`
- Read: `apps/remote_runner/workflow_resources.py`
- Test: `tests/test_workflow_resource_binding.py`

- [ ] **Step 1: Remove the local duplicate contract assertion**

Delete the local `_assert_resource_resolution_contract` helper from `tests/test_workflow_resource_binding.py` and import the shared assertion from `tests/helpers/reference_database.py`.

```python
from tests.helpers.reference_database import (
    assert_resolution_contract,
    iter_workflow_resource_contract_cases,
    make_configured_remote_runner,
    patch_tool_probe_success,
)
```

- [ ] **Step 2: Replace the one-off happy-path tests with one parameterized contract test**

Collapse the separate resource-binding happy-path tests into a parameterized test over the shared case list.

```python
def test_workflow_resource_binding_contract_matrix(tmp_path: Path, monkeypatch) -> None:
    patch_tool_probe_success(monkeypatch)
    cfg = make_configured_remote_runner(tmp_path, token="workflow-resource-token")

    for case in iter_workflow_resource_contract_cases(tmp_path):
        add_reference_database(
            cfg,
            {
                "id": case.database_id,
                "name": case.database_name,
                "templateId": case.template_id,
                "path": case.database_path,
                **({"metadata": case.metadata} if case.metadata else {}),
            },
        )

        result = build_workflow_resource_config(
            cfg,
            workflow_resource_spec={
                case.resource_key: {
                    "required": True,
                    "acceptedTemplates": [case.template_id],
                    "configKey": case.config_key,
                }
            },
            bindings={case.resource_key: case.database_id},
        )

        assert result["config"][case.config_key] == case.expected_config_value
        resource = result["resources"][case.resource_key]
        assert resource["resolved"] == case.expected_resolved
        assert_resolution_contract(
            resource,
            input_path=case.database_path,
            entry_path=case.entry_path,
            path_mode=case.expected_path_mode,
            input_kind=case.expected_input_kind,
            resolved_path=case.expected_resolved,
        )
```

- [ ] **Step 3: Keep one explicit negative test for template mismatch**

Retain a single focused negative case for `WORKFLOW_RESOURCE_TEMPLATE_UNSUPPORTED`. Do not fold the rejection path into the happy-path matrix.

```python
def test_workflow_resource_binding_rejects_wrong_template(tmp_path: Path, monkeypatch) -> None:
    patch_tool_probe_success(monkeypatch)
    cfg = make_configured_remote_runner(tmp_path, token="workflow-resource-token")
    db_dir = make_kraken2_database(tmp_path / "kraken2")
    add_reference_database(
        cfg,
        {
            "id": "db_kraken2",
            "name": "Kraken2",
            "templateId": "kraken2",
            "path": str(db_dir),
        },
    )
    with pytest.raises(ValueError, match="WORKFLOW_RESOURCE_TEMPLATE_UNSUPPORTED"):
        build_workflow_resource_config(
            cfg,
            workflow_resource_spec={
                "blast_nt_db": {
                    "required": True,
                    "acceptedTemplates": ["blast"],
                    "configKey": "blast_nt_db",
                }
            },
            bindings={"blast_nt_db": "db_kraken2"},
        )
```

- [ ] **Step 4: Run the focused verification for this file**

Run:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
$env:UV_PYTHON='python'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run python -m pytest tests/test_workflow_resource_binding.py -q
```

Expected:
- All workflow resource binding tests pass.
- Case ids make failures point to a contract axis instead of a random scenario name.

### Task 3: Add One Reuse Point Outside Workflow Resource Binding

**Files:**
- Modify: `tests/test_reference_database_registry_templates.py`
- Modify: `tests/helpers/reference_database.py`
- Test: `tests/test_reference_database_registry_templates.py`

- [ ] **Step 1: Pick exactly one downstream consumer of the new helper**

Use `tests/test_reference_database_registry_templates.py` as the first downstream reuse point because it already exercises template shape coverage and is close enough to the helper layer to benefit from shared path materialization.

- [ ] **Step 2: Replace one duplicated setup block with the shared case/materialization helper**

Do not broaden scope. Reuse the new helper in one place only to prove the abstraction works outside `test_workflow_resource_binding.py`.

```python
case = next(
    case
    for case in iter_workflow_resource_contract_cases(tmp_path)
    if case.case_id == "prefix-blast"
)
```

- [ ] **Step 3: Run only the directly affected tests**

Run:

```powershell
$env:UV_CACHE_DIR='E:\code\bio_ui\.uv-cache-local'
$env:UV_PYTHON='python'
$env:UV_PYTHON_INSTALL_DIR='E:\code\bio_ui\.codex-uv-python'
uv run python -m pytest tests/test_workflow_resource_binding.py tests/test_reference_database_registry_templates.py -q
```

Expected:
- The shared helper is proven reusable.
- No new helper abstraction is added without a second consumer.

### Task 4: Record Follow-Up Work, But Do Not Start It In This Round

**Files:**
- Modify: `docs/superpowers/plans/2026-05-06-database-resource-contract-matrix.md`

- [ ] **Step 1: Capture the next two follow-ups explicitly**

Add a short note at the bottom of the working branch or PR description:
- Follow-up A: database page boundary convergence
- Follow-up B: research artifact promotion guardrails

- [ ] **Step 2: Write the exact boundaries for those follow-ups**

Document them as:
- Boundary convergence: front-end consumes top-level `inputPath / entryPath / pathMode / resolvedPath` as the owner contract and stops deriving primary display state from `metadata.resolvedPath`.
- Research hygiene: ignore `.firecrawl/` and `.tavily/`, forbid tests from importing files under `skills/*/scripts`, require exploratory scripts to move into stable directories before tests depend on them.

---

## Priority After This Round

1. `P1`: Contract test architecture for database/resource binding
2. `P2`: Database page state surface and API boundary convergence
3. `P3`: Research artifact promotion guardrails

## Why This Order

- `P1` is the most reusable skill because database pages, SSH, and remote runner control-plane work all showed the same “expand surface first, structure contract tests later” pattern.
- `P2` should come next because the current database page contract is still carrying boundary ambiguity between selected path, resolved path, and displayed tool path.
- `P3` matters, but it is a guardrail problem and can be cleaned up after the team has a stronger habit of defining stable surfaces first.
