"""Workflow-first Nextflow bundle compiler."""

from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any

from core.execution.command_builder import CommandBuilder

from .domain import LaunchSpec, WorkflowSpec

_LEGACY_CONDA_ENV_MARKER = "/.h2ometa/conda/envs/"
_LEGACY_PLUGIN_FIELDS = ("conda_env", "install_cmd")
_SUPPORTED_PROFILE_KINDS = {
    "personal_docker",
    "personal_podman",
    "personal_conda",
    "hpc_slurm_apptainer",
    "hpc_slurm_conda",
    "hpc_pbs_apptainer",
    "hpc_pbs_conda",
    "hpc_sge_apptainer",
    "hpc_sge_conda",
}
_DEFAULT_WORK_DIR = "~/.bioflow/runs/work"
_DEFAULT_OUTPUT_DIR = "~/.bioflow/runs/output"
_DEFAULT_CONDA_CACHE_DIR = "~/.bioflow/cache/conda"
_DEFAULT_CONTAINER_CACHE_DIR = "~/.bioflow/cache/containers"


@dataclass(frozen=True)
class _ResolvedRuntime:
    container_ref: str
    conda_spec: str
    cpus: int | None
    memory: str
    time_limit: str


@dataclass(frozen=True)
class _CompiledNode:
    node_id: str
    process_name: str
    emit_names: dict[str, str]
    input_names: list[str]
    process_block: str


@dataclass(frozen=True)
class _ProfileResolution:
    profile_kind: str
    executor: str
    packaging_mode: str
    container_runtime: str
    work_dir: str
    output_dir: str
    cache_dir: str
    runtime_block_name: str
    runtime_block_lines: list[str]
    cache_policy: str


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


def _sanitize_identifier(value: str, *, prefix: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value or "").strip())
    cleaned = cleaned.strip("_")
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned


def _groovy_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _sample_id_for_bundle(spec: WorkflowSpec, launch: LaunchSpec) -> str:
    sample_id = str(
        launch.params.get("sample_id")
        or launch.params.get("sample_name")
        or spec.workflow_id
        or "sample"
    ).strip()
    return _sanitize_identifier(sample_id, prefix="sample")


def _reject_legacy_plugin_format(descriptor: dict[str, Any]) -> None:
    legacy_fields = [
        field
        for field in _LEGACY_PLUGIN_FIELDS
        if str(descriptor.get(field) or "").strip()
    ]
    if legacy_fields:
        plugin_id = descriptor.get("id") or "<unknown>"
        joined = ", ".join(legacy_fields)
        raise RuntimeError(
            f"插件 {plugin_id} 仍使用旧格式字段 {joined}；"
            "请先迁移到 runtime.container/runtime.conda 后再编译 workflow"
        )
    runtime = descriptor.get("runtime")
    if not isinstance(runtime, dict) or not runtime:
        plugin_id = descriptor.get("id") or "<unknown>"
        raise RuntimeError(
            f"插件 {plugin_id} 缺少 runtime 元数据；"
            "旧格式插件不再被 compiler 接受"
        )
    if _LEGACY_CONDA_ENV_MARKER in str(descriptor.get("command_template") or ""):
        plugin_id = descriptor.get("id") or "<unknown>"
        raise RuntimeError(
            f"插件 {plugin_id} 的 command_template 仍硬编码旧 conda env 路径；"
            "请改为 runtime.container/runtime.conda 后再编译 workflow"
        )


def _extract_conda_spec(descriptor: dict[str, Any]) -> str:
    runtime = descriptor.get("runtime")
    if not isinstance(runtime, dict):
        return ""
    return str(runtime.get("conda") or "").strip()


def _resolve_runtime(descriptor: dict[str, Any], launch: LaunchSpec) -> _ResolvedRuntime:
    _reject_legacy_plugin_format(descriptor)
    runtime = descriptor.get("runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    resources = descriptor.get("resources")
    resources = resources if isinstance(resources, dict) else {}
    container_ref = str(runtime.get("container") or "").strip()
    if launch.profile.packaging_mode == "container" and not container_ref:
        raise RuntimeError(
            f"插件 {descriptor.get('id') or '<unknown>'} 缺少 runtime.container，无法生成 container workflow"
        )
    conda_spec = _extract_conda_spec(descriptor)
    if launch.profile.packaging_mode == "conda" and not conda_spec:
        raise RuntimeError(
            f"插件 {descriptor.get('id') or '<unknown>'} 缺少 runtime.conda，无法生成 conda workflow"
        )
    cpus = None
    if resources.get("cpus") not in (None, ""):
        cpus = int(resources["cpus"])
    memory = str(resources.get("memory") or "").strip()
    time_limit = str(resources.get("time") or "").strip()
    return _ResolvedRuntime(
        container_ref=container_ref,
        conda_spec=conda_spec,
        cpus=cpus,
        memory=memory,
        time_limit=time_limit,
    )


def _default_profile_paths(launch: LaunchSpec) -> tuple[str, str, str]:
    work_dir = str(launch.profile.work_dir or "").strip() or _DEFAULT_WORK_DIR
    output_dir = str(launch.profile.output_dir or "").strip() or _DEFAULT_OUTPUT_DIR
    if str(launch.profile.cache_dir or "").strip():
        cache_dir = str(launch.profile.cache_dir).strip()
    elif launch.profile.packaging_mode == "conda":
        cache_dir = _DEFAULT_CONDA_CACHE_DIR
    else:
        cache_dir = _DEFAULT_CONTAINER_CACHE_DIR
    return work_dir, output_dir, cache_dir


def _profile_resolution(launch: LaunchSpec) -> _ProfileResolution:
    profile_kind = str(launch.profile.profile_kind or "").strip()
    executor = str(launch.profile.executor or "").strip()
    packaging_mode = str(launch.profile.packaging_mode or "").strip()
    container_runtime = str(launch.profile.container_runtime or "").strip()
    if not profile_kind:
        raise RuntimeError("launch.profile.profile_kind is required")
    if profile_kind not in _SUPPORTED_PROFILE_KINDS:
        raise RuntimeError(f"不支持的 workflow profile_kind: {profile_kind}")
    if not executor:
        raise RuntimeError("launch.profile.executor is required")
    if packaging_mode not in {"container", "conda"}:
        raise RuntimeError(f"不支持的 packaging_mode: {packaging_mode or '<empty>'}")
    if packaging_mode == "container" and not container_runtime:
        raise RuntimeError(f"profile {profile_kind} 需要 container_runtime")
    work_dir, output_dir, cache_dir = _default_profile_paths(launch)
    if profile_kind == "personal_docker":
        runtime_block_name = "docker"
        runtime_block_lines = [
            "docker {",
            "  enabled = true",
            "}",
        ]
        cache_policy = "container"
    elif profile_kind == "personal_podman":
        runtime_block_name = "podman"
        runtime_block_lines = [
            "podman {",
            "  enabled = true",
            "}",
        ]
        cache_policy = "container"
    elif profile_kind == "hpc_slurm_apptainer":
        runtime_block_name = "apptainer"
        runtime_block_lines = [
            "apptainer {",
            "  enabled = true",
            "  autoMounts = true",
            "}",
        ]
        cache_policy = "container"
    elif profile_kind == "personal_conda" or profile_kind == "hpc_slurm_conda":
        runtime_block_name = "conda"
        runtime_block_lines = [
            "conda {",
            "  enabled = true",
            "  useMicromamba = true",
            f"  cacheDir = {_groovy_string(cache_dir)}",
            "}",
        ]
        cache_policy = "conda"
    else:
        runtime_block_name = "conda" if packaging_mode == "conda" else container_runtime
        runtime_block_lines = []
        if packaging_mode == "conda":
            runtime_block_lines = [
                "conda {",
                "  enabled = true",
                "  useMicromamba = true",
                f"  cacheDir = {_groovy_string(cache_dir)}",
                "}",
            ]
            cache_policy = "conda"
        else:
            runtime_block_lines = [
                f"{container_runtime} {{",
                "  enabled = true",
                "}",
            ]
            cache_policy = "container"
    return _ProfileResolution(
        profile_kind=profile_kind,
        executor=executor,
        packaging_mode=packaging_mode,
        container_runtime=container_runtime,
        work_dir=work_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        runtime_block_name=runtime_block_name,
        runtime_block_lines=runtime_block_lines,
        cache_policy=cache_policy,
    )


def _validate_graph(spec: WorkflowSpec, descriptors_by_node: dict[str, dict[str, Any]]) -> list[str]:
    node_ids = {node.node_id for node in spec.nodes}
    edge_targets: dict[tuple[str, str], list[str]] = {}
    sorter = TopologicalSorter()
    for node in spec.nodes:
        sorter.add(node.node_id)
    for edge in spec.edges:
        if edge.source_node_id not in node_ids:
            raise RuntimeError(f"workflow edge {edge.edge_id} 引用了不存在的 source_node_id: {edge.source_node_id}")
        if edge.target_node_id not in node_ids:
            raise RuntimeError(f"workflow edge {edge.edge_id} 引用了不存在的 target_node_id: {edge.target_node_id}")
        if edge.source_node_id == edge.target_node_id:
            raise RuntimeError(f"workflow edge {edge.edge_id} 不允许自环")
        sorter.add(edge.target_node_id, edge.source_node_id)
        key = (edge.target_node_id, edge.input_name)
        edge_targets.setdefault(key, []).append(edge.edge_id)
        descriptor = descriptors_by_node[edge.source_node_id]
        outputs = {
            str(item.get("name") or "").strip()
            for item in descriptor.get("outputs", [])
            if isinstance(item, dict)
        }
        if edge.output_name and edge.output_name not in outputs:
            raise RuntimeError(
                f"workflow edge {edge.edge_id} 引用了 {edge.source_node_id} 不存在的 output: {edge.output_name}"
            )
    duplicated_inputs = [key for key, edge_ids in edge_targets.items() if key[1] and len(edge_ids) > 1]
    if duplicated_inputs:
        details = ", ".join(f"{node_id}.{input_name}" for node_id, input_name in duplicated_inputs)
        raise RuntimeError(f"workflow graph 存在重复输入连接: {details}")
    try:
        return list(sorter.static_order())
    except CycleError as exc:
        cycle = ", ".join(str(item) for item in exc.args[1] or [])
        raise RuntimeError(f"workflow graph 存在循环依赖: {cycle}") from exc


def _resolve_tool_specs(spec: WorkflowSpec, plugin_registry: Any) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for node in spec.nodes:
        descriptor = plugin_registry.get_descriptor(node.tool_id)
        if not isinstance(descriptor, dict) or not descriptor:
            raise RuntimeError(f"插件描述符无效: {node.tool_id}")
        _reject_legacy_plugin_format(descriptor)
        resolved[node.node_id] = descriptor
    return resolved


def _render_process_block(
    *,
    spec: WorkflowSpec,
    node: Any,
    descriptor: dict[str, Any],
    launch: LaunchSpec,
    sample_id: str,
    source_inputs: dict[str, str],
) -> _CompiledNode:
    process_name = _sanitize_identifier(node.node_id, prefix="process")
    emit_names: dict[str, str] = {}
    input_names: list[str] = []
    runtime = _resolve_runtime(descriptor, launch)
    raw_inputs = [item for item in descriptor.get("inputs", []) if isinstance(item, dict)]
    raw_outputs = [item for item in descriptor.get("outputs", []) if isinstance(item, dict)]
    merged_params = {**(launch.params or {}), **(node.params or {})}
    input_context: dict[str, str] = {}
    provided_inputs = {edge.input_name for edge in spec.edges if edge.target_node_id == node.node_id and edge.input_name}
    for input_def in raw_inputs:
        input_name = str(input_def.get("name") or "").strip()
        if not input_name:
            continue
        input_names.append(input_name)
        is_required = bool(input_def.get("required"))
        if is_required or input_name in provided_inputs or bool(source_inputs.get(input_name)):
            input_context[input_name] = f"${{{input_name}}}"
        else:
            input_context[input_name] = ""
    descriptor_for_render = copy.deepcopy(descriptor)
    descriptor_for_render["conda_env"] = ""
    output_paths = CommandBuilder.resolve_output_paths(
        descriptor_for_render,
        output_dir="results",
        sample_id=sample_id,
    )
    render_params = CommandBuilder.merge_defaults(descriptor_for_render, merged_params)
    render_params.update(output_paths)
    command = CommandBuilder.build(
        descriptor_for_render,
        parameters=render_params,
        input_paths=input_context,
        output_dir="results",
        sample_id=sample_id,
        database_paths={
            str(item.get("param_name") or "").strip(): str(merged_params.get(str(item.get("param_name") or "").strip()) or "").strip()
            for item in descriptor_for_render.get("databases", [])
            if isinstance(item, dict) and str(item.get("param_name") or "").strip()
        },
        conda_executable="conda",
    )
    while "\\ \\" in command:
        command = command.replace("\\ \\", "\\")
    lines = [f"process {process_name} {{", "  tag { params.run_name ?: 'adhoc-run' }"]
    if launch.profile.output_dir:
        lines.append(
            f"  publishDir \"${{params.output_dir}}/{process_name}\", mode: 'copy', overwrite: true"
        )
    if launch.profile.packaging_mode == "container":
        lines.append(f"  container {_groovy_string(runtime.container_ref)}")
    else:
        lines.append(f"  conda {_groovy_string(runtime.conda_spec)}")
    if runtime.cpus:
        lines.append(f"  cpus {runtime.cpus}")
    if runtime.memory:
        lines.append(f"  memory {_groovy_string(runtime.memory)}")
    if runtime.time_limit:
        lines.append(f"  time {_groovy_string(runtime.time_limit)}")
    lines.extend(["", "  input:"])
    if input_names:
        for input_name in input_names:
            lines.append(f"    val {input_name}")
    else:
        lines.append("    val trigger")
    lines.extend(["", "  output:"])
    if raw_outputs:
        for output_def in raw_outputs:
            output_name = str(output_def.get("name") or "").strip()
            if not output_name:
                continue
            emit_name = _sanitize_identifier(output_name, prefix="output")
            emit_names[output_name] = emit_name
            resolved_path = output_paths.get(output_name, "")
            if not resolved_path:
                raise RuntimeError(f"插件 {descriptor.get('id')} output {output_name} 缺少可解析 pattern")
            lines.append(f"    path {_groovy_string(resolved_path)}, emit: {emit_name}")
    else:
        fallback_name = "process_complete.txt"
        emit_names["done"] = "done"
        command = f"mkdir -p results\n{command}\nprintf 'done\\n' > {fallback_name}\n"
        lines.append(f"    path {_groovy_string(fallback_name)}, emit: done")
    script_body = command if command.endswith("\n") else f"{command}\n"
    lines.extend(["", "  script:", '  """', "  mkdir -p results"])
    lines.extend(f"  {line}" for line in script_body.splitlines())
    lines.extend(['  """', "}"])
    return _CompiledNode(
        node_id=node.node_id,
        process_name=process_name,
        emit_names=emit_names,
        input_names=input_names,
        process_block="\n".join(lines),
    )


def _render_workflow_graph(
    spec: WorkflowSpec,
    compiled_nodes: dict[str, _CompiledNode],
    descriptors_by_node: dict[str, dict[str, Any]],
    launch: LaunchSpec,
) -> str:
    workflow_lines = [
        "def workflowInput(nodeId, inputName) {",
        "  def root = params.inputs instanceof Map ? params.inputs : [:]",
        "  def nodeInputs = root[nodeId] instanceof Map ? root[nodeId] : [:]",
        "  return nodeInputs[inputName] ?: ''",
        "}",
        "",
        "workflow {",
    ]
    edge_map = {
        (edge.target_node_id, edge.input_name): edge
        for edge in spec.edges
        if edge.input_name
    }
    topo_order = _validate_graph(spec, descriptors_by_node)
    nodes_by_id = {node.node_id: node for node in spec.nodes}
    for node_id in topo_order:
        node = nodes_by_id[node_id]
        compiled = compiled_nodes[node_id]
        descriptor = descriptors_by_node[node_id]
        call_args: list[str] = []
        for input_def in descriptor.get("inputs", []):
            if not isinstance(input_def, dict):
                continue
            input_name = str(input_def.get("name") or "").strip()
            if not input_name:
                continue
            edge = edge_map.get((node.node_id, input_name))
            if edge is not None:
                source = compiled_nodes[edge.source_node_id]
                output_name = edge.output_name or next(iter(source.emit_names.keys()), "")
                emit_name = source.emit_names.get(output_name)
                if not emit_name:
                    raise RuntimeError(
                        f"workflow edge {edge.edge_id} 无法从 {edge.source_node_id} 解析 output: {output_name or '<default>'}"
                    )
                call_args.append(f"{source.process_name}.out.{emit_name}")
            else:
                call_args.append(f"workflowInput('{node.node_id}', '{input_name}')")
        if not call_args:
            call_args.append("params.run_name ?: 'trigger'")
        workflow_lines.append(f"  {compiled.process_name}({', '.join(call_args)})")
    workflow_lines.append("}")
    return "\n".join(workflow_lines)


def _build_nextflow_config(launch: LaunchSpec, *, bundle_id: str, profile: _ProfileResolution) -> str:
    lines = [
        "# Base Nextflow config generated by the workflow compiler",
        "manifest {",
        "  name = 'h2ometa-generated-workflow'",
        "}",
        "",
        "params {",
        "  run_name = 'h2ometa-run'",
        "  inputs = [:]",
        f"  output_dir = {_groovy_string(profile.output_dir)}",
        f"  work_dir = {_groovy_string(profile.work_dir)}",
        f"  cache_dir = {_groovy_string(profile.cache_dir)}",
        f"  profile_id = {_groovy_string(launch.profile.profile_id)}",
        f"  profile_kind = {_groovy_string(profile.profile_kind)}",
        f"  executor = {_groovy_string(profile.executor)}",
        f"  packaging_mode = {_groovy_string(profile.packaging_mode)}",
        f"  container_runtime = {_groovy_string(profile.container_runtime)}",
        "}",
        "",
        "bioflow {",
        f"  bundle_id = {_groovy_string(bundle_id)}",
        f"  profile_id = {_groovy_string(launch.profile.profile_id)}",
        f"  profile_kind = {_groovy_string(profile.profile_kind)}",
        f"  server_id = {_groovy_string(launch.profile.server_id)}",
        f"  executor = {_groovy_string(profile.executor)}",
        f"  packaging_mode = {_groovy_string(profile.packaging_mode)}",
        f"  container_runtime = {_groovy_string(profile.container_runtime)}",
        f"  work_dir = {_groovy_string(profile.work_dir)}",
        f"  output_dir = {_groovy_string(profile.output_dir)}",
        f"  cache_dir = {_groovy_string(profile.cache_dir)}",
        f"  runtime_block_name = {_groovy_string(profile.runtime_block_name)}",
        f"  cache_policy = {_groovy_string(profile.cache_policy)}",
        "}",
        "",
        "process {",
        "  errorStrategy = 'terminate'",
        "}",
    ]
    return "\n".join(lines) + "\n"


def _build_resolved_nextflow_config(
    launch: LaunchSpec,
    *,
    bundle_id: str,
    profile: _ProfileResolution,
) -> str:
    lines = [
        "# Resolved Nextflow config generated for the selected profile",
        f"process.executor = {_groovy_string(profile.executor)}",
        f"workDir = {_groovy_string(profile.work_dir)}",
        f"params.output_dir = {_groovy_string(profile.output_dir)}",
        f"params.work_dir = {_groovy_string(profile.work_dir)}",
        f"params.cache_dir = {_groovy_string(profile.cache_dir)}",
        "",
        "bioflow {",
        f"  bundle_id = {_groovy_string(bundle_id)}",
        f"  profile_id = {_groovy_string(launch.profile.profile_id)}",
        f"  profile_kind = {_groovy_string(profile.profile_kind)}",
        f"  server_id = {_groovy_string(launch.profile.server_id)}",
        f"  executor = {_groovy_string(profile.executor)}",
        f"  packaging_mode = {_groovy_string(profile.packaging_mode)}",
        f"  container_runtime = {_groovy_string(profile.container_runtime)}",
        f"  work_dir = {_groovy_string(profile.work_dir)}",
        f"  output_dir = {_groovy_string(profile.output_dir)}",
        f"  cache_dir = {_groovy_string(profile.cache_dir)}",
        f"  runtime_block_name = {_groovy_string(profile.runtime_block_name)}",
        f"  cache_policy = {_groovy_string(profile.cache_policy)}",
        "}",
        "",
        "process {",
        "  errorStrategy = 'terminate'",
        "}",
    ]
    if profile.runtime_block_lines:
        lines.extend([""] + profile.runtime_block_lines)
    return "\n".join(lines) + "\n"


def _source_input_mapping(spec: WorkflowSpec, launch: LaunchSpec, descriptors_by_node: dict[str, dict[str, Any]]) -> dict[str, dict[str, str]]:
    provided = launch.params.get("inputs", {}) if isinstance(launch.params.get("inputs"), dict) else {}
    mapping: dict[str, dict[str, str]] = {}
    refs_iter = iter(launch.data_refs)
    target_inputs = {
        (edge.target_node_id, edge.input_name)
        for edge in spec.edges
        if edge.input_name
    }
    for node in spec.nodes:
        node_mapping: dict[str, str] = {}
        provided_node = provided.get(node.node_id, {}) if isinstance(provided.get(node.node_id), dict) else {}
        for input_def in descriptors_by_node[node.node_id].get("inputs", []):
            if not isinstance(input_def, dict):
                continue
            input_name = str(input_def.get("name") or "").strip()
            if not input_name or (node.node_id, input_name) in target_inputs:
                continue
            explicit = str(provided_node.get(input_name) or "").strip()
            if explicit:
                node_mapping[input_name] = explicit
                continue
            next_ref = str(next(refs_iter, "") or "").strip()
            if next_ref:
                node_mapping[input_name] = next_ref
            else:
                node_mapping[input_name] = ""
        if node_mapping:
            mapping[node.node_id] = node_mapping
    return mapping


def compile_workflow_bundle(spec: WorkflowSpec, launch: LaunchSpec, *, plugin_registry: Any | None = None) -> dict[str, Any]:
    if plugin_registry is None:
        raise RuntimeError("plugin_registry is required for workflow compilation")
    bundle_id = f"bundle_{uuid.uuid4().hex[:12]}"
    profile = _profile_resolution(launch)
    descriptors_by_node = _resolve_tool_specs(spec, plugin_registry)
    sample_id = _sample_id_for_bundle(spec, launch)
    source_inputs = _source_input_mapping(spec, launch, descriptors_by_node)
    compiled_nodes = {
        node.node_id: _render_process_block(
            spec=spec,
            node=node,
            descriptor=descriptors_by_node[node.node_id],
            launch=launch,
            sample_id=sample_id,
            source_inputs=source_inputs.get(node.node_id, {}),
        )
        for node in spec.nodes
    }
    main_nf = "\n\n".join(
        [node.process_block for node in compiled_nodes.values()]
        + [_render_workflow_graph(spec, compiled_nodes, descriptors_by_node, launch)]
    )
    config_text = _build_nextflow_config(launch, bundle_id=bundle_id, profile=profile)
    resolved_config_text = _build_resolved_nextflow_config(launch, bundle_id=bundle_id, profile=profile)
    params_payload = dict(launch.params or {})
    params_payload["inputs"] = source_inputs
    params_payload.setdefault("sample_id", sample_id)
    params_yaml = _yaml_dump(params_payload)
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
        "server_id": launch.profile.server_id,
        "profile_kind": launch.profile.profile_kind,
        "executor": launch.profile.executor,
        "packaging_mode": launch.profile.packaging_mode,
        "container_runtime": launch.profile.container_runtime,
        "work_dir": profile.work_dir,
        "output_dir": profile.output_dir,
        "cache_dir": profile.cache_dir,
        "resolved_profile": {
            "profile_kind": profile.profile_kind,
            "executor": profile.executor,
            "packaging_mode": profile.packaging_mode,
            "container_runtime": profile.container_runtime,
            "work_dir": profile.work_dir,
            "output_dir": profile.output_dir,
            "cache_dir": profile.cache_dir,
            "runtime_block_name": profile.runtime_block_name,
            "cache_policy": profile.cache_policy,
        },
        "config": {
            "base_config": "nextflow.config",
            "resolved_config": "resolved.config",
            "resolved_is_profile_specific": True,
            "profile_kind": profile.profile_kind,
            "executor": profile.executor,
            "packaging_mode": profile.packaging_mode,
            "container_runtime": profile.container_runtime,
            "work_dir": profile.work_dir,
            "output_dir": profile.output_dir,
            "cache_dir": profile.cache_dir,
            "runtime_block_name": profile.runtime_block_name,
            "cache_policy": profile.cache_policy,
        },
        "runtime_policy": {
            "work_dir": profile.work_dir,
            "output_dir": profile.output_dir,
            "cache_dir": profile.cache_dir,
            "executor": profile.executor,
            "packaging_mode": profile.packaging_mode,
            "runtime_block_name": profile.runtime_block_name,
            "cache_policy": profile.cache_policy,
        },
        "node_count": len(spec.nodes),
        "edge_count": len(spec.edges),
        "resume": launch.resume,
        "data_refs": launch.data_refs,
        "source_inputs": params_payload["inputs"],
        "tools": {
            node.node_id: {
                "tool_id": node.tool_id,
                "descriptor_path": str(descriptors_by_node[node.node_id].get("_yaml_path") or ""),
            }
            for node in spec.nodes
        },
    }
    files = {
        "main.nf": main_nf,
        "nextflow.config": config_text,
        "resolved.config": resolved_config_text,
        "params/run.yaml": params_yaml + ("\n" if params_yaml else ""),
        "params.schema.json": json.dumps(params_schema, ensure_ascii=False, indent=2) + "\n",
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "docs/inputs.json": json.dumps(params_payload["inputs"], ensure_ascii=False, indent=2) + "\n",
    }
    return {
        "bundle_id": bundle_id,
        "files": files,
        "manifest": manifest,
        "bundle_root": str(Path(bundle_id)),
    }
