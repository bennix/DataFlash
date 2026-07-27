import json
from pathlib import Path

import numpy as np
import plotly.graph_objects as go

from app.engine.artifacts import load_output, save_figure
from app.figures import (
    figure_to_png_b64,
    figure_to_png_bytes,
    markdown_chart_block,
    materialize_data_uri_images,
    sanitize_figure_dict,
)
from app.nodes.export_node import _html_to_pdf, _md_to_html


def test_figure_to_png_and_markdown_block():
    fig = go.Figure(data=[go.Bar(x=["a", "b"], y=[1, 2])])
    b64 = figure_to_png_b64(fig)
    assert len(b64) > 100
    md = markdown_chart_block(b64)
    assert "data:image/png;base64," in md
    assert "\n" not in b64


def test_save_figure_preserves_numpy_customdata(tmp_path: Path):
    custom = np.array([["female", "c"], ["female", "s"], ["male", "q"]])
    fig = go.Figure(
        data=[
            go.Scatter(
                x=[1, 2, 3],
                y=[3, 1, 2],
                mode="markers",
                customdata=custom,
                hovertemplate="%{customdata[0]} %{customdata[1]}",
            )
        ]
    )
    path = save_figure(fig, tmp_path / "chart")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload["data"][0]["customdata"], list)
    assert payload["data"][0]["customdata"][0] == ["female", "c"]
    loaded = load_output(path)
    # Must render even after disk round-trip
    assert len(figure_to_png_bytes(loaded)) > 100


def test_sanitize_stringified_customdata_for_png():
    broken = {
        "data": [
            {
                "type": "scatter",
                "x": [1, 2],
                "y": [3, 4],
                "customdata": "[['female' 'c']\n ['female' 's']]",
            }
        ],
        "layout": {},
    }
    fixed = sanitize_figure_dict(json.loads(json.dumps(broken)))
    assert isinstance(fixed["data"][0]["customdata"], list) or "customdata" not in fixed["data"][0]
    assert len(figure_to_png_bytes(broken)) > 100


def test_materialize_data_uri_images(tmp_path: Path):
    fig = go.Figure(data=[go.Scatter(x=[1], y=[1])])
    png = figure_to_png_b64(fig)
    html = f'<p><img alt="c" src="data:image/png;base64,{png}" /></p>'
    out = materialize_data_uri_images(html, tmp_path)
    assert "data:image" not in out
    assert "file://" in out
    assert list(tmp_path.glob("embed_*.png"))


def test_pdf_contains_embedded_chart(tmp_path: Path):
    fig = go.Figure(data=[go.Bar(x=["a", "b"], y=[3, 4])])
    b64 = figure_to_png_b64(fig)
    md = "# Report\n" + markdown_chart_block(b64)
    html = _md_to_html(md)
    pdf = tmp_path / "chart.pdf"
    _html_to_pdf(html, pdf)
    assert pdf.stat().st_size > 8_000
    # PDF should reference an image XObject
    assert b"/Image" in pdf.read_bytes()
