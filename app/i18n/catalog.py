"""English overlays for node metadata, ports, params, and common UI-facing backend strings."""

from __future__ import annotations

from typing import Any

from app.i18n.locale import is_en, pick

# Node-level description_en (label_en already on NodeSpec)
DESCRIPTION_EN: dict[str, str] = {
    "file_input": "Load a local CSV / Excel / JSON file as a table",
    "ai_clean": "Describe cleaning intent in natural language; AI generates pandas code",
    "filter": "Filter rows by expression or natural language; outputs matched and unmatched tables",
    "join": "Join two tables by key (inner / left / right / outer / cross)",
    "groupby": "Group by columns and aggregate (sum / mean / count / …)",
    "ai_analyze": "Produce descriptive stats and analysis summaries via AI",
    "ai_chart": "Let AI choose a chart type and build a Plotly figure",
    "ai_report": "Compose stats, charts, and tables into a Markdown report",
    "export": "Export the report as Markdown or PDF",
    "preview": "Debug helper to inspect any port’s data",
}

COMMON_PARAM_EN: dict[str, str] = {
    "columns": "Columns",
    "intent": "Intent",
    "model": "AI model",
    "path": "Path",
    "format": "Export format",
    "expression": "Filter expression",
    "ai_intent": "Natural-language filter",
    "x": "X axis",
    "y": "Y axis",
    "color": "Color",
    "sample_policy": "Sampling policy",
    "sample_n": "Sample size",
    "limit": "Row limit",
    "left_on": "Left join keys",
    "right_on": "Right join keys",
    "how": "Join type",
    "suffixes": "Overlap suffixes (left,right)",
    "validate": "Key relationship check",
    "indicator": "Add _merge indicator column",
    "by": "Group-by columns",
    "values": "Value columns",
    "aggs": "Aggregations",
    "dropna": "Drop NA group keys",
}

# Per-node overrides when the common label is too generic
PARAM_EN_OVERRIDE: dict[tuple[str, str], str] = {
    ("ai_clean", "columns"): "Focus columns",
    ("ai_clean", "intent"): "Cleaning intent",
    ("ai_analyze", "columns"): "Analysis columns",
    ("ai_analyze", "intent"): "Analysis intent",
    ("ai_chart", "columns"): "Focus columns",
    ("ai_chart", "intent"): "Chart intent",
    ("ai_report", "columns"): "Report columns",
    ("ai_report", "intent"): "Report intent",
    ("filter", "columns"): "Involved columns",
    ("export", "path"): "Output path",
    ("file_input", "path"): "File path",
}

COMMON_PORT_EN: dict[str, str] = {
    "table_in": "Table",
    "table_out": "Table",
    "left": "Left table",
    "right": "Right table",
    "matched": "Matched",
    "unmatched": "Unmatched",
    "stats_in": "Stats",
    "stats_out": "Stats",
    "figure_in": "Figure",
    "figure_out": "Figure",
    "text_out": "Report",
    "file_out": "File",
    "input": "Input",
}

CATEGORY_EN: dict[str, str] = {
    "input": "input",
    "clean": "clean",
    "transform": "transform",
    "analyze": "analyze",
    "visualize": "visualize",
    "report": "report",
    "output": "output",
    "custom": "custom",
}

# Backend messages shown in toasts / precheck (code -> en)
MESSAGE_EN: dict[str, tuple[str, str]] = {
    # (message, fix_hint) — zh remains in Message catalog; en overlay by code
    "empty_result": ("Cleaning produced an empty table", "Relax cleaning conditions"),
    "missing_column": ("Column “{col}” is missing upstream", "Reselect columns"),
    "bad_expression": ("Invalid filter expression: {err}", "Check column names and syntax"),
    "bad_join": ("Join failed: {err}", "Check join keys, join type, and uniqueness validation"),
    "bad_groupby": ("GroupBy failed: {err}", "Check group-by columns and aggregations"),
    "export_failed": ("Export failed: {err}", "Check path and format"),
    "missing_file": ("Input file does not exist", "Reselect the file"),
    "required_param": ("{label}: missing “{field}”", "Select the node and fill “{field}”"),
    "missing_input": ("Input port {port} is not connected", "Connect a compatible upstream output"),
    "api_key_missing": ("AI nodes require an API key", "Configure the ZenMux API key in Settings"),
}

REPORT_SECTION_EN: dict[str, str] = {
    "关键指标": "Key metrics",
    "分析说明": "Analysis",
    "明细数据": "Details",
    "数据概览": "Data overview",
    "统计摘要": "Statistical summary",
    "图表": "Chart",
    "分析报告": "Analysis report",
    "数据分析报告": "Data analysis report",
}


def param_label(node_type: str, key: str, zh_label: str, locale: str | None) -> str:
    if not is_en(locale):
        return zh_label
    return PARAM_EN_OVERRIDE.get((node_type, key)) or COMMON_PARAM_EN.get(key) or zh_label


def port_label(port_id: str, zh_label: str, locale: str | None) -> str:
    if not is_en(locale):
        return zh_label or port_id
    return COMMON_PORT_EN.get(port_id) or zh_label or port_id


def node_description(node_type: str, zh: str, locale: str | None) -> str:
    return pick(locale, zh, DESCRIPTION_EN.get(node_type, zh))


def localize_params_schema(
    node_type: str, params_schema: list[dict[str, Any]], locale: str | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for field in params_schema:
        item = dict(field)
        item["label"] = param_label(node_type, str(item.get("key", "")), str(item.get("label", "")), locale)
        # Keep original for debugging / future editors
        if is_en(locale):
            item["label_zh"] = field.get("label")
        out.append(item)
    return out


def localize_ports(ports: list[Any], locale: str | None) -> list[dict[str, Any]]:
    result = []
    for p in ports:
        pub = p.public() if hasattr(p, "public") else dict(p)
        pub = dict(pub)
        pub["label"] = port_label(str(pub.get("id", "")), str(pub.get("label", "")), locale)
        result.append(pub)
    return result
