from __future__ import annotations

import re

from .tools_errors import ToolRegistryError


RULE_TOKEN_RE = re.compile(r"\{[^{}\s]+\}")
DATABASE_TOKEN_RE = re.compile(
    r"^database\.[A-Za-z_][A-Za-z0-9_]*\.(id|name|type|templateId|version|path|manifestPath|checksum)(:q)?$"
)
CONFIG_TOKEN_RE = re.compile(r"^config\.[A-Za-z_][A-Za-z0-9_]*(:q)?$")


def validate_command_tokens(
    command: str,
    *,
    input_names: set[str],
    output_names: set[str],
    param_names: set[str],
    threads_declared: bool,
    scheduler_resource_names: set[str],
    log_names: set[str],
    has_log: bool,
) -> None:
    if "{resource." in command:
        raise ToolRegistryError("TOOL_RULE_RESOURCE_TOKEN_UNSUPPORTED")
    for match in RULE_TOKEN_RE.finditer(command):
        token = match.group(0)
        body = token[1:-1]
        if body in {"input", "input:q", "output", "output:q", "output_dir", "output_dir:q"}:
            continue
        if body in {"threads", "threads:q"} and threads_declared:
            continue
        if body in {"log", "log:q"} and has_log:
            continue
        if body.startswith("input."):
            name = body.removeprefix("input.").removesuffix(":q")
            if name in input_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("output."):
            name = body.removeprefix("output.").removesuffix(":q")
            if name in output_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("params."):
            name = body.removeprefix("params.").removesuffix(":q")
            if name in param_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("resources."):
            name = body.removeprefix("resources.").removesuffix(":q")
            if name in scheduler_resource_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if body.startswith("log."):
            name = body.removeprefix("log.").removesuffix(":q")
            if name in log_names:
                continue
            raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
        if DATABASE_TOKEN_RE.match(body) or CONFIG_TOKEN_RE.match(body):
            continue
        raise ToolRegistryError(f"TOOL_RULE_TOKEN_UNSUPPORTED: {token}")
