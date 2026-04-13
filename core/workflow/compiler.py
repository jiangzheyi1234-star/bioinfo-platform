"""Minimal Nextflow bundle compiler for workflow-first migration."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .domain import LaunchSpec, WorkflowSpec


def _yaml_dump(value: Any, indent: int = 0) -> str:
    pad = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(_yaml_dump(item, indent + 2))
            else:
                lines.append(f"{pad}{key}: {_scalar_yaml(item)}")
        return "\n".join(lines) if lines else f"{pad}{{}}"
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_yaml_dump(item, indent + 2))
            else:
                lines.append(f"{pad}- {_scalar_yaml(item)}")
        return "\n".join(lines) if lines else f"{pad}[]"
    return f"{pad}{_scalar_yaml(value)}"


def _scalar_yaml(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in [":", "#", "\n", "{", "}", "[", "]"]):
        return json.dumps(text, ensure_ascii=False)
    return text


def _build_main_nf(spec: WorkflowSpec) -> str:
    process_blocks = []
    workflow_lines = ["workflow {"]
    for node in spec.nodes:
        process_blocks.append(
            "\n".join(
                [
                    f"process {node.node_id} {{",
                    "  tag { params.run_name ?: 'adhoc-run' }",
                    "  input:",
                    "    val meta",
                    "  output:",
                    f"    path '{node.node_id}.done'",
                    "  script:",
                    f"  \"\"\"\n  echo {node.tool_id} > {node.node_id}.done\n  \"\"\"",
                    "}",
                ]
            )
        )
        workflow_lines.append(f"  {node.node_id}(params.meta ?: [:])")
    workflow_lines.append("}")
    return "\n\n".join(process_blocks + ["\n".join(workflow_lines)])


def _build_nextflow_config(launch: LaunchSpec) -> str:
    lines = [
        "manifest {",
        "  name = 'h2ometa-generated-workflow'",
        "}",
        "",
        "params {",
        "  run_name = 'h2ometa-run'",
        "  meta = [:]",
        "}",
        "",
        f"process.executor = '{launch.profile.executor}'",
    ]
    if launch.profile.packaging_mode == "container" and launch.profile.container_runtime:
        runtime = launch.profile.container_runtime
        lines.extend(
            [
                "",
                f"{runtime} {{",
                "  enabled = true",
                f"  cacheDir = '{launch.profile.cache_dir or '~/.bioflow/cache'}'",
                "}",
            ]
        )
    if launch.profile.packaging_mode == "conda":
        lines.extend(
            [
                "",
                "conda {",
                "  enabled = true",
                "  useMicromamba = true",
                f"  cacheDir = '{launch.profile.cache_dir or '~/.bioflow/cache/conda'}'",
                "}",
            ]
        )
    if launch.profile.work_dir:
        lines.append(f"workDir = '{launch.profile.work_dir}'")
    return "\n".join(lines) + "\n"


def compile_workflow_bundle(spec: WorkflowSpec, launch: LaunchSpec) -> dict[str, Any]:
    bundle_id = f"bundle_{uuid.uuid4().hex[:12]}"
    main_nf = _build_main_nf(spec)
    config_text = _build_nextflow_config(launch)
    params_yaml = _yaml_dump(launch.params or {})
    params_schema = spec.params_schema or {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }
    manifest = {
        "bundle_id": bundle_id,
        "generated_at": time.time(),
        "workflow_id": spec.workflow_id,
        "workflow_name": spec.name,
        "workflow_version": spec.version,
        "profile_id": launch.profile.profile_id,
        "profile_kind": launch.profile.profile_kind,
        "executor": launch.profile.executor,
        "packaging_mode": launch.profile.packaging_mode,
        "node_count": len(spec.nodes),
        "edge_count": len(spec.edges),
        "resume": launch.resume,
        "data_refs": launch.data_refs,
    }
    files = {
        "main.nf": main_nf,
        "nextflow.config": config_text,
        "resolved.config": config_text,
        "params/run.yaml": params_yaml + ("\n" if params_yaml else ""),
        "params.schema.json": json.dumps(params_schema, ensure_ascii=False, indent=2) + "\n",
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    }
    return {
        "bundle_id": bundle_id,
        "files": files,
        "manifest": manifest,
    }
