from pathlib import Path

import markdown
import pandas as pd

from app.nodes.export_node import _html_to_pdf, _md_to_html
from app.report_format import (
    dataframe_to_md_tables,
    ensure_md_table_blank_lines,
    structured_to_markdown,
)


def test_dataframe_to_md_tables_splits_wide_frames():
    cols = [f"c{i}" for i in range(12)]
    df = pd.DataFrame([{c: f"v{i}-{c}" * 5 for c in cols} for i in range(3)])
    md = dataframe_to_md_tables(df, max_cols=6)
    assert "字段 1–6 / 12" in md
    assert "字段 7–12 / 12" in md
    assert md.count("|") > 10
    # Label and table must be separated by a blank line or Markdown won't parse <table>.
    assert "**字段 1–6 / 12**\n\n|" in md


def test_md_tables_render_as_html_tables_in_pdf_path():
    cols = [f"c{i}" for i in range(8)]
    df = pd.DataFrame([{c: i for c in cols} for i in range(3)])
    md = "## 概览\n\n- 列数：8\n\n" + dataframe_to_md_tables(df, max_cols=6)
    html = _md_to_html(md)
    assert html.count("<table>") >= 2
    assert "| c0 |" not in html  # raw pipes must not remain in body paragraphs

    # AI-style report: label stuck to table without blank line — sanitizer fixes it.
    sticky = "**字段 1–6 / 8**\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert "<table>" not in markdown.markdown(sticky, extensions=["tables"])
    assert "<table>" in _md_to_html(sticky)
    assert "**字段 1–6 / 8**\n\n|" in ensure_md_table_blank_lines(sticky)


def test_structured_stats_with_narrative_becomes_markdown():
    payload = {
        "report_title": "乘客生存分析简报",
        "sample_size": 16,
        "survival_rate": 1.0,
        "age_stats": {"count": 16, "mean": 25.19, "std": 10.2, "min": 2, "max": 45},
        "sex_distribution": {"female": 10, "male": 6},
        "narrative": "1. 样本共 16 人，全部生还。\n2. 平均年龄约 25 岁。",
    }
    md = structured_to_markdown(payload)
    assert "# 乘客生存分析简报" in md
    assert "关键指标" in md
    assert "sample size" in md.lower() or "样本量" in md or "16" in md
    assert "全部生还" in md
    assert "sex distribution" in md.lower() or "Sex" in md or "female" in md
    assert "```json" not in md
    assert not md.strip().startswith("{")


def test_report_node_uses_narrative_not_raw_json(tmp_path: Path):
    from app.nodes import ai_report

    stats = {
        "report_title": "测试简报",
        "sample_size": 3,
        "narrative": "这是可读的分析说明，不应以 JSON 展示。",
        "fare_stats": {"mean": 12.5, "max": 30},
    }
    body = ai_report._execute(
        {
            "params": {"intent": "写报告"},
            "inputs": {"stats_in": stats, "figure_in": None, "table_in": None},
            "event": lambda *a, **k: None,
            "node_id": "r1",
            "code": "",
            "ai_generator": None,
            "cache_dir": str(tmp_path),
            "node": {"data": {}},
        }
    )["text_out"]
    assert "这是可读的分析说明" in body
    assert "测试简报" in body
    assert not body.strip().startswith("{")
    assert '"narrative"' not in body


def test_pdf_export_does_not_overflow_wide_table(tmp_path: Path):
    cols = [
        "PassengerId",
        "Survived",
        "Pclass",
        "Name",
        "Sex",
        "Age",
        "SibSp",
        "Parch",
        "Ticket",
        "Fare",
        "Cabin",
        "Embarked",
    ]
    df = pd.DataFrame(
        [
            {
                "PassengerId": 2,
                "Survived": 1,
                "Pclass": 1,
                "Name": "Cumings, Mrs. John Bradley (Florence Briggs Thayer)",
                "Sex": "female",
                "Age": 38,
                "SibSp": 1,
                "Parch": 0,
                "Ticket": "PC 17599",
                "Fare": 71.2833,
                "Cabin": "C85",
                "Embarked": "C",
            }
        ]
    )
    md = "# 数据分析报告\n\n## 数据概览\n\n" + dataframe_to_md_tables(df, columns=cols, max_cols=6)
    html = _md_to_html(md)
    assert "table-layout: fixed" in html
    assert "overflow-wrap: anywhere" in html
    out = tmp_path / "wide.pdf"
    _html_to_pdf(html, out)
    assert out.is_file() and out.stat().st_size > 1000
