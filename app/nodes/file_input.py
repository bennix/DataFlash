from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.registry import Message, MessageCatalog, NodeSpec, Port, param, register

MAX_BYTES = 200 * 1024 * 1024
MAX_ROWS = 500_000


def _execute(ctx: dict):
    params = ctx["params"]
    path = Path(params["path"])
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在：{path}")

    size = path.stat().st_size
    policy = params.get("sample_policy") or None
    if policy == "":
        policy = None
    n = params.get("sample_n") or params.get("limit")
    limit = int(n) if n else None

    ext = path.suffix.lower().lstrip(".")
    event = ctx["event"]
    node_id = ctx["node_id"]

    if ext == "csv":
        pd.read_csv(path, nrows=0)
        if size > MAX_BYTES and not policy:
            raise RuntimeError("文件超过 200MB；请选择采样策略")
        if policy == "random":
            df = pd.read_csv(path)
            if limit and len(df) > limit:
                df = df.sample(n=limit, random_state=42)
        else:
            df = pd.read_csv(path, nrows=limit)
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(path, nrows=limit)
    elif ext == "json":
        df = pd.read_json(path)
        if limit:
            df = df.head(limit)
    else:
        raise ValueError("仅支持 CSV、XLSX、JSON")

    if len(df) > MAX_ROWS and policy != "full":
        if not policy:
            raise RuntimeError("预估超过 50 万行；请选择采样策略")
        if policy == "head":
            df = df.head(limit or MAX_ROWS)
        elif policy == "random":
            df = df.sample(n=min(limit or MAX_ROWS, len(df)), random_state=42)

    if policy:
        event("node_log", node_id, {"message": f"已按「{policy}」策略读取 {len(df)} 行"})
    else:
        event("node_log", node_id, {"message": f"已读取 {len(df)} 行 × {len(df.columns)} 列"})
    return {"table_out": df}


SPEC = register(
    NodeSpec(
        type="file_input",
        category="input",
        label="文件输入",
        label_en="File Input",
        description="从 CSV / Excel / JSON 读取表格数据",
        keywords=("file", "csv", "excel", "json", "导入", "上传"),
        icon="file",
        priority=10,
        inputs=[],
        outputs=[Port("table_out", "table", "表格", default=True)],
        params_schema=[
            param("path", "file", True, "数据文件"),
            param("limit", "number", False, "读取行数"),
            param(
                "sample_policy",
                "select",
                False,
                "采样策略",
                options=["", "head", "random", "full"],
            ),
            param("sample_n", "number", False, "采样行数 N"),
        ],
        messages=MessageCatalog(
            error={
                "missing_file": Message("missing_file", "输入文件不存在", "重新选择文件"),
            },
            warning={
                "file_too_large": Message("file_too_large", "文件超过 200MB", "选择采样策略"),
            },
            info={
                "sampled": Message("sampled", "已按「{policy}」策略采样 {n} 行"),
            },
        ),
        code_profile="trusted",
        execute=_execute,
    )
)
