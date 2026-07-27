"""Deterministic table Join / Merge (two inputs)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.registry import Message, MessageCatalog, NodeSpec, Port, param, register

JOIN_HOW = ("inner", "left", "right", "outer", "cross")
JOIN_VALIDATE = ("", "one_to_one", "one_to_many", "many_to_one", "many_to_many")

# Soft guard: many-to-many blow-ups still succeed but log a warning via return meta.
ROW_BLOWUP_FACTOR = 10


def _as_col_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [p.strip() for p in value.split(",") if p.strip()]
    return []


def _parse_suffixes(raw: Any) -> tuple[str, str]:
    text = (str(raw) if raw is not None else "_x,_y").strip() or "_x,_y"
    parts = [p.strip() for p in text.split(",")]
    if len(parts) == 1:
        return parts[0] or "_x", "_y"
    left_sfx, right_sfx = parts[0], parts[1]
    return left_sfx or "_x", right_sfx or "_y"


def join_frames(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    how: str = "inner",
    left_on: list[str] | None = None,
    right_on: list[str] | None = None,
    suffixes: tuple[str, str] = ("_x", "_y"),
    validate: str | None = None,
    indicator: bool = False,
) -> tuple[pd.DataFrame, list[str]]:
    """Merge two frames. Returns (result, warning_messages)."""
    how = (how or "inner").lower().strip()
    if how not in JOIN_HOW:
        raise ValueError(f"不支持的连接方式：{how}；可选：{', '.join(JOIN_HOW)}")

    warnings: list[str] = []
    left_keys = list(left_on or [])
    right_keys = list(right_on or [])

    merge_kwargs: dict[str, Any] = {
        "how": how,
        "suffixes": suffixes,
        "indicator": indicator,
        "copy": True,
    }
    if validate:
        merge_kwargs["validate"] = validate

    if how == "cross":
        if left_keys or right_keys:
            warnings.append("交叉连接忽略连接键")
        # pandas cross ignores on/left_on/right_on
        if len(left) * len(right) > max(len(left), len(right), 1) * ROW_BLOWUP_FACTOR:
            warnings.append(
                f"交叉连接可能产生 {len(left) * len(right)} 行，请确认是否符合预期"
            )
    else:
        if not left_keys and not right_keys:
            raise ValueError("请指定左表/右表连接键（或改用 cross）")
        if left_keys and not right_keys:
            right_keys = list(left_keys)
        if right_keys and not left_keys:
            left_keys = list(right_keys)
        if len(left_keys) != len(right_keys):
            raise ValueError(
                f"左右连接键数量不一致：左 {len(left_keys)} 个，右 {len(right_keys)} 个"
            )
        missing_l = [c for c in left_keys if c not in left.columns]
        missing_r = [c for c in right_keys if c not in right.columns]
        if missing_l:
            raise ValueError(f"左表缺少连接键：{', '.join(missing_l)}")
        if missing_r:
            raise ValueError(f"右表缺少连接键：{', '.join(missing_r)}")
        merge_kwargs["left_on"] = left_keys
        merge_kwargs["right_on"] = right_keys

    try:
        out = pd.merge(left, right, **merge_kwargs)
    except pd.errors.MergeError as exc:
        raise ValueError(f"连接校验失败：{exc}") from exc
    except Exception as exc:
        raise ValueError(f"连接失败：{exc}") from exc

    base = max(len(left), len(right), 1)
    if how != "cross" and len(out) > base * ROW_BLOWUP_FACTOR:
        warnings.append(
            f"结果 {len(out)} 行，约为较大输入的 {len(out) / base:.1f} 倍，可能存在多对多膨胀"
        )
    return out, warnings


def _execute(ctx: dict):
    left = ctx["inputs"].get("left")
    right = ctx["inputs"].get("right")
    if not isinstance(left, pd.DataFrame):
        raise RuntimeError("Join 需要左表输入（left）")
    if not isinstance(right, pd.DataFrame):
        raise RuntimeError("Join 需要右表输入（right）")

    params = ctx["params"]
    how = (params.get("how") or "inner").lower()
    left_on = _as_col_list(params.get("left_on"))
    right_on = _as_col_list(params.get("right_on"))
    suffixes = _parse_suffixes(params.get("suffixes"))
    validate = (params.get("validate") or "").strip() or None
    indicator = bool(params.get("indicator"))

    out, warnings = join_frames(
        left,
        right,
        how=how,
        left_on=left_on,
        right_on=right_on,
        suffixes=suffixes,
        validate=validate,
        indicator=indicator,
    )

    event = ctx["event"]
    node_id = ctx["node_id"]
    event(
        "node_log",
        node_id,
        {
            "message": (
                f"Join {how}：左 {len(left)} × 右 {len(right)} → {len(out)} 行，"
                f"{len(out.columns)} 列"
            )
        },
    )
    for msg in warnings:
        event("node_log", node_id, {"message": f"注意：{msg}"})
    return {"table_out": out}


SPEC = register(
    NodeSpec(
        type="join",
        category="transform",
        label="Join",
        label_en="Join",
        description="按键连接两张表（inner / left / right / outer / cross）",
        keywords=("join", "merge", "连接", "合并", "关联"),
        icon="join",
        priority=80,
        inputs=[
            Port("left", "table", "左表"),
            Port("right", "table", "右表"),
        ],
        outputs=[Port("table_out", "table", "表格", default=True)],
        params_schema=[
            param(
                "how",
                "select",
                False,
                "连接方式",
                options=list(JOIN_HOW),
            ),
            param(
                "left_on",
                "columns",
                False,
                "左表连接键",
                port="left",
            ),
            param(
                "right_on",
                "columns",
                False,
                "右表连接键",
                port="right",
            ),
            param(
                "suffixes",
                "string",
                False,
                "重名列后缀（左,右）",
            ),
            param(
                "validate",
                "select",
                False,
                "键关系校验",
                options=list(JOIN_VALIDATE),
            ),
            param("indicator", "boolean", False, "添加 _merge 匹配标记列"),
        ],
        is_ai=False,
        code_profile="trusted",
        messages=MessageCatalog(
            error={
                "bad_join": Message(
                    "bad_join", "连接失败：{err}", "检查连接键、连接方式与键唯一性校验"
                ),
            },
        ),
        execute=_execute,
    )
)
