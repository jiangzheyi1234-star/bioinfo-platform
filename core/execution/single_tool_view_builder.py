"""Helpers for building standard single-tool result views."""

from __future__ import annotations

from typing import Any

from core.execution.single_tool_view_schema import (
    HeroInfo,
    ProvenanceInfo,
    SingleToolView,
    SummaryItem,
    TableView,
    ViewStatus,
)


def build_single_tool_view(
    *,
    feature_id: str,
    tool_ids: list[str],
    title: str,
    description: str,
    status: dict[str, Any],
    summary: list[dict[str, Any]] | None = None,
    charts: list[dict[str, Any]] | None = None,
    columns: list[dict[str, str]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    parameters: list[dict[str, str]] | None = None,
    table_title: str = "",
    table_subtitle: str = "",
    sample_name: str = "",
    execution_id: str = "",
    updated_at: str = "",
    tool_version: str = "",
    remote_result_dir: str = "",
    command_preview: str = "",
) -> dict[str, Any]:
    status_model = ViewStatus(
        state=str(status.get("state", "") or ""),
        label=str(status.get("label", "") or ""),
        detail=str(status.get("detail", "") or ""),
    )
    summary_models = [
        SummaryItem(
            label=str(item.get("label", "") or ""),
            value=str(item.get("value", "") or ""),
            tone=str(item.get("tone", "default") or "default"),
        )
        for item in (summary or [])
    ]
    table_model = TableView(
        title=table_title,
        subtitle=table_subtitle,
        columns=list(columns or []),
        rows=list(rows or []),
    )
    view = SingleToolView(
        feature_id=feature_id,
        tool_ids=list(tool_ids or [feature_id]),
        title=title,
        description=description,
        status=status_model,
        hero=HeroInfo(
            sample_name=sample_name,
            execution_id=execution_id,
            updated_at=updated_at,
            primary_action="view_result",
        ),
        summary=summary_models,
        charts=list(charts or []),
        table=table_model,
        artifacts=list(artifacts or []),
        provenance=ProvenanceInfo(
            parameters=list(parameters or []),
            tool_version=tool_version,
            remote_result_dir=remote_result_dir,
            command_preview=command_preview,
        ),
        parameters=list(parameters or []),
        table_title=table_title,
        table_subtitle=table_subtitle,
        columns=list(columns or []),
        rows=list(rows or []),
    )
    return view.to_dict()


def build_artifact_result_view(
    *,
    feature_id: str,
    tool_ids: list[str],
    title: str,
    description: str,
    status: dict[str, Any],
    artifacts: list[dict[str, Any]],
    parameters: list[dict[str, str]] | None = None,
    sample_name: str = "",
    execution_id: str = "",
    updated_at: str = "",
    tool_version: str = "",
    remote_result_dir: str = "",
) -> dict[str, Any]:
    summary = [
        {
            "label": "结果文件",
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
        tool_ids=tool_ids,
        title=title,
        description=description,
        status=status,
        summary=summary,
        artifacts=artifacts,
        parameters=parameters,
        table_title="结果文件",
        table_subtitle="当前工具未声明结构化结果表，以下展示已同步产物。",
        sample_name=sample_name,
        execution_id=execution_id,
        updated_at=updated_at,
        tool_version=tool_version,
        remote_result_dir=remote_result_dir,
    )
