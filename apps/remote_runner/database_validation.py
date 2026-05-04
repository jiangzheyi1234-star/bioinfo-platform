from __future__ import annotations

import os
import re
import shlex
import subprocess
from hashlib import sha256
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_AMBIGUOUS_CANDIDATES = 6

@dataclass(frozen=True)
class ToolProbeResult:
    ok: bool
    command: str
    stdout: str
    stderr: str
    returncode: int


def run_tool_probe(command: str, *, timeout: int) -> ToolProbeResult:
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return ToolProbeResult(ok=False, command=command, stdout="", stderr=str(exc), returncode=127)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else "tool probe timed out"
        return ToolProbeResult(ok=False, command=command, stdout=stdout, stderr=stderr, returncode=124)
    return ToolProbeResult(
        ok=result.returncode == 0,
        command=command,
        stdout=result.stdout[-4000:],
        stderr=result.stderr[-4000:],
        returncode=result.returncode,
    )


def render_tool_probe_command(template: dict[str, Any], data_path: Path, resolved: dict[str, str]) -> str:
    probe = dict(template.get("toolProbe") or {})
    command = str(probe.get("commandTemplate") or "").strip()
    if not command:
        return ""
    path_kind = str(template.get("pathKind") or "directory")
    tool_path = resolved.get("path") if path_kind in {"file", "primary_with_sidecars"} else str(data_path)
    context = {
        "path": tool_path or str(data_path),
        "parent": str(data_path.parent),
        "prefix": resolved.get("prefix") or str(data_path),
        "firstMatch": resolved.get("firstMatch") or str(data_path),
        "firstIndexPrefix": resolved.get("firstIndexPrefix") or resolved.get("prefix") or str(data_path),
    }
    for key, value in context.items():
        command = command.replace(f"{{{key}}}", value)
        command = command.replace(f"{{{key}:q}}", shlex.quote(value))
    return command


def prepare_tool_probe_command(cfg: Any, template_id: str, template: dict[str, Any], command: str) -> str:
    probe = dict(template.get("toolProbe") or {})
    package_specs = _tool_probe_package_specs(probe)
    if not package_specs:
        return command
    package_spec = "\n".join(package_specs)
    env_path = ensure_probe_environment(cfg, template_id=template_id, package_spec=package_spec)
    conda_command = str(cfg.managed_conda_command or "").strip()
    conda_bin = str(Path(conda_command).parent)
    return " ".join(
        [
            f"PATH={shlex.quote(conda_bin)}:$PATH",
            f"CONDA_EXE={shlex.quote(conda_command)}",
            shlex.quote(conda_command),
            "run",
            "-p",
            shlex.quote(str(env_path)),
            "bash",
            "-lc",
            shlex.quote(command),
        ]
    )


def ensure_probe_environment(cfg: Any, *, template_id: str, package_spec: str) -> Path:
    conda_command = str(cfg.managed_conda_command or "").strip()
    if not conda_command:
        raise RuntimeError("Conda command is not configured on the remote runner.")
    conda_path = Path(conda_command)
    if not conda_path.exists():
        raise RuntimeError(f"Conda command does not exist: {conda_command}")

    env_root = Path(str(cfg.data_root)) / "database-probe-envs"
    env_path = env_root / _safe_env_name(template_id)
    marker = env_path / ".h2ometa-package-spec"
    if marker.exists() and marker.read_text(encoding="utf-8") == package_spec:
        return env_path
    if env_path.exists():
        env_path = env_root / f"{_safe_env_name(template_id)}-{sha256(package_spec.encode('utf-8')).hexdigest()[:12]}"
        marker = env_path / ".h2ometa-package-spec"
        if marker.exists() and marker.read_text(encoding="utf-8") == package_spec:
            return env_path

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env = _conda_subprocess_env(conda_path)
    result = subprocess.run(
        [conda_command, "create", "-y", "-p", str(env_path), *_package_specs_from_marker(package_spec)],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
        env=env,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Failed to prepare database probe environment for {template_id}: {detail}")
    marker.write_text(package_spec, encoding="utf-8")
    return env_path


def _tool_probe_package_specs(probe: dict[str, Any]) -> list[str]:
    specs = [str(value).strip() for value in probe.get("packageSpecs") or [] if str(value).strip()]
    if specs:
        return specs
    spec = str(probe.get("packageSpec") or "").strip()
    return [spec] if spec else []


def _package_specs_from_marker(package_spec: str) -> list[str]:
    return [line.strip() for line in str(package_spec).splitlines() if line.strip()]


def _safe_env_name(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in str(value)).strip("-") or "database"


def _conda_subprocess_env(conda_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    conda_bin = str(conda_path.parent)
    current_path = env.get("PATH", "")
    env["PATH"] = conda_bin if not current_path else f"{conda_bin}{os.pathsep}{current_path}"
    env["CONDA_EXE"] = str(conda_path)
    return env


def probe_metadata(result: ToolProbeResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "command": result.command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def validate_template_files(
    data_path: Path,
    item: dict[str, Any],
    template: dict[str, Any] | None,
    *,
    resolved: dict[str, str] | None = None,
) -> str:
    metadata = dict(item.get("metadata") or {})
    template_id = str(metadata.get("templateId") or "").strip().lower()
    expected_files = [str(value).strip() for value in metadata.get("expectedFiles") or [] if str(value).strip()]

    if template_id == "custom":
        return missing_named_files(data_path, expected_files)
    if template is None:
        return ""
    if str(template.get("pathKind") or "directory") == "prefix":
        if (resolved or {}).get("ambiguousCandidates"):
            return ambiguous_target_error(template_id, resolved or {})
        prefix = Path(str((resolved or {}).get("prefix") or data_path))
        return prefix_structure_error(prefix, template)
    if str(template.get("pathKind") or "directory") == "primary_with_sidecars":
        if (resolved or {}).get("ambiguousCandidates"):
            return ambiguous_target_error(template_id, resolved or {})
        resolved_path = Path(str((resolved or {}).get("path") or data_path))
        return primary_with_sidecars_structure_error(resolved_path, template)
    if str(template.get("pathKind") or "directory") == "file" and data_path.is_dir():
        if (resolved or {}).get("ambiguousCandidates"):
            return ambiguous_target_error(template_id, resolved or {})
        resolved_path = Path(str((resolved or {}).get("path") or ""))
        if not resolved_path.is_file():
            return f"Database template {template_id} requires a matching file under: {data_path}"
        return validate_template_file_path(resolved_path, template_id, template)
    if not data_path.is_dir():
        return validate_template_file_path(data_path, template_id, template)

    missing = missing_named_files(data_path, [*template.get("requiredFiles", []), *expected_files])
    if missing:
        return missing
    for pattern in template.get("requiredPatterns", []):
        if not any(data_path.glob(str(pattern))):
            return f"Database template {template_id} requires a file matching {pattern} in {data_path}"
    any_patterns = [str(pattern) for pattern in template.get("anyPatterns", []) if str(pattern).strip()]
    if any_patterns and not any(any(data_path.glob(pattern)) for pattern in any_patterns):
        return f"Database template {template_id} requires at least one file matching: {', '.join(any_patterns)}"
    if template.get("anyIndexPatterns") and not any(any(data_path.glob(str(pattern))) for pattern in template["anyIndexPatterns"]):
        return f"Database template {template_id} requires at least one index file matching: {', '.join(template['anyIndexPatterns'])}"
    if template.get("anyFiles") and not any((data_path / str(filename)).exists() or any(data_path.glob(f"**/{filename}")) for filename in template["anyFiles"]):
        return f"Database template {template_id} requires one of these files under {data_path}: {', '.join(template['anyFiles'])}"
    for pattern_set in template.get("anyPatternSets", []):
        if all(any(data_path.glob(str(pattern))) for pattern in pattern_set):
            break
    else:
        if template.get("anyPatternSets"):
            choices = [" + ".join(pattern_set) for pattern_set in template["anyPatternSets"]]
            return f"Database template {template_id} requires one complete index set: {' or '.join(choices)}"
    return ""


def validate_template_file_path(data_path: Path, template_id: str, template: dict[str, Any]) -> str:
    if str(template.get("pathKind") or "directory") == "directory":
        return f"Database template {template_id} requires a directory path: {data_path}"
    if str(template.get("pathKind") or "directory") == "primary_with_sidecars":
        return validate_primary_with_sidecars_path(data_path, template_id, template)

    filename = data_path.name
    patterns: list[str] = []
    patterns.extend(str(pattern) for pattern in template.get("anyPatterns", []) if str(pattern).strip())
    patterns.extend(str(pattern) for pattern in template.get("requiredPatterns", []) if str(pattern).strip())
    patterns.extend(str(pattern) for pattern in template.get("anyIndexPatterns", []) if str(pattern).strip())
    patterns.extend(str(filename) for filename in template.get("anyFiles", []) if str(filename).strip())
    for pattern_set in template.get("anyPatternSets", []):
        patterns.extend(str(pattern) for pattern in pattern_set if str(pattern).strip())
    companion_suffixes = [str(value) for value in template.get("companionSuffixes", []) if str(value).strip()]
    if companion_suffixes:
        base = data_path.with_suffix("")
        missing = [str(base) + suffix for suffix in companion_suffixes if not Path(str(base) + suffix).exists()]
        if missing:
            return f"Database template {template_id} requires companion file(s): {', '.join(missing)}"
    if not patterns:
        return ""
    if any(data_path.match(pattern) or Path(filename).match(pattern) for pattern in patterns):
        return ""
    return f"Database template {template_id} requires a file matching: {', '.join(patterns)}"


def missing_prefix_set(prefix: Path, template: dict[str, Any]) -> str:
    pattern_sets = template.get("prefixPatternSets") or []
    if not pattern_sets:
        return ""
    missing_choices: list[list[str]] = []
    for pattern_set in pattern_sets:
        expected = [str(prefix) + str(suffix) for suffix in pattern_set if str(suffix).strip()]
        missing = [path for path in expected if not Path(path).exists()]
        if not missing:
            return ""
        missing_choices.append(missing)
    shortest = min(missing_choices, key=len)
    return f"Database template requires one complete prefix index set; missing file(s): {', '.join(shortest)}"


def prefix_structure_error(prefix: Path, template: dict[str, Any]) -> str:
    if _prefix_alias_for_prefix(prefix, template) is not None:
        return ""
    return missing_prefix_set(prefix, template)


def primary_with_sidecars_structure_error(fasta_path: Path, template: dict[str, Any]) -> str:
    template_id = str(template.get("label") or "primary_with_sidecars")
    path_error = validate_primary_with_sidecars_path(fasta_path, template_id, template)
    if path_error:
        return path_error
    missing = [str(fasta_path) + str(suffix) for suffix in template.get("indexSuffixes", []) if not Path(str(fasta_path) + str(suffix)).exists()]
    if missing:
        return f"Database template requires sidecar index companion file(s): {', '.join(missing)}"
    return ""


def validate_primary_with_sidecars_path(data_path: Path, template_id: str, template: dict[str, Any]) -> str:
    if data_path.is_dir():
        return f"Database template {template_id} requires a FASTA main file, not a directory: {data_path}"
    if not data_path.is_file():
        return f"Database template {template_id} requires a FASTA main file: {data_path}"
    fasta_patterns = [str(pattern) for pattern in template.get("anyPatterns", []) if str(pattern).strip()]
    filename = data_path.name
    if fasta_patterns and not any(data_path.match(pattern) or Path(filename).match(pattern) for pattern in fasta_patterns):
        return f"Database template {template_id} requires a FASTA main file matching: {', '.join(fasta_patterns)}"
    return ""


def resolve_template_path(data_path: Path, template: dict[str, Any]) -> dict[str, str]:
    path_kind = str(template.get("pathKind") or "directory")
    resolved = {"kind": path_kind, "path": str(data_path)}
    if path_kind == "prefix":
        if data_path.is_dir():
            alias_candidates = prefix_alias_prefixes_in_directory(data_path, template)
            candidates = alias_candidates or complete_prefixes_in_directory(data_path, template)
            if len(candidates) > 1:
                resolved["ambiguousCandidates"] = json_list(candidates)
                return resolved
            if len(candidates) == 1:
                resolved["prefix"] = str(candidates[0])
                return resolved
        resolved["prefix"] = str(resolve_prefix_path(data_path, template))
        return resolved
    if path_kind == "file" and data_path.is_dir():
        matches = template_file_matches(data_path, template)
        if len(matches) > 1:
            resolved["ambiguousCandidates"] = json_list(matches)
            return resolved
        if len(matches) == 1:
            resolved["path"] = str(matches[0])
            resolved["firstMatch"] = str(matches[0])
        return resolved
    if path_kind == "primary_with_sidecars":
        if data_path.is_dir():
            matches = template_file_matches(data_path, template)
            if len(matches) > 1:
                resolved["ambiguousCandidates"] = json_list(matches)
                return resolved
            if len(matches) == 1:
                resolved["path"] = str(matches[0])
                resolved["firstMatch"] = str(matches[0])
            return resolved
        if data_path.is_file():
            resolved["firstMatch"] = str(data_path)
        return resolved
    if data_path.is_file():
        resolved["firstMatch"] = str(data_path)
        return resolved
    for pattern in template.get("anyIndexPatterns", []):
        match = next(data_path.glob(str(pattern)), None)
        if match is not None:
            resolved["firstMatch"] = str(match)
            resolved["firstIndexPrefix"] = strip_known_index_suffix(match)
            return resolved
    for pattern in template.get("anyPatterns", []):
        match = next(data_path.glob(str(pattern)), None)
        if match is not None:
            resolved["firstMatch"] = str(match)
            return resolved
    return resolved


def resolve_prefix_path(data_path: Path, template: dict[str, Any]) -> Path:
    if missing_prefix_set(data_path, template) == "":
        return data_path
    alias_path = _prefix_alias_path(data_path, template)
    if alias_path is not None:
        return alias_path.with_suffix("")
    directory_prefix = first_complete_prefix_in_directory(data_path, template)
    if directory_prefix is not None:
        return directory_prefix
    stripped = strip_known_prefix_suffix(data_path, template)
    if stripped != data_path and missing_prefix_set(stripped, template) == "":
        return stripped
    return data_path


def first_complete_prefix_in_directory(data_path: Path, template: dict[str, Any]) -> Path | None:
    matches = complete_prefixes_in_directory(data_path, template)
    return matches[0] if matches else None


def complete_prefixes_in_directory(data_path: Path, template: dict[str, Any]) -> list[Path]:
    if not data_path.is_dir():
        return []
    matches: list[Path] = []
    for pattern_set in template.get("prefixPatternSets", []):
        suffixes = [str(suffix) for suffix in pattern_set if str(suffix).strip()]
        for suffix in suffixes:
            for match in data_path.glob(f"*{suffix}"):
                prefix = match.with_name(match.name[: -len(suffix)])
                if missing_prefix_set(prefix, template) == "":
                    matches.append(prefix)
    return unique_paths(matches)


def prefix_alias_prefixes_in_directory(data_path: Path, template: dict[str, Any]) -> list[Path]:
    if not data_path.is_dir():
        return []
    return unique_paths([path.with_suffix("") for path in _prefix_alias_paths(data_path, template)])


def first_template_file_match(data_path: Path, template: dict[str, Any]) -> Path | None:
    matches = template_file_matches(data_path, template)
    return matches[0] if matches else None


def template_file_matches(data_path: Path, template: dict[str, Any]) -> list[Path]:
    patterns: list[str] = []
    patterns.extend(str(pattern) for pattern in template.get("anyPatterns", []) if str(pattern).strip())
    patterns.extend(str(pattern) for pattern in template.get("requiredPatterns", []) if str(pattern).strip())
    patterns.extend(str(pattern) for pattern in template.get("anyIndexPatterns", []) if str(pattern).strip())
    patterns.extend(str(filename) for filename in template.get("anyFiles", []) if str(filename).strip())
    for pattern_set in template.get("anyPatternSets", []):
        patterns.extend(str(pattern) for pattern in pattern_set if str(pattern).strip())
    matches: list[Path] = []
    for pattern in patterns:
        for match in data_path.glob(pattern):
            if match.is_file():
                matches.append(match)
    return unique_paths(matches)


def _prefix_alias_path(data_path: Path, template: dict[str, Any]) -> Path | None:
    matches = _prefix_alias_paths(data_path, template)
    return matches[0] if matches else None


def _prefix_alias_paths(data_path: Path, template: dict[str, Any]) -> list[Path]:
    alias_patterns = [str(pattern) for pattern in template.get("prefixAliasPatterns", []) if str(pattern).strip()]
    if not alias_patterns:
        return []
    if data_path.is_file() and any(data_path.match(pattern) or Path(data_path.name).match(pattern) for pattern in alias_patterns):
        return [data_path]
    matches: list[Path] = []
    if data_path.is_dir():
        for pattern in alias_patterns:
            matches.extend(match for match in data_path.glob(pattern) if match.is_file())
    return unique_paths(matches)


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in sorted(paths, key=lambda item: str(item)):
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def json_list(paths: list[Path]) -> str:
    if not paths:
        return ""
    if len(paths) <= MAX_AMBIGUOUS_CANDIDATES:
        return ", ".join(str(path) for path in paths)
    shown = ", ".join(str(path) for path in paths[:MAX_AMBIGUOUS_CANDIDATES])
    omitted = len(paths) - MAX_AMBIGUOUS_CANDIDATES
    return f"{shown}（还有 {omitted} 个候选）"


def ambiguous_target_error(template_id: str, resolved: dict[str, str]) -> str:
    return (
        f"Database template {template_id} found multiple candidate targets: "
        f"{resolved.get('ambiguousCandidates') or '未知候选项'}. Please enter a more specific directory."
    )


def bracken_read_lengths(data_path: Path) -> list[int]:
    if not data_path.is_dir():
        return []
    lengths: list[int] = []
    for path in data_path.glob("database*mers.kmer_distrib"):
        match = re.fullmatch(r"database(\d+)mers\.kmer_distrib", path.name)
        if match:
            lengths.append(int(match.group(1)))
    return sorted(set(lengths))


def _prefix_alias_for_prefix(prefix: Path, template: dict[str, Any]) -> Path | None:
    alias_patterns = [str(pattern) for pattern in template.get("prefixAliasPatterns", []) if str(pattern).strip()]
    alias_suffixes = [pattern[1:] for pattern in alias_patterns if pattern.startswith("*") and "/" not in pattern]
    for suffix in alias_suffixes:
        candidate = Path(str(prefix) + suffix)
        if candidate.exists():
            return candidate
    return None


def strip_known_prefix_suffix(path: Path, template: dict[str, Any]) -> Path:
    name = path.name
    suffixes: list[str] = []
    for pattern_set in template.get("prefixPatternSets", []):
        suffixes.extend(str(suffix) for suffix in pattern_set if str(suffix).strip())
    suffixes.extend([".nal", ".pal", ".00.nhr", ".00.nin", ".00.nsq", ".00.phr", ".00.pin", ".00.psq"])
    for suffix in sorted(set(suffixes), key=len, reverse=True):
        if name.endswith(suffix):
            return path.with_name(name[: -len(suffix)])
    return path


def strip_known_index_suffix(path: Path) -> str:
    name = path.name
    suffixes = [
        ".rev.2.bt2l",
        ".rev.1.bt2l",
        ".rev.2.bt2",
        ".rev.1.bt2",
        ".1.bt2l",
        ".2.bt2l",
        ".3.bt2l",
        ".4.bt2l",
        ".1.bt2",
        ".2.bt2",
        ".3.bt2",
        ".4.bt2",
    ]
    for suffix in suffixes:
        if name.endswith(suffix):
            return str(path.with_name(name[: -len(suffix)]))
    return str(path.with_suffix(""))


def missing_named_files(data_path: Path, filenames: list[str]) -> str:
    missing = [filename for filename in filenames if not (data_path / filename).exists()]
    if not missing:
        return ""
    return f"Database path is missing required file(s): {', '.join(missing)}"
