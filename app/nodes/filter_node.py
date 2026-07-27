from __future__ import annotations

import pandas as pd

from app.registry import Message, MessageCatalog, NodeSpec, Port, param, register
from app.sandbox import run_sandboxed


def _execute(ctx: dict):
    params = ctx["params"]
    df = ctx["inputs"].get("table_in")
    if not isinstance(df, pd.DataFrame):
        raise RuntimeError("Filter 需要表格输入")

    expr = (params.get("expression") or "").strip()
    ai_intent = (params.get("ai_intent") or "").strip()
    event = ctx["event"]
    node_id = ctx["node_id"]

    if expr:
        # Trusted template — still run in sandbox for isolation
        code = (
            f"result = df.query({expr!r}, engine='python')\n"
            "unmatched = df.loc[~df.index.isin(result.index)]\n"
        )
        # Actually sandbox only returns one result_var. Run locally for dual output
        # Dual-output: execute in parent with validated template is OK for trusted filter expr
        # Prefer sandbox single matched, compute unmatched in parent from index
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory(dir=ctx["cache_dir"], prefix="filter-") as tmp:
            src = Path(tmp) / "in.parquet"
            out = Path(tmp) / "out.parquet"
            df.to_parquet(src)
            code_matched = f"result = df.query({expr!r}, engine='python')"
            result = run_sandboxed(
                code=code_matched,
                input_paths={"df": str(src)},
                output_path=out,
                profile="ai",  # expression still shouldn't do IO
            )
            if not result.ok:
                raise RuntimeError(result.error)
            matched = pd.read_parquet(out)
        unmatched = df.loc[~df.index.isin(matched.index)]
        event("node_log", node_id, {"message": f"筛选：{len(matched)} 匹配 / {len(unmatched)} 未匹配"})
        return {"matched": matched, "unmatched": unmatched}

    if ai_intent or ctx.get("code"):
        # Fall through to AI code path by raising to use build — actually call AI generator
        code = ctx["code"]
        if not code:
            gen = ctx["ai_generator"]
            if not gen:
                raise RuntimeError("自然语言筛选需要 AI 生成器")
            generated = gen("filter", {**params, "intent": ai_intent}, df)
            code = generated["code"]
            event("node_log", node_id, {"message": generated.get("explanation", "筛选代码已生成")})
            ctx["node"].setdefault("data", {})["code"] = code

        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory(dir=ctx["cache_dir"], prefix="filter-") as tmp:
            src = Path(tmp) / "in.parquet"
            out = Path(tmp) / "out.parquet"
            df.to_parquet(src)
            result = run_sandboxed(
                code=code,
                input_paths={"df": str(src)},
                output_path=out,
                profile="ai",
            )
            if not result.ok:
                raise RuntimeError(result.error)
            matched = pd.read_parquet(out)
        unmatched = df.loc[~df.index.isin(matched.index)]
        return {"matched": matched, "unmatched": unmatched}

    raise RuntimeError("请填写筛选表达式或自然语言筛选要求")


SPEC = register(
    NodeSpec(
        type="filter",
        category="transform",
        label="筛选",
        label_en="Filter",
        description="按表达式或自然语言筛选行；输出匹配与未匹配两表",
        keywords=("filter", "筛选", "query"),
        icon="filter",
        priority=100,
        inputs=[Port("table_in", "table", "表格")],
        outputs=[
            Port("matched", "table", "匹配", default=True),
            Port("unmatched", "table", "未匹配", required=False),
        ],
        params_schema=[
            param("columns", "columns", False, "涉及字段"),
            param("expression", "expression", False, "筛选表达式"),
            param("ai_intent", "textarea", False, "自然语言筛选要求"),
            param("model", "model", False, "AI 模型"),
        ],
        is_ai=True,
        code_profile="ai",
        messages=MessageCatalog(
            error={
                "bad_expression": Message("bad_expression", "筛选表达式无效：{err}", "检查列名与语法"),
            },
        ),
        execute=_execute,
    )
)
