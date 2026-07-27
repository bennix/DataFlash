"""Deterministic GroupBy / Aggregate."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.registry import Message, MessageCatalog, NodeSpec, Port, param, register

AGG_OPTIONS = (
    "count",
    "size",
    "sum",
    "mean",
    "median",
    "min",
    "max",
    "std",
    "nunique",
    "first",
    "last",
)

# Aggregations that require numeric-like columns (others still attempted; pandas may coerce).
_NUMERIC_AGGS = frozenset({"sum", "mean", "median", "std", "min", "max"})


def _as_col_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [p.strip() for p in value.split(",") if p.strip()]
    return []


def _as_agg_list(value: Any) -> list[str]:
    items = _as_col_list(value)
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key not in AGG_OPTIONS:
            raise ValueError(f"不支持的聚合：{item}；可选：{', '.join(AGG_OPTIONS)}")
        if key not in out:
            out.append(key)
    return out


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            "_".join(str(part) for part in col if str(part) != "")
            for col in df.columns.to_list()
        ]
    return df


def groupby_frame(
    df: pd.DataFrame,
    *,
    by: list[str],
    values: list[str] | None = None,
    aggs: list[str] | None = None,
    dropna: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    """Group and aggregate. Returns (result, warning_messages)."""
    warnings: list[str] = []
    by = list(by or [])
    values = list(values or [])
    aggs = list(aggs or [])

    if not by:
        raise ValueError("请至少选择一个分组字段")
    missing_by = [c for c in by if c not in df.columns]
    if missing_by:
        raise ValueError(f"分组字段不存在：{', '.join(missing_by)}")
    missing_vals = [c for c in values if c not in df.columns]
    if missing_vals:
        raise ValueError(f"聚合字段不存在：{', '.join(missing_vals)}")
    overlap = [c for c in values if c in by]
    if overlap:
        raise ValueError(f"聚合字段不能与分组字段重复：{', '.join(overlap)}")

    if not aggs:
        aggs = ["size"] if not values else ["mean"]

    # size / count-only path when no value columns
    if not values:
        grouped = df.groupby(by, dropna=dropna, observed=True, sort=True)
        if aggs == ["size"] or set(aggs) <= {"size", "count"}:
            name = "count" if "count" in aggs and "size" not in aggs else "size"
            if "count" in aggs and "size" in aggs:
                out = grouped.size().reset_index(name="size")
                # count without values ≈ size
                out["count"] = out["size"]
                warnings.append("未选聚合字段时 count 与 size 均为组内行数")
            else:
                out = grouped.size().reset_index(name=name)
            return out, warnings
        raise ValueError("未选择聚合字段时，仅支持 size / count")

    # Drop size from column aggs — applied separately if requested
    col_aggs = [a for a in aggs if a != "size"]
    if not col_aggs:
        col_aggs = ["count"]

    numeric_cols = set(df.select_dtypes(include="number").columns)
    for agg in col_aggs:
        if agg in _NUMERIC_AGGS:
            bad = [c for c in values if c not in numeric_cols]
            if bad:
                warnings.append(
                    f"聚合「{agg}」遇到非数值列 {', '.join(bad)}，将尝试转换或产生空值"
                )

    work_cols = list(dict.fromkeys(by + values))
    work = df.loc[:, work_cols]
    grouped = work.groupby(by, dropna=dropna, observed=True, sort=True)

    agg_map: dict[str, list[str]] = {col: list(col_aggs) for col in values}
    try:
        out = grouped.agg(agg_map)
    except Exception as exc:
        raise ValueError(f"分组聚合失败：{exc}") from exc

    out = _flatten_columns(out).reset_index()

    if "size" in aggs:
        sizes = (
            df.groupby(by, dropna=dropna, observed=True, sort=True)
            .size()
            .reset_index(name="size")
        )
        out = out.merge(sizes, on=by, how="left")

    return out, warnings


def _execute(ctx: dict):
    df = ctx["inputs"].get("table_in")
    if not isinstance(df, pd.DataFrame):
        raise RuntimeError("GroupBy 需要表格输入")

    params = ctx["params"]
    by = _as_col_list(params.get("by"))
    values = _as_col_list(params.get("values"))
    aggs = _as_agg_list(params.get("aggs"))
    dropna = params.get("dropna")
    if dropna is None:
        dropna = True
    else:
        dropna = bool(dropna)

    out, warnings = groupby_frame(
        df, by=by, values=values, aggs=aggs, dropna=dropna
    )

    event = ctx["event"]
    node_id = ctx["node_id"]
    event(
        "node_log",
        node_id,
        {
            "message": (
                f"GroupBy：按 {', '.join(by)} 得到 {len(out)} 组 / {len(out.columns)} 列"
            )
        },
    )
    for msg in warnings:
        event("node_log", node_id, {"message": f"注意：{msg}"})
    return {"table_out": out}


SPEC = register(
    NodeSpec(
        type="groupby",
        category="transform",
        label="GroupBy",
        label_en="GroupBy",
        description="按字段分组并聚合（sum / mean / count 等）",
        keywords=("groupby", "aggregate", "分组", "聚合", "汇总"),
        icon="groupby",
        priority=85,
        inputs=[Port("table_in", "table", "表格")],
        outputs=[Port("table_out", "table", "表格", default=True)],
        params_schema=[
            param("by", "columns", True, "分组字段"),
            param("values", "columns", False, "聚合字段"),
            param(
                "aggs",
                "multiselect",
                False,
                "聚合方式",
                options=list(AGG_OPTIONS),
            ),
            param("dropna", "boolean", False, "丢弃分组键为空的行"),
        ],
        is_ai=False,
        code_profile="trusted",
        messages=MessageCatalog(
            error={
                "bad_groupby": Message(
                    "bad_groupby", "分组失败：{err}", "检查分组字段与聚合方式"
                ),
            },
        ),
        execute=_execute,
    )
)
