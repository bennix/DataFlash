from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import markdown
import pandas as pd

from app.registry import Message, MessageCatalog, NodeSpec, Port, param, register


def _md_to_html(md_text: str) -> str:
    from app.report_format import ensure_md_table_blank_lines

    # AI / composed reports often omit the blank line before tables; without it
    # Python-Markdown keeps pipes inside <p> and PDF shows one smashed line.
    md_text = ensure_md_table_blank_lines(md_text or "")
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 1.2cm; }}
html, body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif;
  color: #222;
  font-size: 11px;
  line-height: 1.45;
  word-wrap: break-word;
  overflow-wrap: anywhere;
}}
body {{ margin: 0; }}
h1 {{ font-size: 1.6em; margin: 0 0 0.6em; }}
h2 {{ font-size: 1.25em; margin: 1.1em 0 0.45em; }}
h3 {{ font-size: 1.05em; margin: 0.9em 0 0.35em; }}
img {{ max-width: 100%; height: auto; }}
pre, code {{
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.9em;
}}
table {{
  width: 100%;
  max-width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  margin: 0.6em 0 1em;
  font-size: 8.5px;
}}
th, td {{
  border: 1px solid #ccc;
  padding: 3px 4px;
  vertical-align: top;
  overflow-wrap: anywhere;
  word-break: break-word;
  hyphens: auto;
}}
th {{ background: #f3f0e8; font-weight: 600; }}
blockquote {{
  margin: 0.4em 0 0.8em;
  padding-left: 0.8em;
  border-left: 3px solid #c9c0ae;
  color: #444;
}}
</style></head><body>{body}</body></html>"""


def _html_to_pdf(html: str, out_path: Path) -> None:
    # Ensure Homebrew libs visible on macOS
    lib = "/opt/homebrew/lib"
    if Path(lib).is_dir():
        prev = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if lib not in prev:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{lib}:{prev}" if prev else lib
    from weasyprint import HTML

    from app.figures import materialize_data_uri_images

    # WeasyPrint is more reliable with file:// images than huge data-URIs.
    with tempfile.TemporaryDirectory(prefix="dataflash-pdf-") as tmp:
        html = materialize_data_uri_images(html, Path(tmp))
        HTML(string=html, base_url=tmp).write_pdf(str(out_path))


def _execute(ctx: dict):
    params = ctx["params"]
    fmt = (params.get("format") or "pdf").lower()
    out_path = Path(params["path"])
    out_path.parent.mkdir(parents=True, exist_ok=True)

    value = ctx["inputs"].get("input")
    event = ctx["event"]
    node_id = ctx["node_id"]

    if value is None:
        raise RuntimeError("Export 没有输入")

    if fmt == "md":
        text = value if isinstance(value, str) else _value_to_md(value)
        out_path.write_text(text, encoding="utf-8")
    elif fmt == "pdf":
        text = value if isinstance(value, str) else _value_to_md(value)
        html = _md_to_html(text)
        _html_to_pdf(html, out_path)
    else:
        raise ValueError(f"不支持的导出格式：{fmt}（仅支持 md / pdf）")

    event("node_log", node_id, {"message": f"已导出 {fmt} → {out_path} ({out_path.stat().st_size} bytes)"})
    return {"file_out": str(out_path)}


def _value_to_md(value: Any) -> str:
    if isinstance(value, pd.DataFrame):
        from app.report_format import dataframe_to_md_tables

        return dataframe_to_md_tables(value)
    if isinstance(value, dict):
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n```"
    return str(value)


SPEC = register(
    NodeSpec(
        type="export",
        category="output",
        label="导出 PDF",
        label_en="Export PDF",
        description="将报告导出为 Markdown 或 PDF",
        keywords=("export", "pdf", "md", "markdown", "导出", "报告"),
        icon="export",
        priority=200,
        inputs=[Port("input", "any", "输入")],
        outputs=[Port("file_out", "file", "文件", default=True)],
        params_schema=[
            param(
                "format",
                "select",
                True,
                "导出格式",
                options=["pdf", "md"],
            ),
            param("path", "string", True, "输出路径"),
        ],
        messages=MessageCatalog(
            error={
                "export_failed": Message("export_failed", "导出失败：{err}", "检查路径与格式"),
            },
        ),
        code_profile="trusted",
        execute=_execute,
    )
)
