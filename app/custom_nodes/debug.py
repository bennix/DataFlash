"""Dry-run a custom node transform against sample CSV / parquet."""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from app.sandbox.runner import run_sandboxed
from app.schema import infer_schema, schema_public

from .loader import (
    full_type,
    node_dir,
    params_preamble,
    validate_id,
    validate_package_dir,
)


def _load_frame(*, csv_text: str | None, path: str | None) -> pd.DataFrame:
    if csv_text and csv_text.strip():
        return pd.read_csv(io.StringIO(csv_text))
    if path:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")
        ext = p.suffix.lower()
        if ext == ".csv":
            return pd.read_csv(p)
        if ext in (".xlsx", ".xls"):
            return pd.read_excel(p)
        if ext == ".parquet":
            return pd.read_parquet(p)
        if ext == ".json":
            return pd.read_json(p)
        raise ValueError("调试输入仅支持 CSV / Excel / JSON / Parquet")
    raise ValueError("请提供 csv_text 或 path 作为调试输入")


def debug_custom_node(
    instance_path: str | Path,
    custom_id: str,
    *,
    csv_text: str | None = None,
    path: str | None = None,
    params: dict[str, Any] | None = None,
    preview_rows: int = 20,
) -> dict[str, Any]:
    custom_id = validate_id(custom_id)
    package_dir = node_dir(instance_path, custom_id)
    meta, code = validate_package_dir(package_dir)
    result_kind = str(meta.get("result_kind") or "table")
    params = params or {}
    is_ai = bool(meta.get("is_ai"))

    df = _load_frame(csv_text=csv_text, path=path)

    if is_ai:
        # AI custom nodes have no fixed transform; dry-run via mock generator.
        from app.ai.client import mock_generate

        prompt_file = package_dir / "prompt.md"
        intent = str(params.get("intent") or params.get("ai_intent") or "")
        if prompt_file.is_file():
            hint = prompt_file.read_text(encoding="utf-8").strip()
            if hint:
                intent = f"{hint}\n\n用户意图：{intent}" if intent else hint
        mock_params = {**params, "intent": intent}
        generated = mock_generate(full_type(custom_id), mock_params, df)
        code = generated.get("code") or "result = df"
        full_code = code
    else:
        if not code.strip():
            raise ValueError("该自定义节点没有 transform.py，无法调试")
        full_code = params_preamble(params) + code

    with tempfile.TemporaryDirectory(prefix="dataflash-cdebug-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / "input.parquet"
        df.to_parquet(src)
        suffix = {
            "table": ".parquet",
            "figure": ".figure.json",
            "stats": ".json",
            "text": ".md",
        }.get(result_kind, ".parquet")
        out = tmp_path / f"output{suffix}"
        result_var = "fig" if result_kind == "figure" else "result"
        sandbox_kind = result_kind if result_kind in ("table", "figure") else "stats"
        result = run_sandboxed(
            code=full_code,
            input_paths={"df": str(src)},
            output_path=out,
            result_var=result_var,
            result_kind=sandbox_kind,
            profile="ai",
            timeout=30,
        )
        payload: dict[str, Any] = {
            "ok": result.ok,
            "id": custom_id,
            "type": full_type(custom_id),
            "duration_ms": result.duration_ms,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": result.error,
            "traceback": result.traceback,
            "result_kind": result_kind,
            "input_rows": int(len(df)),
            "input_columns": [str(c) for c in df.columns],
        }
        if not result.ok:
            return payload

        if result_kind == "table":
            out_df = pd.read_parquet(out)
            sch = schema_public(infer_schema(out_df))
            payload["schema"] = sch
            payload["preview"] = {
                "columns": [str(c) for c in out_df.columns],
                "rows": out_df.head(preview_rows).fillna("").astype(str).to_dict(orient="records"),
                "row_count": int(len(out_df)),
            }
        elif result_kind == "figure":
            payload["preview"] = {
                "type": "figure",
                "json": json.loads(out.read_text(encoding="utf-8")),
            }
        else:
            text = out.read_text(encoding="utf-8")
            try:
                payload["preview"] = {"type": result_kind, "value": json.loads(text)}
            except json.JSONDecodeError:
                payload["preview"] = {"type": result_kind, "text": text[:4000]}
        return payload
