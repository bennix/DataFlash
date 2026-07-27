"""P0 main pipeline E2E with mock AI (SPEC 6.1 / delta §3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai import mock_generate
from app.engine import execute


def test_main_pipeline_exports_pdf_with_image(tmp_path):
    source = tmp_path / "titanic_sample.csv"
    source.write_text(
        "Survived,Sex,Age,Fare\n"
        "1,female,22,7.25\n"
        "0,male,38,71.28\n"
        "1,female,26,7.92\n"
        "1,female,35,53.1\n"
        "0,male,,8.05\n"
        "0,male,54,51.86\n",
        encoding="utf-8",
    )
    pdf_path = tmp_path / "report.pdf"
    graph = {
        "format_version": 2,
        "nodes": [
            {
                "id": "n1",
                "type": "file_input",
                "data": {"params": {"path": str(source)}},
            },
            {
                "id": "n2",
                "type": "ai_clean",
                "data": {"params": {"intent": "去重并删除空值", "model": "mock"}},
            },
            {
                "id": "n3",
                "type": "filter",
                "data": {"params": {"expression": "Survived == 1"}},
            },
            {
                "id": "n4",
                "type": "ai_analyze",
                "data": {"params": {"intent": "描述统计", "model": "mock"}},
            },
            {
                "id": "n5",
                "type": "ai_chart",
                "data": {"params": {"x": "Age", "y": "Fare", "intent": "散点图", "model": "mock"}},
            },
            {
                "id": "n6",
                "type": "ai_report",
                "data": {"params": {"intent": "乘客生存分析", "model": "mock"}},
            },
            {
                "id": "n7",
                "type": "export",
                "data": {"params": {"format": "pdf", "path": str(pdf_path)}},
            },
        ],
        "edges": [
            {"source": "n1", "sourceHandle": "table_out", "target": "n2", "targetHandle": "table_in"},
            {"source": "n2", "sourceHandle": "table_out", "target": "n3", "targetHandle": "table_in"},
            {"source": "n3", "sourceHandle": "matched", "target": "n4", "targetHandle": "table_in"},
            {"source": "n3", "sourceHandle": "matched", "target": "n5", "targetHandle": "table_in"},
            {"source": "n4", "sourceHandle": "stats_out", "target": "n6", "targetHandle": "stats_in"},
            {"source": "n5", "sourceHandle": "figure_out", "target": "n6", "targetHandle": "figure_in"},
            {"source": "n3", "sourceHandle": "matched", "target": "n6", "targetHandle": "table_in"},
            {"source": "n6", "sourceHandle": "text_out", "target": "n7", "targetHandle": "input"},
        ],
    }

    events = []

    def on_event(kind, node, payload):
        events.append((kind, node))

    def generator(node_type, params, df):
        return mock_generate(node_type, params, df)

    run_id, outputs = execute(
        graph,
        tmp_path / "cache",
        on_event,
        configured=True,
        ai_generator=generator,
    )
    assert run_id
    assert pdf_path.is_file()
    size = pdf_path.stat().st_size
    assert size > 20_000, f"PDF too small: {size}"
    # Report node should have embedded a chart (base64 PNG in markdown → PDF)
    report_md = outputs.get("n6")
    assert isinstance(report_md, str) and "data:image/png;base64," in report_md
    assert ("run_done", None) in events
