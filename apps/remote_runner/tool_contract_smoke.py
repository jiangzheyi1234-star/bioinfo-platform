from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any


def materialize_smoke_inputs(tool: dict[str, Any], input_dir: Path) -> list[dict[str, Any]]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    specs = [item for item in (template.get("inputs") or []) if isinstance(item, dict)]
    if not specs:
        specs = [{"name": "primary", "type": "file", "required": True}]
    smoke_inputs = smoke_test(tool).get("inputs")
    smoke_inputs = smoke_inputs if isinstance(smoke_inputs, dict) else {}
    input_dir.mkdir(parents=True, exist_ok=True)
    resolved: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        fixture = smoke_inputs.get(name) if isinstance(smoke_inputs.get(name), dict) else {}
        if not bool(spec.get("required", True)) and not fixture:
            continue
        filename = str(fixture.get("filename") or _default_input_filename(name, spec)).strip()
        path = input_dir / Path(filename).name
        content = _fixture_bytes(fixture, spec)
        path.write_bytes(content)
        resolved.append(
            {
                "uploadId": f"smoke_{name}",
                "filename": path.name,
                "role": "input" if index == 0 else f"input_{index + 1}",
                "path": str(path),
                "sizeBytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "mimeType": str(fixture.get("mimeType") or spec.get("mimeType") or "text/plain"),
                "index": index,
            }
        )
    return resolved


def smoke_workflow_inputs(tool: dict[str, Any], resolved_inputs: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    specs = [item for item in (template.get("inputs") or []) if isinstance(item, dict)]
    inputs: dict[str, dict[str, str]] = {}
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        if not name or index >= len(resolved_inputs):
            continue
        role = str(resolved_inputs[index].get("role") or "").strip()
        if role:
            inputs[name] = {"fromInput": role}
    return inputs


def smoke_fixture_error(tool: dict[str, Any]) -> dict[str, str] | None:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    specs = [item for item in (template.get("inputs") or []) if isinstance(item, dict)]
    smoke_inputs = smoke_test(tool).get("inputs")
    if not isinstance(smoke_inputs, dict) or not smoke_inputs:
        return {"code": "TOOL_RULE_SMOKE_TEST_REQUIRED", "message": "Smoke test input fixtures are required."}
    missing: list[str] = []
    for index, spec in enumerate(specs):
        name = str(spec.get("name") or ("primary" if index == 0 else f"input_{index + 1}")).strip()
        fixture = smoke_inputs.get(name)
        if not bool(spec.get("required", True)) and not isinstance(fixture, dict):
            continue
        if not isinstance(fixture, dict) or ("content" not in fixture and "contentBase64" not in fixture):
            missing.append(name)
    if missing:
        return {
            "code": "TOOL_RULE_SMOKE_INPUT_REQUIRED",
            "message": f"Smoke test input fixture is missing: {', '.join(missing)}",
        }
    return None


def smoke_test(tool: dict[str, Any]) -> dict[str, Any]:
    template = tool.get("ruleTemplate") if isinstance(tool.get("ruleTemplate"), dict) else {}
    raw_smoke = template.get("smokeTest")
    return raw_smoke if isinstance(raw_smoke, dict) else {}


def smoke_timeout(tool: dict[str, Any]) -> int:
    raw = smoke_test(tool).get("timeoutSeconds")
    try:
        return max(1, min(int(raw or 600), 3600))
    except (TypeError, ValueError):
        return 600


def _fixture_bytes(fixture: dict[str, Any], spec: dict[str, Any]) -> bytes:
    if "contentBase64" in fixture:
        return base64.b64decode(str(fixture["contentBase64"]).encode("utf-8"))
    if "content" in fixture:
        return str(fixture["content"]).encode("utf-8")
    return _default_input_content(spec)


def _default_input_filename(name: str, spec: dict[str, Any]) -> str:
    mime_type = str(spec.get("mimeType") or "").lower()
    kind = str(spec.get("kind") or "").lower()
    if "fastq" in mime_type or "sequence" in kind or name in {"reads", "fastq"}:
        return f"{name}.fastq"
    if "json" in mime_type:
        return f"{name}.json"
    return f"{name}.txt"


def _default_input_content(spec: dict[str, Any]) -> bytes:
    mime_type = str(spec.get("mimeType") or "").lower()
    kind = str(spec.get("kind") or "").lower()
    if "fastq" in mime_type or "sequence" in kind:
        return b"@smoke\nACGT\n+\nFFFF\n"
    if "json" in mime_type:
        return b'{"smoke": true}\n'
    return b"smoke\n"
