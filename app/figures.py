"""Plotly figure → PNG helpers for reports / PDF."""

from __future__ import annotations

import ast
import base64
import json
import os
import re
from pathlib import Path
from typing import Any


def _ensure_native_libs() -> None:
    lib = "/opt/homebrew/lib"
    if Path(lib).is_dir():
        prev = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if lib not in prev:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{lib}:{prev}" if prev else lib


def _to_jsonable(value: Any) -> Any:
    """Convert numpy/pandas values so Plotly JSON round-trips cleanly."""
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore
    try:
        import pandas as pd
    except ImportError:
        pd = None  # type: ignore

    if np is not None:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    if pd is not None:
        if isinstance(value, pd.Series):
            return value.tolist()
        if isinstance(value, pd.Index):
            return value.tolist()
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def figure_to_dict(fig: Any) -> dict[str, Any]:
    """Normalize a figure object/dict into a JSON-safe plotly dict."""
    if hasattr(fig, "to_plotly_json"):
        payload = fig.to_plotly_json()
    elif isinstance(fig, dict):
        payload = fig
    else:
        raise TypeError(f"无法识别的 figure 类型：{type(fig)!r}")
    return _to_jsonable(payload)


def figure_to_json(fig: Any) -> str:
    return json.dumps(figure_to_dict(fig), ensure_ascii=False)


def _repair_arrayish_string(value: str) -> Any | None:
    """Best-effort recovery for arrays stringified by json default=str."""
    text = value.strip()
    if not text:
        return None
    # Numpy repr: "[['female' 'c']\n ['female' 's']]"
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")")):
        try:
            import numpy as np

            repaired = np.array(ast.literal_eval(text.replace("] [", "], [").replace("'\n", "',\n")))
            return repaired.tolist()
        except Exception:
            pass
        try:
            # Common numpy 2d string: replace spaces between quotes with commas
            normalized = re.sub(r"'([^']*)'\s+'", r"'\1', '", text)
            normalized = re.sub(r"\]\s+\[", "], [", normalized)
            return ast.literal_eval(normalized)
        except Exception:
            return None
    return None


def sanitize_figure_dict(fig: dict[str, Any]) -> dict[str, Any]:
    """Fix/drop trace fields that break Plotly validation after bad JSON round-trips."""
    data = fig.get("data")
    if not isinstance(data, list):
        return fig
    array_keys = (
        "customdata",
        "ids",
        "hovertext",
        "text",
        "x",
        "y",
        "z",
        "lat",
        "lon",
        "values",
        "labels",
        "locations",
    )
    for trace in data:
        if not isinstance(trace, dict):
            continue
        for key in array_keys:
            if key not in trace:
                continue
            val = trace[key]
            if isinstance(val, str):
                repaired = _repair_arrayish_string(val)
                if repaired is not None:
                    trace[key] = repaired
                else:
                    # customdata/ids are hover helpers — safe to drop for PNG export
                    if key in {"customdata", "ids"}:
                        del trace[key]
                    # leave other string fields (e.g. single text) alone if not array-like
                    elif key == "text" and not (val.startswith("[") or "\n" in val):
                        continue
                    elif val.startswith("[") or "\n" in val:
                        del trace[key]
            elif isinstance(val, tuple):
                trace[key] = list(val)
    return fig


def figure_to_png_bytes(fig: Any) -> bytes:
    """Render a plotly figure (object or dict) to PNG bytes. Raises on failure."""
    _ensure_native_libs()
    import plotly.io as pio

    if hasattr(fig, "to_image") and not isinstance(fig, dict):
        try:
            return fig.to_image(format="png", width=960, height=540, scale=2)
        except Exception:
            # Fall through to sanitized dict path (e.g. figure already partially broken)
            pass

    payload = sanitize_figure_dict(figure_to_dict(fig))
    fig_obj = pio.from_json(json.dumps(payload, ensure_ascii=False))
    return fig_obj.to_image(format="png", width=960, height=540, scale=2)


def figure_to_png_b64(fig: Any) -> str:
    return base64.b64encode(figure_to_png_bytes(fig)).decode("ascii")


def markdown_chart_block(b64: str, *, alt: str = "chart") -> str:
    """Markdown image block; keep URL on one line for parsers."""
    return f"\n\n## 图表\n\n![{alt}](data:image/png;base64,{b64})\n"


_DATA_IMG_RE = re.compile(
    r"""(<img\b[^>]*\bsrc\s*=\s*)(['"])data:(image/(?:png|jpeg|jpg|gif|webp));base64,([A-Za-z0-9+/=\s]+)\2""",
    re.IGNORECASE,
)


def materialize_data_uri_images(html: str, workdir: Path) -> str:
    """Rewrite data-URI <img src> to local file:// paths for WeasyPrint reliability."""
    workdir.mkdir(parents=True, exist_ok=True)
    counter = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        prefix, _quote, mime, payload = match.groups()
        ext = "jpg" if mime.endswith("jpeg") or mime.endswith("jpg") else mime.split("/")[-1]
        raw = base64.b64decode(re.sub(r"\s+", "", payload))
        path = workdir / f"embed_{counter}.{ext}"
        path.write_bytes(raw)
        return f'{prefix}"{path.resolve().as_uri()}"'

    return _DATA_IMG_RE.sub(repl, html)
