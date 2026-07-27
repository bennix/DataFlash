from pathlib import Path
import pandas as pd
from app.ai import mock_generate
from app.engine import execute


def test_report_embeds_chart_png(tmp_path):
    source = tmp_path / "s.csv"
    source.write_text("Age,Fare\n22,7.25\n38,71.28\n26,7.92\n", encoding="utf-8")
    out_md = tmp_path / "r.md"
    graph = {
        "nodes": [
            {"id": "n1", "type": "file_input", "data": {"params": {"path": str(source)}}},
            {"id": "n5", "type": "ai_chart", "data": {"params": {"x": "Age", "y": "Fare", "model": "mock"}}},
            {"id": "n6", "type": "ai_report", "data": {"params": {"intent": "t", "model": "mock"}}},
            {"id": "n7", "type": "export", "data": {"params": {"format": "md", "path": str(out_md)}}},
        ],
        "edges": [
            {"source": "n1", "sourceHandle": "table_out", "target": "n5", "targetHandle": "table_in"},
            {"source": "n5", "sourceHandle": "figure_out", "target": "n6", "targetHandle": "figure_in"},
            {"source": "n1", "sourceHandle": "table_out", "target": "n6", "targetHandle": "table_in"},
            {"source": "n6", "sourceHandle": "text_out", "target": "n7", "targetHandle": "input"},
        ],
    }
    _, outputs = execute(
        graph,
        tmp_path / "cache",
        lambda *a: None,
        configured=True,
        ai_generator=mock_generate,
        concurrency=1,
    )
    report = outputs["n6"]
    assert "data:image/png;base64," in report, report[:500]
