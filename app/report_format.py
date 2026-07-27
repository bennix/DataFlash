"""Helpers for report / PDF-friendly markdown tables."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

import pandas as pd

MAX_SAMPLE_ROWS = 10
MAX_COLS_PER_TABLE = 6
MAX_CELL_CHARS = 40

_NARRATIVE_KEYS = (
    "narrative",
    "summary",
    "report",
    "markdown",
    "body",
    "analysis",
    "结论",
    "分析说明",
)
_TITLE_KEYS = ("report_title", "title", "标题", "name")
_SKIP_KEYS = frozenset(
    {
        *_NARRATIVE_KEYS,
        *_TITLE_KEYS,
        "code",
        "assumptions",
        "steps",
        "explanation",
        "intent",
    }
)


def _clip_cell(value: Any, limit: int = MAX_CELL_CHARS) -> str:
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def ensure_md_table_blank_lines(md_text: str) -> str:
    """Insert a blank line before GFM tables so Python-Markdown can parse them.

    Without a blank line after a paragraph/heading label, tables are swallowed into
    ``<p>`` and WeasyPrint collapses row newlines into a single line of pipes.
    """
    if not md_text:
        return md_text
    lines = md_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_table = stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2
        if is_table and out:
            prev = out[-1].strip()
            prev_is_table = prev.startswith("|") and prev.endswith("|") and prev.count("|") >= 2
            if prev and not prev_is_table:
                out.append("")
        out.append(line)
    return "\n".join(out)


def dataframe_to_md_tables(
    df: pd.DataFrame,
    *,
    columns: Iterable[str] | None = None,
    max_rows: int = MAX_SAMPLE_ROWS,
    max_cols: int = MAX_COLS_PER_TABLE,
) -> str:
    """Render a dataframe as one or more narrow markdown tables that fit PDF width."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return "_（无数据）_"

    wanted = [str(c) for c in (columns or []) if str(c) in df.columns]
    cols = wanted or [str(c) for c in df.columns]
    sample = df.loc[:, cols].head(max_rows).copy()
    for col in sample.columns:
        sample[col] = sample[col].map(_clip_cell)

    chunks: list[str] = []
    total = len(cols)
    for start in range(0, total, max_cols):
        part_cols = cols[start : start + max_cols]
        part = sample.loc[:, part_cols]
        if total > max_cols:
            # Blank line after the label is required for Markdown table parsing.
            chunks.append(f"**字段 {start + 1}–{start + len(part_cols)} / {total}**\n")
        chunks.append(part.to_markdown(index=False))
        chunks.append("")
    if len(df) > max_rows:
        chunks.append(f"_仅展示前 {max_rows} 行，共 {len(df)} 行。_")
    return ensure_md_table_blank_lines("\n".join(chunks).strip())


def _pretty_key(key: Any) -> str:
    text = str(key).strip()
    text = text.replace("_", " ")
    return text


def _fmt_scalar(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if pd.isna(value):
            return "—"
        if abs(value) >= 1000 or (abs(value) < 0.01 and value != 0):
            return f"{value:.4g}"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _is_stats_row(value: Any) -> bool:
    return isinstance(value, dict) and value and all(
        isinstance(v, (int, float, str, bool)) or v is None for v in value.values()
    )


def _dict_of_stats_to_table(data: dict[str, Any]) -> str | None:
    """Render {col: {stat: val}} describe-like dict as a markdown table."""
    if not data or not all(isinstance(v, dict) for v in data.values()):
        return None
    # Collect union of inner keys
    inner_keys: list[str] = []
    for inner in data.values():
        for k in inner.keys():
            if str(k) not in inner_keys:
                inner_keys.append(str(k))
    if not inner_keys or not all(
        all(isinstance(v, (int, float, str, bool)) or v is None for v in inner.values())
        for inner in data.values()
    ):
        return None
    header = ["字段", *inner_keys]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for field, inner in data.items():
        row = [_pretty_key(field)] + [_fmt_scalar(inner.get(k)) for k in inner_keys]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _format_mapping(data: dict[str, Any], *, depth: int = 0) -> str:
    if depth > 3:
        return "```json\n" + json.dumps(data, ensure_ascii=False, indent=2, default=str)[:2000] + "\n```"

    # describe-like nested map
    table = _dict_of_stats_to_table(data)
    if table:
        return table

    # flat distribution / KPI map
    if _is_stats_row(data):
        return "\n".join(f"- **{_pretty_key(k)}**：{_fmt_scalar(v)}" for k, v in data.items())

    parts: list[str] = []
    for key, val in data.items():
        label = _pretty_key(key)
        if isinstance(val, dict):
            nested_table = _dict_of_stats_to_table(val)
            if nested_table:
                parts.append(f"**{label}**\n\n{nested_table}")
            elif _is_stats_row(val):
                bullets = "\n".join(
                    f"- **{_pretty_key(k)}**：{_fmt_scalar(v)}" for k, v in val.items()
                )
                parts.append(f"**{label}**\n\n{bullets}")
            else:
                parts.append(f"**{label}**\n\n{_format_mapping(val, depth=depth + 1)}")
        elif isinstance(val, list):
            parts.append(f"**{label}**\n\n{_format_list(val, depth=depth + 1)}")
        else:
            parts.append(f"- **{label}**：{_fmt_scalar(val)}")
    return "\n\n".join(parts)


def _format_list(items: list[Any], *, depth: int = 0) -> str:
    if not items:
        return "_（空列表）_"
    if all(isinstance(x, (int, float, str, bool)) or x is None for x in items):
        return "\n".join(f"- {_fmt_scalar(x)}" for x in items[:50])
    if all(isinstance(x, dict) for x in items):
        try:
            frame = pd.DataFrame(items)
            return dataframe_to_md_tables(frame)
        except Exception:
            pass
    return "\n".join(f"- {x}" for x in items[:30])


def _section(locale: str | None, zh: str) -> str:
    from app.i18n import is_en
    from app.i18n.catalog import REPORT_SECTION_EN

    if is_en(locale):
        return REPORT_SECTION_EN.get(zh, zh)
    return zh


def structured_to_markdown(
    value: Any, *, fallback_title: str = "分析报告", locale: str | None = None
) -> str:
    """Turn AI/stats JSON (or markdown string) into readable report markdown.

    Prefer ``narrative`` / title fields when present; never leave raw JSON as the
    primary reading experience.
    """
    from app.i18n import is_en, pick

    if value is None:
        return ""

    if isinstance(value, pd.DataFrame):
        return dataframe_to_md_tables(value)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        # JSON string accidentally saved as report body
        if (text.startswith("{") and text.endswith("}")) or (
            text.startswith("[") and text.endswith("]")
        ):
            try:
                return structured_to_markdown(
                    json.loads(text), fallback_title=fallback_title, locale=locale
                )
            except Exception:
                pass
        # Strip accidental outer quotes from json.dumps(str)
        if len(text) >= 2 and text[0] == text[-1] == '"' and "\\n" in text:
            try:
                return structured_to_markdown(
                    json.loads(text), fallback_title=fallback_title, locale=locale
                )
            except Exception:
                pass
        return text

    if isinstance(value, list):
        return _format_list(value)

    if not isinstance(value, dict):
        return str(value)

    data = value
    default_title = pick(locale, "分析报告", "Analysis report")
    title = (
        next((str(data[k]).strip() for k in _TITLE_KEYS if data.get(k)), "")
        or fallback_title
        or default_title
    )
    narrative = next(
        (data[k] for k in _NARRATIVE_KEYS if isinstance(data.get(k), str) and str(data.get(k)).strip()),
        "",
    )
    narrative = str(narrative).strip() if narrative else ""
    colon = ": " if is_en(locale) else "："

    lines: list[str] = []
    if title and not (narrative.startswith("#") and title in narrative[:80]):
        lines.append(f"# {title}")
        lines.append("")

    scalars = {
        k: v
        for k, v in data.items()
        if k not in _SKIP_KEYS and (isinstance(v, (int, float, bool, str)) or v is None)
    }
    # Keep short strings as KPI; long strings belong in narrative-like body
    kpi = {k: v for k, v in scalars.items() if not (isinstance(v, str) and len(v) > 80)}
    long_text = {
        k: v for k, v in scalars.items() if isinstance(v, str) and len(v) > 80 and k not in _SKIP_KEYS
    }

    if kpi:
        lines.append(f"## {_section(locale, '关键指标')}")
        for k, v in kpi.items():
            lines.append(f"- **{_pretty_key(k)}**{colon}{_fmt_scalar(v)}")
        lines.append("")

    if narrative:
        # Narrative often already has its own structure
        analysis_h = _section(locale, "分析说明")
        if not re.match(r"^#{1,3}\s", narrative) and analysis_h not in narrative[:30]:
            lines.append(f"## {analysis_h}")
            lines.append("")
        lines.append(narrative)
        lines.append("")

    for k, v in long_text.items():
        lines.append(f"## {_pretty_key(k)}")
        lines.append("")
        lines.append(v.strip())
        lines.append("")

    nested = {k: v for k, v in data.items() if k not in _SKIP_KEYS and k not in scalars}
    if nested:
        # If narrative already covers the story, put details under appendix
        section = f"## {_section(locale, '明细数据')}" if narrative else None
        if section:
            lines.append(section)
            lines.append("")
        for k, v in nested.items():
            lines.append(f"### {_pretty_key(k)}" if section else f"## {_pretty_key(k)}")
            lines.append("")
            if isinstance(v, dict):
                lines.append(_format_mapping(v))
            elif isinstance(v, list):
                lines.append(_format_list(v))
            else:
                lines.append(_fmt_scalar(v))
            lines.append("")

    text = "\n".join(lines).strip()
    return text or json.dumps(data, ensure_ascii=False, indent=2, default=str)
