"""Helpers for building standard single-tool result views."""

from __future__ import annotations

from typing import Any

from core.execution.single_tool_view_schema import (
    HeroInfo,
    ProvenanceInfo,
    SingleToolView,
    SummaryItem,
    TableView,
    ViewSection,
    ViewStatus,
)


def _coerce_status(status: dict[str, Any] | None) -> ViewStatus:
    payload = status or {}
    return ViewStatus(
        state=str(payload.get("state", "") or ""),
        label=str(payload.get("label", "") or ""),
        detail=str(payload.get("detail", "") or ""),
    )


def _coerce_summary(summary: list[dict[str, Any]] | None) -> list[SummaryItem]:
    return [
        SummaryItem(
            label=str(item.get("label", "") or ""),
            value=str(item.get("value", "") or ""),
            tone=str(item.get("tone", "default") or "default"),
        )
        for item in (summary or [])
    ]


def _coerce_table(
    *,
    table: dict[str, Any] | None = None,
) -> TableView:
    payload = table or {}
    return TableView(
        title=str(payload.get("title") or ""),
        subtitle=str(payload.get("subtitle") or ""),
        columns=list(payload.get("columns") or []),
        rows=list(payload.get("rows") or []),
    )


def _coerce_provenance(
    *,
    provenance: dict[str, Any] | None = None,
) -> ProvenanceInfo:
    payload = provenance or {}
    return ProvenanceInfo(
        execution_id=str(payload.get("execution_id") or ""),
        parameters=list(payload.get("parameters") or []),
        tool_version=str(payload.get("tool_version") or ""),
        remote_result_dir=str(payload.get("remote_result_dir") or ""),
        local_result_dir=str(payload.get("local_result_dir") or ""),
        command_preview=str(payload.get("command_preview") or ""),
    )


def build_view_section(
    *,
    section_id: str,
    title: str,
    archetype: str,
    summary: list[dict[str, Any]] | None = None,
    charts: list[dict[str, Any]] | None = None,
    table: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section = ViewSection(
        section_id=section_id,
        title=title,
        archetype=archetype,
        summary=_coerce_summary(summary),
        charts=list(charts or []),
        table=_coerce_table(table=table),
        artifacts=list(artifacts or []),
        provenance=_coerce_provenance(provenance=provenance),
    )
    return section.to_dict()


def section_from_view(
    view: dict[str, Any],
    *,
    section_id: str,
    title: str | None = None,
    archetype: str | None = None,
) -> dict[str, Any]:
    table_payload = view.get("table") if isinstance(view.get("table"), dict) else {}
    return build_view_section(
        section_id=section_id,
        title=str(title or view.get("title") or section_id),
        archetype=str(archetype or view.get("archetype") or ""),
        summary=list(view.get("summary") or []),
        charts=list(view.get("charts") or []),
        table={
            "title": str(table_payload.get("title") or ""),
            "subtitle": str(table_payload.get("subtitle") or ""),
            "columns": list(table_payload.get("columns") or []),
            "rows": list(table_payload.get("rows") or []),
        },
        artifacts=list(view.get("artifacts") or []),
        provenance=dict(view.get("provenance") or {}),
    )


def build_single_tool_view(
    *,
    feature_id: str,
    tool_id: str | None = None,
    archetype: str = "",
    tool_ids: list[str] | None = None,
    title: str,
    description: str,
    status: dict[str, Any],
    summary: list[dict[str, Any]] | None = None,
    charts: list[dict[str, Any]] | None = None,
    table: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    provenance: dict[str, Any] | None = None,
    sections: list[dict[str, Any]] | None = None,
    sample_name: str = "",
    execution_id: str = "",
    updated_at: str = "",
) -> dict[str, Any]:
    normalized_tool_id = str(tool_id or (tool_ids[0] if tool_ids else feature_id) or feature_id)
    table_model = _coerce_table(table=table)
    provenance_model = _coerce_provenance(provenance=provenance)
    section_models = [
        ViewSection(
            section_id=str(item.get("section_id") or ""),
            title=str(item.get("title") or ""),
            archetype=str(item.get("archetype") or ""),
            summary=_coerce_summary(list(item.get("summary") or [])),
            charts=list(item.get("charts") or []),
            table=_coerce_table(table=dict(item.get("table") or {})),
            artifacts=list(item.get("artifacts") or []),
            provenance=_coerce_provenance(provenance=dict(item.get("provenance") or {})),
        )
        for item in (sections or [])
    ]

    view = SingleToolView(
        feature_id=str(feature_id),
        tool_id=normalized_tool_id,
        archetype=str(archetype or ""),
        title=title,
        description=description,
        status=_coerce_status(status),
        hero=HeroInfo(
            sample_name=sample_name,
            execution_id=execution_id,
            updated_at=updated_at,
            primary_action="view_result",
        ),
        summary=_coerce_summary(summary),
        charts=list(charts or []),
        table=table_model,
        artifacts=list(artifacts or []),
        provenance=provenance_model,
        sections=section_models,
        tool_ids=list(tool_ids or [normalized_tool_id]),
    )
    return view.to_dict()


def normalize_result_view(
    view: dict[str, Any],
    *,
    feature_id: str,
    tool_id: str,
    archetype: str,
    title: str | None = None,
    description: str | None = None,
    sample_name: str = "",
    execution_id: str = "",
    updated_at: str = "",
    tool_version: str = "",
    remote_result_dir: str = "",
    local_result_dir: str = "",
    command_preview: str = "",
    sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_sections = sections if sections is not None else list(view.get("sections") or [])
    raw_table = view.get("table") if isinstance(view.get("table"), dict) else {}
    raw_provenance = view.get("provenance") if isinstance(view.get("provenance"), dict) else {}
    charts = list(view.get("charts") or [])

    return build_single_tool_view(
        feature_id=feature_id,
        tool_id=tool_id,
        archetype=archetype,
        tool_ids=list(view.get("tool_ids") or [tool_id]),
        title=str(title or view.get("title") or feature_id),
        description=str(description or view.get("description") or ""),
        status=dict(view.get("status") or {"state": "", "label": "", "detail": ""}),
        summary=list(view.get("summary") or []),
        charts=charts,
        table={
            "title": str(raw_table.get("title") or ""),
            "subtitle": str(raw_table.get("subtitle") or ""),
            "columns": list(raw_table.get("columns") or []),
            "rows": list(raw_table.get("rows") or []),
        },
        artifacts=list(view.get("artifacts") or []),
        provenance={
            "execution_id": str(raw_provenance.get("execution_id") or execution_id or ""),
            "parameters": list(raw_provenance.get("parameters") or []),
            "tool_version": str(raw_provenance.get("tool_version") or tool_version or ""),
            "remote_result_dir": str(raw_provenance.get("remote_result_dir") or remote_result_dir or ""),
            "local_result_dir": str(raw_provenance.get("local_result_dir") or local_result_dir or ""),
            "command_preview": str(raw_provenance.get("command_preview") or command_preview or ""),
        },
        sections=normalized_sections,
        sample_name=str(view.get("hero", {}).get("sample_name") or sample_name or ""),
        execution_id=str(view.get("hero", {}).get("execution_id") or execution_id or ""),
        updated_at=str(view.get("hero", {}).get("updated_at") or updated_at or ""),
    )


def build_artifact_result_view(
    *,
    feature_id: str,
    tool_id: str | None = None,
    archetype: str = "artifact_collection",
    tool_ids: list[str],
    title: str,
    description: str,
    status: dict[str, Any],
    artifacts: list[dict[str, Any]],
    parameters: list[dict[str, Any]] | None = None,
    sample_name: str = "",
    execution_id: str = "",
    updated_at: str = "",
    tool_version: str = "",
    remote_result_dir: str = "",
    local_result_dir: str = "",
) -> dict[str, Any]:
    summary = [
        {
            "label": "已同步文件",
            "value": str(len([item for item in artifacts if item.get("available")])),
            "tone": "primary",
        },
        {
            "label": "总产物数",
            "value": str(len(artifacts)),
            "tone": "info",
        },
    ]
    return build_single_tool_view(
        feature_id=feature_id,
        tool_id=tool_id or feature_id,
        archetype=archetype,
        tool_ids=tool_ids,
        title=title,
        description=description,
        status=status,
        summary=summary,
        table={
            "title": "结果文件",
            "subtitle": "当前工具以结果产物为主，以下展示已同步到本地的文件与目录。",
            "columns": [],
            "rows": [],
        },
        artifacts=artifacts,
        provenance={
            "execution_id": execution_id,
            "parameters": list(parameters or []),
            "tool_version": tool_version,
            "remote_result_dir": remote_result_dir,
            "local_result_dir": local_result_dir,
        },
        sample_name=sample_name,
        execution_id=execution_id,
        updated_at=updated_at,
    )
