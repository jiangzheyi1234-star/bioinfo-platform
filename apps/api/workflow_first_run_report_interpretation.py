"""Report interpretation and trust assertions for First Successful Run."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


FIRST_RUN_REPORT_INTERPRETATION_SCHEMA_VERSION = "h2ometa.first-run.report-interpretation.v1"
FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED = "FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED"
FIRST_RUN_REPORT_PREVIEW_REQUIRED = "FIRST_RUN_REPORT_PREVIEW_REQUIRED"
FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED = "FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED"

MOVING_PICTURES_REPORT_OUTPUTS = (
    {
        "name": "summary.tsv",
        "key": "summary",
        "label": "Per-sample demultiplexed summary",
        "kind": "table",
        "interpretation": "Sample-level read counts and observed feature totals for the official tutorial dataset.",
    },
    {
        "name": "qc-summary.tsv",
        "key": "qc_summary",
        "label": "Quality-control summary",
        "kind": "table",
        "interpretation": "Aggregate read matching, pass-rate, and feature-table readiness metrics.",
    },
    {
        "name": "feature-table.tsv",
        "key": "feature_table",
        "label": "Feature table",
        "kind": "table",
        "interpretation": "The first successful run produced the expected ASV feature table artifact.",
    },
    {
        "name": "run-report.html",
        "key": "report",
        "label": "Human-readable report",
        "kind": "report",
        "interpretation": "Portable HTML report for non-technical review and handoff.",
    },
)
MOVING_PICTURES_REPORT_OUTPUT_NAMES = {str(item["name"]) for item in MOVING_PICTURES_REPORT_OUTPUTS}
MOVING_PICTURES_OUTPUT_KEYS_TO_NAMES = {str(item["key"]): str(item["name"]) for item in MOVING_PICTURES_REPORT_OUTPUTS}
MOVING_PICTURES_PREVIEW_OUTPUT_NAMES = {"summary.tsv", "qc-summary.tsv"}
MOVING_PICTURES_PREVIEW_OUTPUT_ORDER = ("summary.tsv", "qc-summary.tsv")


class FirstRunReportInterpretationUnavailableError(ValueError):
    pass


def build_first_run_report_interpretation(
    *,
    artifacts: list[dict[str, Any]],
    report_previews: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing_outputs = missing_expected_output_names(artifacts)
    if missing_outputs:
        raise _unavailable(
            FIRST_RUN_EXPECTED_OUTPUTS_REQUIRED,
            f"expected Moving Pictures outputs missing: {', '.join(missing_outputs)}",
        )
    summary_columns, summary_rows, summary_truncated = _required_table_preview(
        report_previews.get("summary.tsv"),
        "summary.tsv",
        required_columns=("passed_reads", "unique_features"),
    )
    qc_columns, qc_rows, qc_truncated = _required_table_preview(
        report_previews.get("qc-summary.tsv"),
        "qc-summary.tsv",
        required_columns=("metric", "value"),
    )
    summary_metrics = _summary_metrics(summary_columns, summary_rows)
    qc_metrics = _qc_metrics(qc_columns, qc_rows)
    _assert_report_trust_assertions(summary_metrics, qc_metrics)
    return {
        "schemaVersion": FIRST_RUN_REPORT_INTERPRETATION_SCHEMA_VERSION,
        "status": "ready",
        "summary": "Moving Pictures 16S first run completed with the expected report, summary, QC, and feature-table artifacts.",
        "outputs": _report_output_items(artifacts),
        "metrics": [*summary_metrics, *qc_metrics],
        "previewSources": [
            _preview_source(report_previews["summary.tsv"], "summary.tsv", summary_truncated),
            _preview_source(report_previews["qc-summary.tsv"], "qc-summary.tsv", qc_truncated),
        ],
        "redaction": {
            "rawPathsExposed": False,
            "storageUrisExposed": False,
            "previewRowsEmbedded": False,
            "policy": "metrics-only",
        },
    }


def artifact_for_output(artifacts: list[dict[str, Any]], output_name: str) -> dict[str, Any] | None:
    return next((artifact for artifact in artifacts if artifact_output_name(artifact) == output_name), None)


def missing_expected_output_names(artifacts: list[dict[str, Any]]) -> list[str]:
    present = {artifact_output_name(artifact) for artifact in artifacts}
    return sorted(name for name in MOVING_PICTURES_REPORT_OUTPUT_NAMES if name not in present)


def artifact_output_name(item: dict[str, Any]) -> str:
    for key in ("displayName", "name", "filename"):
        label = str(item.get(key) or "").strip()
        if label in MOVING_PICTURES_REPORT_OUTPUT_NAMES:
            return label
    artifact_key = str(item.get("artifactKey") or item.get("key") or "").strip()
    if artifact_key in MOVING_PICTURES_OUTPUT_KEYS_TO_NAMES:
        return MOVING_PICTURES_OUTPUT_KEYS_TO_NAMES[artifact_key]
    basename = PurePosixPath(str(item.get("path") or item.get("storageUri") or "")).name
    return basename if basename in MOVING_PICTURES_REPORT_OUTPUT_NAMES else ""


def _report_output_items(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {
        output_name: artifact
        for artifact in artifacts
        if (output_name := artifact_output_name(artifact)) in MOVING_PICTURES_REPORT_OUTPUT_NAMES
    }
    items = []
    for output in MOVING_PICTURES_REPORT_OUTPUTS:
        artifact = by_name[str(output["name"])]
        items.append(
            _compact(
                {
                    "name": output["name"],
                    "key": output["key"],
                    "label": output["label"],
                    "kind": output["kind"],
                    "present": True,
                    "artifactId": artifact.get("artifactId"),
                    "mimeType": artifact.get("mimeType"),
                    "sizeBytes": artifact.get("sizeBytes"),
                    "sha256": artifact.get("sha256"),
                    "interpretation": output["interpretation"],
                }
            )
        )
    return items


def _required_table_preview(
    preview: dict[str, Any] | None,
    output_name: str,
    *,
    required_columns: tuple[str, ...],
) -> tuple[list[str], list[list[str]], bool]:
    if not isinstance(preview, dict):
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{output_name} preview is missing")
    preview_data = preview.get("preview") if isinstance(preview.get("preview"), dict) else {}
    if preview_data.get("kind") != "table":
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{output_name} preview is not a table")
    columns = [str(item) for item in preview_data.get("columns") or []]
    rows = [[str(cell) for cell in row] for row in (preview_data.get("rows") or []) if isinstance(row, list)]
    if not columns or not rows:
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{output_name} table preview is empty")
    missing_columns = [column for column in required_columns if column not in columns]
    if missing_columns:
        raise _unavailable(
            FIRST_RUN_REPORT_PREVIEW_REQUIRED,
            f"{output_name} preview missing columns: {', '.join(missing_columns)}",
        )
    return columns, rows, bool(preview_data.get("truncated"))


def _summary_metrics(columns: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    passed_reads = _sum_numeric_column(rows, columns.index("passed_reads"), "summary.tsv:passed_reads")
    unique_features = _sum_numeric_column(rows, columns.index("unique_features"), "summary.tsv:unique_features")
    return [
        _metric("sample_count", "samples", len(rows), "summary.tsv"),
        _metric("passed_reads_total", "passed reads", passed_reads, "summary.tsv"),
        _metric("unique_features_sample_sum", "unique features", unique_features, "summary.tsv"),
    ]


def _qc_metrics(columns: list[str], rows: list[list[str]]) -> list[dict[str, Any]]:
    metric_index = columns.index("metric")
    value_index = columns.index("value")
    preferred = {"total_pairs", "matched_reads", "passed_reads", "samples_with_reads", "features"}
    metrics = []
    for row in rows:
        metric_id = str(row[metric_index] if metric_index < len(row) else "").strip()
        if metric_id not in preferred:
            continue
        value = _numeric_value(row[value_index] if value_index < len(row) else "", f"qc-summary.tsv:{metric_id}")
        metrics.append(_metric(f"qc_{metric_id}", metric_id.replace("_", " "), value, "qc-summary.tsv"))
    return metrics


def _assert_report_trust_assertions(
    summary_metrics: list[dict[str, Any]],
    qc_metrics: list[dict[str, Any]],
) -> None:
    metrics = {str(item.get("metricId") or ""): item.get("value") for item in [*summary_metrics, *qc_metrics]}
    sample_count = _metric_number(metrics, "sample_count")
    passed_reads_total = _metric_number(metrics, "passed_reads_total")
    unique_features_total = _metric_number(metrics, "unique_features_sample_sum")
    if sample_count < 2:
        raise _unavailable(
            FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
            "summary.tsv must contain at least two Moving Pictures samples",
        )
    if passed_reads_total <= 0:
        raise _unavailable(
            FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
            "summary.tsv passed_reads total must be greater than zero",
        )
    if unique_features_total <= 0:
        raise _unavailable(
            FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
            "summary.tsv unique_features total must be greater than zero",
        )
    required_qc = {
        "qc_passed_reads": passed_reads_total,
        "qc_samples_with_reads": sample_count,
        "qc_features": unique_features_total,
    }
    for metric_id, expected in required_qc.items():
        if metric_id not in metrics:
            raise _unavailable(
                FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
                f"qc-summary.tsv metric {metric_id.removeprefix('qc_')} is required",
            )
        actual = _metric_number(metrics, metric_id)
        if actual != expected:
            raise _unavailable(
                FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED,
                f"qc-summary.tsv {metric_id.removeprefix('qc_')}={_format_number(actual)} does not match summary.tsv {_format_number(expected)}",
            )


def _metric_number(metrics: dict[str, Any], metric_id: str) -> int | float:
    value = metrics.get(metric_id)
    if not isinstance(value, int | float):
        raise _unavailable(FIRST_RUN_REPORT_TRUST_ASSERTIONS_FAILED, f"report metric {metric_id} is required")
    return value


def _metric(metric_id: str, label: str, value: int | float, source: str) -> dict[str, Any]:
    return {
        "metricId": metric_id,
        "label": label,
        "value": value,
        "displayValue": _format_number(value),
        "source": source,
    }


def _sum_numeric_column(rows: list[list[str]], column_index: int, source: str) -> int | float:
    return sum(_numeric_value(row[column_index] if column_index < len(row) else "", source) for row in rows)


def _numeric_value(value: Any, source: str) -> int | float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{source} has an empty numeric value")
    try:
        number = float(text)
    except ValueError as exc:
        raise _unavailable(FIRST_RUN_REPORT_PREVIEW_REQUIRED, f"{source} is not numeric") from exc
    return int(number) if number.is_integer() else number


def _format_number(value: int | float) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _preview_source(preview: dict[str, Any], output_name: str, truncated: bool) -> dict[str, Any]:
    preview_data = preview.get("preview") if isinstance(preview.get("preview"), dict) else {}
    return _compact(
        {
            "outputName": output_name,
            "kind": preview_data.get("kind"),
            "columnCount": len(preview_data.get("columns") or []),
            "rowCount": len(preview_data.get("rows") or []),
            "truncated": truncated,
        }
    )


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _unavailable(code: str, detail: str) -> FirstRunReportInterpretationUnavailableError:
    return FirstRunReportInterpretationUnavailableError(f"{code}: {detail}")
