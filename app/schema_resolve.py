"""Resolve table schemas for inspector / AI context (file probe + run cache + upstream)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd

from app.registry import get_spec
from app.schema import Column, TableSchema, infer_schema, schema_public

PROBE_ROWS = 500

__all__ = [
    "schema_public",
    "probe_file_schema",
    "schema_from_artifact",
    "resolve_node_output_schema",
    "resolve_upstream_schema",
    "resolve_table_input_schemas",
    "selected_columns_from_params",
]


def probe_file_schema(path: str | Path) -> TableSchema:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")
    ext = path.suffix.lower().lstrip(".")
    if ext == "csv":
        df = pd.read_csv(path, nrows=PROBE_ROWS)
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(path, nrows=PROBE_ROWS)
    elif ext == "json":
        df = pd.read_json(path)
        if len(df) > PROBE_ROWS:
            df = df.head(PROBE_ROWS)
    else:
        raise ValueError("仅支持 CSV、XLSX、JSON")
    return infer_schema(df)


def schema_from_artifact(path: str | Path | None) -> TableSchema | None:
    if not path:
        return None
    try:
        from app.engine.artifacts import load_schema_for

        return load_schema_for(path)
    except Exception:
        return None


def _node_data(node: dict) -> dict:
    return node.get("data") or {}


def _node_params(node: dict) -> dict:
    data = _node_data(node)
    return data.get("params") or node.get("params") or {}


def _find_node(graph: dict, node_id: str) -> dict | None:
    for node in graph.get("nodes") or []:
        if node.get("id") == node_id:
            return node
    return None


def _table_output_port(node_type: str) -> str | None:
    spec = get_spec(node_type)
    if not spec:
        return None
    for port in spec.outputs:
        if port.type == "table":
            return port.id
    return None


def _upstream_table_edge(graph: dict, node_id: str, target_handle: str | None = None) -> dict | None:
    edges = graph.get("edges") or []
    candidates = [e for e in edges if e.get("target") == node_id]
    if target_handle:
        exact = [
            e
            for e in candidates
            if (e.get("targetHandle") or e.get("target_handle")) == target_handle
        ]
        if exact:
            candidates = exact
    for edge in candidates:
        handle = edge.get("targetHandle") or edge.get("target_handle") or ""
        if "table" in handle or handle in ("input", "table_in", ""):
            return edge
    return candidates[0] if candidates else None


def _as_col_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [p.strip() for p in value.split(",") if p.strip()]
    return []


def _parse_join_suffixes(raw: Any) -> tuple[str, str]:
    text = (str(raw) if raw is not None else "_x,_y").strip() or "_x,_y"
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 1:
        return parts[0] or "_x", "_y"
    return parts[0] or "_x", parts[1] or "_y"


def merge_join_schemas(
    left: TableSchema,
    right: TableSchema,
    *,
    left_on: list[str] | None = None,
    right_on: list[str] | None = None,
    suffixes: tuple[str, str] = ("_x", "_y"),
) -> TableSchema:
    """Approximate pandas merge column layout for pre-run inspector."""
    left_keys = _as_col_list(left_on)
    right_keys = _as_col_list(right_on)
    if left_keys and not right_keys:
        right_keys = list(left_keys)
    if right_keys and not left_keys:
        left_keys = list(right_keys)

    # Same-name keys collapse to a single column (pandas default).
    shared_keys = {
        lk for lk, rk in zip(left_keys, right_keys) if lk == rk
    }
    left_names = {c.name for c in left.columns}
    right_names = {c.name for c in right.columns}
    left_sfx, right_sfx = suffixes

    cols: list[Column] = []
    used: set[str] = set()

    for col in left.columns:
        name = col.name
        if name in right_names and name not in shared_keys:
            name = f"{col.name}{left_sfx}"
        cols.append(col if name == col.name else replace(col, name=name))
        used.add(name)

    for col in right.columns:
        if col.name in shared_keys:
            continue
        name = col.name
        if col.name in left_names:
            name = f"{col.name}{right_sfx}"
        if name in used:
            name = f"{col.name}{right_sfx}"
            n = 2
            while name in used:
                name = f"{col.name}{right_sfx}{n}"
                n += 1
        cols.append(col if name == col.name else replace(col, name=name))
        used.add(name)

    return TableSchema(
        columns=tuple(cols),
        row_count=max(left.row_count, right.row_count),
    )


def resolve_node_output_schema(
    graph: dict,
    node_id: str,
    *,
    run_paths: dict[str, Any] | None = None,
) -> TableSchema | None:
    """Schema of a node's own table output (probe file_input, else run artifact)."""
    node = _find_node(graph, node_id)
    if not node:
        return None
    node_type = node.get("type") or _node_data(node).get("nodeType") or ""
    params = _node_params(node)

    if node_type == "file_input":
        path = params.get("path")
        if path:
            return probe_file_schema(path)
        return None

    if not _table_output_port(node_type):
        return None

    if run_paths and node_id in run_paths:
        raw = run_paths[node_id]
        if isinstance(raw, dict):
            for key in ("table_out", "matched", "input", "df"):
                if key in raw:
                    schema = schema_from_artifact(raw[key])
                    if schema:
                        return schema
            for path in raw.values():
                schema = schema_from_artifact(path)
                if schema:
                    return schema
        else:
            return schema_from_artifact(raw)

    # Pre-run: synthesize Join output so downstream pickers see merged columns.
    if node_type == "join":
        inputs = resolve_table_input_schemas(graph, node_id, run_paths=run_paths)
        left = inputs.get("left")
        right = inputs.get("right")
        if left is not None and right is not None:
            return merge_join_schemas(
                left,
                right,
                left_on=_as_col_list(params.get("left_on")),
                right_on=_as_col_list(params.get("right_on")),
                suffixes=_parse_join_suffixes(params.get("suffixes")),
            )
        return left or right

    return None


def _first_table_input_handle(node_type: str) -> str | None:
    spec = get_spec(node_type)
    if not spec:
        return None
    for port in spec.inputs:
        if port.type == "table":
            return port.id
    return None


def resolve_upstream_schema(
    graph: dict,
    node_id: str,
    *,
    target_handle: str | None = None,
    run_paths: dict[str, Any] | None = None,
) -> tuple[TableSchema | None, str | None, str | None]:
    """Return (schema, source_node_id, source_port).

    Walks the upstream table chain so intermediate nodes (e.g. ai_clean → filter)
    can still expose columns before they have been executed — typically by probing
    the originating file_input.
    """
    visited: set[str] = set()
    current_id: str | None = node_id
    handle = target_handle
    first_source_id: str | None = None
    first_source_port: str | None = None

    while current_id and current_id not in visited:
        visited.add(current_id)
        edge = _upstream_table_edge(graph, current_id, handle)
        if not edge:
            break
        source_id = edge.get("source")
        if not source_id:
            break
        source = _find_node(graph, source_id)
        source_type = ""
        if source:
            source_type = source.get("type") or _node_data(source).get("nodeType") or ""
        source_port = (
            edge.get("sourceHandle")
            or edge.get("source_handle")
            or _table_output_port(source_type)
        )
        if first_source_id is None:
            first_source_id = source_id
            first_source_port = source_port

        if run_paths and source_id in run_paths:
            raw = run_paths[source_id]
            if isinstance(raw, dict) and source_port and source_port in raw:
                schema = schema_from_artifact(raw[source_port])
                if schema:
                    return schema, source_id, source_port

        schema = resolve_node_output_schema(graph, source_id, run_paths=run_paths)
        if schema:
            return schema, source_id, source_port

        # No schema on this hop — keep walking toward the data origin.
        current_id = source_id
        handle = _first_table_input_handle(source_type)

    return None, first_source_id, first_source_port


def resolve_table_input_schemas(
    graph: dict,
    node_id: str,
    *,
    run_paths: dict[str, Any] | None = None,
) -> dict[str, TableSchema]:
    """Schema for each table input port on a node (e.g. join left/right)."""
    node = _find_node(graph, node_id)
    if not node:
        return {}
    node_type = node.get("type") or _node_data(node).get("nodeType") or ""
    spec = get_spec(node_type)
    if not spec:
        return {}
    out: dict[str, TableSchema] = {}
    for port in spec.inputs:
        if port.type != "table":
            continue
        schema, _, _ = resolve_upstream_schema(
            graph, node_id, target_handle=port.id, run_paths=run_paths
        )
        if schema is not None:
            out[port.id] = schema
    return out


def selected_columns_from_params(params: dict[str, Any] | None) -> list[str]:
    if not params:
        return []
    cols = params.get("columns")
    selected: list[str] = []
    if isinstance(cols, list):
        selected.extend(str(c) for c in cols if c)
    elif isinstance(cols, str) and cols.strip():
        selected.extend(p.strip() for p in cols.split(",") if p.strip())
    for key in ("x", "y", "color", "by", "left_on", "right_on", "values"):
        val = params.get(key)
        if isinstance(val, list):
            for item in val:
                s = str(item).strip()
                if s and s not in selected:
                    selected.append(s)
        elif isinstance(val, str) and val and val not in selected:
            selected.append(val)
    return selected
