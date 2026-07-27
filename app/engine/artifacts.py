"""Disk artifacts: parquet/json + .meta.json sidecar (SPEC delta §2.2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.schema import TableSchema, infer_schema, schema_summary_brief, schema_summary_detail


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_table(df: pd.DataFrame, base: Path, *, mask_samples: bool = True) -> Path:
    base.parent.mkdir(parents=True, exist_ok=True)
    path = base.with_suffix(".parquet")
    df.to_parquet(path)
    schema = infer_schema(df, mask_samples=mask_samples)
    _write_meta(
        base,
        kind="table",
        schema=schema.to_dict(),
        summary={"brief": schema_summary_brief(schema), "detail": schema_summary_detail(schema)},
    )
    return path


def save_figure(fig: Any, base: Path) -> Path:
    base.parent.mkdir(parents=True, exist_ok=True)
    path = base.with_suffix(".figure.json")
    from app.figures import figure_to_json

    # Avoid json default=str — it stringifies numpy customdata and breaks Plotly reload.
    path.write_text(figure_to_json(fig), encoding="utf-8")
    _write_meta(base, kind="figure", summary={"brief": "figure", "detail": "plotly figure"})
    return path


def save_json(value: Any, base: Path, kind: str = "stats") -> Path:
    base.parent.mkdir(parents=True, exist_ok=True)
    path = base.with_suffix(".json")
    path.write_text(json.dumps(value, default=str, ensure_ascii=False), encoding="utf-8")
    brief = kind
    if isinstance(value, dict) and "row_count" in value:
        brief = f"stats({value['row_count']})"
    _write_meta(base, kind=kind, summary={"brief": brief, "detail": kind})
    return path


def save_text(text: str, base: Path) -> Path:
    base.parent.mkdir(parents=True, exist_ok=True)
    path = base.with_suffix(".md")
    path.write_text(text, encoding="utf-8")
    _write_meta(
        base,
        kind="text",
        summary={"brief": f"{len(text)} chars", "detail": "markdown"},
    )
    return path


def _write_meta(base: Path, *, kind: str, schema: dict | None = None, summary: dict | None = None) -> None:
    meta = {
        "kind": kind,
        "schema": schema,
        "summary": summary or {},
        "created_at": now_iso(),
    }
    base.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, default=str), encoding="utf-8"
    )


def load_meta(base: Path) -> dict[str, Any] | None:
    meta_path = base.with_suffix(".meta.json")
    # Also try beside known suffixes
    if not meta_path.exists():
        for suffix in (".parquet", ".figure.json", ".json", ".md"):
            candidate = Path(str(base) + "").with_suffix(".meta.json")
            # Prefer sibling of artifact: <fp>/<port>.meta.json next to <fp>/<port>.parquet
            pass
    # Convention: base is .cache/<fp>/<port_id> without suffix
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    # Try from artifact path with suffix
    stem = base
    if base.suffix:
        stem = base.with_suffix("")
        if stem.suffix == ".figure":
            stem = stem.with_suffix("")
    alt = stem.with_suffix(".meta.json")
    if alt.exists():
        return json.loads(alt.read_text(encoding="utf-8"))
    return None


def load_output(path: str | Path) -> Any:
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".md":
        return path.read_text(encoding="utf-8")
    if path.name.endswith(".figure.json"):
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema_for(path: str | Path) -> TableSchema | None:
    path = Path(path)
    stem = path
    if path.name.endswith(".figure.json"):
        stem = Path(str(path)[: -len(".figure.json")])
    elif path.suffix:
        stem = path.with_suffix("")
    meta = load_meta(stem)
    if meta and meta.get("schema"):
        return TableSchema.from_dict(meta["schema"])
    if path.suffix == ".parquet":
        return infer_schema(pd.read_parquet(path))
    return None


def cached_artifact(base: Path) -> Path | None:
    for suffix in (".parquet", ".figure.json", ".json", ".md"):
        # .figure.json is two suffixes conceptually
        if suffix == ".figure.json":
            candidate = Path(str(base) + ".figure.json")
        else:
            candidate = base.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def save_output(value: Any, base: Path, *, kind: str | None = None) -> Path:
    if isinstance(value, pd.DataFrame):
        return save_table(value, base)
    if hasattr(value, "to_plotly_json") or kind == "figure":
        return save_figure(value, base)
    if kind == "file":
        return save_json({"path": value} if isinstance(value, str) else value, base, kind="file")
    if kind == "text" or (isinstance(value, str) and kind != "stats"):
        return save_text(str(value), base)
    return save_json(value, base, kind=kind or "stats")
