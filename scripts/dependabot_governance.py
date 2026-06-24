from __future__ import annotations

import re
from dataclasses import dataclass


MAX_DEPENDABOT_OPEN_PULL_REQUESTS = 5
DEPENDABOT_REQUIRED_UPDATE_GROUPS: dict[tuple[str, str], str] = {
    ("github-actions", "/"): "github-actions",
    ("uv", "/"): "python-uv",
    ("npm", "/"): "root-npm",
    ("npm", "/apps/web"): "web-npm",
    ("npm", "/apps/desktop"): "desktop-npm",
}


@dataclass(frozen=True)
class DependabotContractFinding:
    code: str
    path: str
    line: int
    detail: str


@dataclass(frozen=True)
class DependabotUpdateBlock:
    line: int
    lines: tuple[str, ...]


def scan_dependabot_version_updates_contract(
    relative: str,
    source: str,
) -> list[DependabotContractFinding]:
    findings: list[DependabotContractFinding] = []
    if not re.search(r"^version:\s*2\s*(?:#.*)?$", source, re.MULTILINE):
        findings.append(_finding("dependabot-version", relative, 0, "Dependabot config must use version: 2"))

    blocks = _dependabot_update_blocks(source)
    updates: dict[tuple[str, str], DependabotUpdateBlock] = {}
    for block in blocks:
        ecosystem_line, ecosystem = _dependabot_direct_value(block, "package-ecosystem")
        directory_line, directory = _dependabot_direct_value(block, "directory")
        if not ecosystem or not directory:
            findings.append(
                _finding(
                    "dependabot-update-identity",
                    relative,
                    ecosystem_line or directory_line or block.line,
                    "each Dependabot update must declare package-ecosystem and directory",
                )
            )
            continue

        key = (ecosystem, directory)
        if key in updates:
            findings.append(
                _finding("dependabot-update-duplicate", relative, block.line, f"duplicate Dependabot update for {key}")
            )
        updates[key] = block

        if key not in DEPENDABOT_REQUIRED_UPDATE_GROUPS:
            findings.append(
                _finding(
                    "dependabot-update-unapproved",
                    relative,
                    block.line,
                    f"unapproved Dependabot update for {ecosystem} in {directory}",
                )
            )

    for key, group_name in DEPENDABOT_REQUIRED_UPDATE_GROUPS.items():
        block = updates.get(key)
        if block is None:
            findings.append(
                _finding(
                    "dependabot-version-updates-missing",
                    relative,
                    0,
                    f"missing Dependabot update for {key[0]} in {key[1]}",
                )
            )
            continue

        schedule_line, interval = _dependabot_nested_value(block, "schedule", "interval")
        if interval != "weekly":
            findings.append(
                _finding(
                    "dependabot-update-schedule",
                    relative,
                    schedule_line or block.line,
                    f"Dependabot update for {key[0]} in {key[1]} must run weekly",
                )
            )

        limit_line, pull_request_limit = _dependabot_direct_value(block, "open-pull-requests-limit")
        try:
            limit = int(pull_request_limit or "")
        except ValueError:
            limit = 0
        if limit < 1 or limit > MAX_DEPENDABOT_OPEN_PULL_REQUESTS:
            findings.append(
                _finding(
                    "dependabot-open-pr-limit",
                    relative,
                    limit_line or block.line,
                    (
                        f"Dependabot update for {key[0]} in {key[1]} must set "
                        f"open-pull-requests-limit between 1 and {MAX_DEPENDABOT_OPEN_PULL_REQUESTS}"
                    ),
                )
            )

        if not _dependabot_group_has_all_dependency_pattern(block, group_name):
            findings.append(
                _finding(
                    "dependabot-update-group",
                    relative,
                    block.line,
                    f"Dependabot update for {key[0]} in {key[1]} must group updates as {group_name}",
                )
            )
    return findings


def _finding(code: str, path: str, line: int, detail: str) -> DependabotContractFinding:
    return DependabotContractFinding(code=code, path=path, line=line, detail=detail)


def _dependabot_update_blocks(source: str) -> list[DependabotUpdateBlock]:
    lines = source.splitlines()
    blocks: list[DependabotUpdateBlock] = []
    current_line = 0
    current: list[str] = []
    in_updates = False
    for index, line in enumerate(lines):
        if re.match(r"^updates:\s*(?:#.*)?$", line):
            in_updates = True
            continue
        if not in_updates:
            continue
        if line.strip() and not line.startswith(" "):
            break
        if re.match(r"^  -\s+", line):
            if current:
                blocks.append(DependabotUpdateBlock(current_line, tuple(current)))
            current_line = index + 1
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(DependabotUpdateBlock(current_line, tuple(current)))
    return blocks


def _dependabot_direct_value(block: DependabotUpdateBlock, key: str) -> tuple[int | None, str | None]:
    first_line_re = re.compile(rf"^  -\s+{re.escape(key)}:\s*(.+?)\s*(?:#.*)?$")
    child_line_re = re.compile(rf"^    {re.escape(key)}:\s*(.+?)\s*(?:#.*)?$")
    for offset, line in enumerate(block.lines):
        match = first_line_re.match(line) or child_line_re.match(line)
        if match:
            return block.line + offset, _yaml_literal_value(match.group(1))
    return None, None


def _dependabot_nested_value(
    block: DependabotUpdateBlock,
    parent_key: str,
    child_key: str,
) -> tuple[int | None, str | None]:
    parent_re = re.compile(rf"^    {re.escape(parent_key)}:\s*(?:#.*)?$")
    child_re = re.compile(rf"^      {re.escape(child_key)}:\s*(.+?)\s*(?:#.*)?$")
    for offset, line in enumerate(block.lines):
        if not parent_re.match(line):
            continue
        for child_offset in range(offset + 1, len(block.lines)):
            child = block.lines[child_offset]
            if child.strip() and len(child) - len(child.lstrip(" ")) <= 4:
                break
            match = child_re.match(child)
            if match:
                return block.line + child_offset, _yaml_literal_value(match.group(1))
    return None, None


def _dependabot_group_has_all_dependency_pattern(block: DependabotUpdateBlock, group_name: str) -> bool:
    group_re = re.compile(rf"^      {re.escape(group_name)}:\s*(?:#.*)?$")
    for groups_offset, line in enumerate(block.lines):
        if not re.match(r"^    groups:\s*(?:#.*)?$", line):
            continue
        for group_offset in range(groups_offset + 1, len(block.lines)):
            group_line = block.lines[group_offset]
            if group_line.strip() and len(group_line) - len(group_line.lstrip(" ")) <= 4:
                break
            if not group_re.match(group_line):
                continue
            return _dependabot_group_patterns_include_all(block.lines[group_offset + 1 :])
    return False


def _dependabot_group_patterns_include_all(lines: tuple[str, ...]) -> bool:
    for offset, line in enumerate(lines):
        if line.strip() and len(line) - len(line.lstrip(" ")) <= 6:
            break
        if not re.match(r"^        patterns:\s*(?:#.*)?$", line):
            continue
        for pattern_line in lines[offset + 1 :]:
            if pattern_line.strip() and len(pattern_line) - len(pattern_line.lstrip(" ")) <= 8:
                break
            match = re.match(r"^          -\s*(.+?)\s*(?:#.*)?$", pattern_line)
            if match and _yaml_literal_value(match.group(1)) == "*":
                return True
    return False


def _yaml_literal_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
