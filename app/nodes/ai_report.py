from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.figures import figure_to_png_b64, markdown_chart_block
from app.i18n import pick
from app.registry import MessageCatalog, NodeSpec, Port, param, register
from app.report_format import dataframe_to_md_tables, structured_to_markdown


def _coerce_report_body(raw: Any, *, intent: str, locale: str | None = None) -> str:
    """Normalize sandbox/AI/stats output into readable markdown (never raw JSON dump)."""
    return structured_to_markdown(
        raw,
        fallback_title=intent or pick(locale, "分析报告", "Analysis report"),
        locale=locale,
    )


def _template_report(
    *,
    intent: str,
    stats: Any,
    table: Any,
    selected: list[str] | None,
    locale: str | None = None,
) -> str:
    # Prefer rich stats payloads (often already contain narrative)
    if isinstance(stats, (dict, list, str)) and stats:
        body = _coerce_report_body(stats, intent=intent, locale=locale)
        if body and not body.lstrip().startswith("{"):
            parts = [body]
            if isinstance(table, pd.DataFrame):
                show_cols = [
                    str(c) for c in (selected or table.columns) if str(c) in table.columns
                ]
                parts.append("")
                parts.append(pick(locale, "## 数据概览", "## Data overview"))
                parts.append(
                    pick(locale, f"- 行数：{len(table)}", f"- Rows: {len(table)}")
                )
                parts.append(
                    pick(
                        locale,
                        f"- 列数：{len(table.columns)}",
                        f"- Columns: {len(table.columns)}",
                    )
                )
                if show_cols:
                    parts.append(
                        pick(
                            locale,
                            f"- 展示字段：{', '.join(show_cols)}",
                            f"- Shown columns: {', '.join(show_cols)}",
                        )
                    )
                parts.append("")
                parts.append(dataframe_to_md_tables(table, columns=show_cols or None))
            return "\n".join(parts).strip()

    lines = [
        pick(locale, "# 数据分析报告", "# Data analysis report"),
        "",
        f"> {intent}",
        "",
    ]
    if isinstance(stats, dict) and stats:
        lines.append(
            _coerce_report_body(
                stats,
                intent=pick(locale, "统计摘要", "Statistical summary"),
                locale=locale,
            )
        )
        lines.append("")
    if isinstance(table, pd.DataFrame):
        show_cols = [str(c) for c in (selected or table.columns) if str(c) in table.columns]
        lines.append(pick(locale, "## 数据概览", "## Data overview"))
        lines.append(pick(locale, f"- 行数：{len(table)}", f"- Rows: {len(table)}"))
        lines.append(
            pick(
                locale,
                f"- 列数：{len(table.columns)}",
                f"- Columns: {len(table.columns)}",
            )
        )
        if show_cols:
            lines.append(
                pick(
                    locale,
                    f"- 展示字段：{', '.join(show_cols)}",
                    f"- Shown columns: {', '.join(show_cols)}",
                )
            )
        lines.append("")
        lines.append(dataframe_to_md_tables(table, columns=show_cols or None))
        lines.append("")
    return "\n".join(lines).strip()


def _execute(ctx: dict):
    """Compose report from stats/figure/table; optionally via AI code on table."""
    params = ctx["params"]
    inputs = ctx["inputs"]
    event = ctx["event"]
    node_id = ctx["node_id"]
    locale = ctx.get("locale")
    intent = params.get("intent") or pick(
        locale, "自动生成的分析报告", "Auto-generated analysis report"
    )

    stats = inputs.get("stats_in")
    figure = inputs.get("figure_in")
    table = inputs.get("table_in")
    selected = params.get("columns") if isinstance(params.get("columns"), list) else None

    # Prefer AI-generated markdown when generator + table available
    code = ctx.get("code") or ""
    if (not code) and ctx.get("ai_generator") and isinstance(table, pd.DataFrame):
        generated = ctx["ai_generator"]("ai_report", params, table)
        code = generated["code"]
        event(
            "node_log",
            node_id,
            {
                "message": generated.get(
                    "explanation",
                    pick(locale, "报告代码已生成", "Report code generated"),
                )
            },
        )
        ctx["node"].setdefault("data", {})["code"] = code

    body = ""
    if code and isinstance(table, pd.DataFrame):
        from pathlib import Path
        import tempfile
        from app.sandbox import run_sandboxed
        from app.engine.artifacts import load_output

        with tempfile.TemporaryDirectory(dir=ctx["cache_dir"], prefix="report-") as tmp:
            src = Path(tmp) / "in.parquet"
            out = Path(tmp) / "out.json"
            table.to_parquet(src)
            result = run_sandboxed(
                code=code,
                input_paths={"df": str(src)},
                output_path=out,
                result_var="result",
                result_kind="stats",
                profile="ai",
            )
            if result.ok:
                raw = load_output(out)
                body = _coerce_report_body(raw, intent=intent, locale=locale)
                # If model returned a thin dict without narrative, merge upstream stats prose
                if (
                    isinstance(raw, dict)
                    and not any(isinstance(raw.get(k), str) and raw.get(k) for k in (
                        "narrative", "summary", "markdown", "report", "body"
                    ))
                    and isinstance(stats, dict)
                    and stats
                ):
                    stats_md = _coerce_report_body(stats, intent=intent, locale=locale)
                    if stats_md and len(stats_md) > len(body):
                        body = stats_md
            else:
                event(
                    "node_log",
                    node_id,
                    {
                        "message": pick(
                            locale,
                            f"AI 报告代码失败，使用模板：{result.error}",
                            f"AI report code failed; using template: {result.error}",
                        )
                    },
                )

    if not body:
        body = _template_report(
            intent=intent, stats=stats, table=table, selected=selected, locale=locale
        )

    # Final safety: never ship a pure JSON blob as the report body
    stripped = body.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            body = _coerce_report_body(json.loads(stripped), intent=intent, locale=locale)
        except Exception:
            body = _coerce_report_body(
                stats if isinstance(stats, dict) else stripped,
                intent=intent,
                locale=locale,
            )

    if figure is not None:
        try:
            b64 = figure_to_png_b64(figure)
            body += markdown_chart_block(b64)
            event(
                "node_log",
                node_id,
                {
                    "message": pick(
                        locale,
                        "已将上游图表渲染为 PNG 并嵌入报告",
                        "Embedded upstream chart as PNG in the report",
                    )
                },
            )
        except Exception as exc:
            event(
                "node_log",
                node_id,
                {
                    "message": pick(
                        locale,
                        f"图表嵌入失败（请确认已安装 kaleido）：{exc}",
                        f"Chart embed failed (is kaleido installed?): {exc}",
                    )
                },
            )
            chart_h = pick(locale, "## 图表", "## Chart")
            fail = pick(locale, f"图表渲染失败：{exc}", f"Chart render failed: {exc}")
            body += f"\n\n{chart_h}\n\n> {fail}\n"

    return {"text_out": body}


SPEC = register(
    NodeSpec(
        type="ai_report",
        category="report",
        label="AI 报告",
        label_en="AI Report",
        description="将统计、图表与表格汇总为 Markdown 报告",
        keywords=("report", "报告", "markdown"),
        icon="report",
        priority=100,
        inputs=[
            Port("stats_in", "stats", "统计", required=False),
            Port("figure_in", "figure", "图表", required=False),
            Port("table_in", "table", "表格", required=False),
        ],
        outputs=[Port("text_out", "text", "报告", default=True)],
        params_schema=[
            param("columns", "columns", False, "报告字段"),
            param("intent", "textarea", False, "报告意图"),
            param("model", "model", False, "AI 模型"),
        ],
        is_ai=True,
        code_profile="ai",
        messages=MessageCatalog(),
        execute=_execute,
    )
)
