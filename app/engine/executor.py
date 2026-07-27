"""DAG executor with fingerprint cache and sandbox isolation (SPEC 3)."""

from __future__ import annotations

import json
import tempfile
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import app.nodes  # noqa: F401  — ensure node registry is populated
from app.registry import NodeSpec, get_spec
from app.sandbox import run_sandboxed

from app.schema import schema_public

from .artifacts import cached_artifact, load_output, load_schema_for, save_output
from .fingerprint import file_stamp, fingerprint
from .precheck import precheck
from .topology import CycleError, graph_order, layered_order

EventFn = Callable[[str, str | None, dict], None]
AIGenerator = Callable[..., dict]


class PrecheckError(RuntimeError):
    def __init__(self, problems: list[dict]):
        super().__init__(json.dumps(problems, ensure_ascii=False))
        self.problems = problems


def _node_params(node: dict) -> dict:
    return (node.get("data") or {}).get("params") or node.get("params") or {}


def _node_code(node: dict) -> str:
    data = node.get("data") or {}
    return data.get("code") or node.get("code") or ""


def _node_code_locked(node: dict) -> bool:
    data = node.get("data") or {}
    return bool(data.get("code_locked") or node.get("code_locked"))


def _upstream_for(node_id: str, edges: list[dict], spec: NodeSpec) -> list[dict]:
    ups = [e for e in edges if e["target"] == node_id]
    port_order = {p.id: i for i, p in enumerate(spec.inputs)}
    ups.sort(key=lambda e: port_order.get(e.get("targetHandle", ""), 999))
    return ups


def execute(
    graph: dict[str, Any],
    cache_dir: str | Path,
    event: EventFn,
    *,
    configured: bool = True,
    target: str | None = None,
    ai_generator: AIGenerator | None = None,
    concurrency: int = 4,
    cancelled: Callable[[], bool] | None = None,
    locale: str | None = None,
) -> tuple[str, dict[str, Any]]:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    problems = precheck(graph, configured, locale=locale)
    if any(p["level"] == "error" for p in problems):
        raise PrecheckError(problems)

    try:
        order, nodes, edges = graph_order(graph, target)
    except CycleError as exc:
        raise PrecheckError(
            [
                {
                    "node_id": None,
                    "level": "error",
                    "code": "cycle",
                    "message": "工作流包含环",
                    "fix_hint": "删除形成环的连线",
                    "cycle_nodes": exc.node_ids,
                }
            ]
        ) from exc

    run_id = str(uuid.uuid4())
    # outputs[node_id][port_id] = in-memory value OR we only keep paths
    output_paths: dict[str, dict[str, str]] = {}
    fps: dict[str, str] = {}
    # For preview convenience tests: node_id -> primary value
    primary_outputs: dict[str, Any] = {}

    layers = layered_order(order, edges)

    def run_node(node_id: str) -> None:
        if cancelled and cancelled():
            raise RuntimeError("运行已取消")
        node = nodes[node_id]
        spec = get_spec(node["type"])
        if not spec:
            raise RuntimeError(f"未知节点：{node['type']}")

        ups = _upstream_for(node_id, edges, spec)
        upstream_fps = [fps[e["source"]] for e in ups]
        # Schema fingerprints from upstream artifacts
        schema_parts = []
        for e in ups:
            paths = output_paths.get(e["source"], {})
            handle = e.get("sourceHandle")
            path = paths.get(handle) if handle else None
            if path is None and paths:
                path = next(iter(paths.values()))
            if path:
                schema = load_schema_for(path)
                if schema:
                    schema_parts.append(schema.fingerprint())

        stamp = ""
        params = _node_params(node)
        if node["type"] == "file_input" and params.get("path"):
            stamp = file_stamp(params["path"])

        code = _node_code(node)
        # Non-AI custom nodes always rebuild from transform.py + current params
        # so param changes are not frozen into cached node.data.code.
        if spec.custom and not spec.is_ai and spec.build_code is not None:
            code = spec.build_code(
                {"params": params, "node": node, "spec": spec, "code_locked": False}
            )
        elif not code and spec.build_code is not None:
            code = spec.build_code(
                {"params": params, "node": node, "spec": spec, "code_locked": False}
            )
        fp = fingerprint(
            node,
            upstream_fps,
            code=code,
            file_stamp=stamp,
            schema_fp="".join(schema_parts),
        )
        fps[node_id] = fp

        port_bases = {
            p.id: cache_dir / fp / p.id for p in (spec.outputs or [type("P", (), {"id": "out"})()])
        }
        # Cache hit if all output ports present
        if spec.outputs:
            hits = {p.id: cached_artifact(port_bases[p.id]) for p in spec.outputs}
            if all(hits.values()):
                output_paths[node_id] = {pid: str(path) for pid, path in hits.items()}
                primary = next(iter(hits.values()))
                primary_outputs[node_id] = load_output(primary)
                sch = load_schema_for(primary)
                event(
                    "node_cached",
                    node_id,
                    {
                        "path": str(primary),
                        "paths": {pid: str(path) for pid, path in hits.items()},
                        "fingerprint": fp,
                        "schema": schema_public(sch),
                    },
                )
                return
        else:
            # Preview / side-effect-only: still mark fingerprint
            sentinel = cache_dir / fp / "_done"
            if sentinel.exists():
                # Pass through first upstream
                if ups:
                    src_paths = output_paths.get(ups[0]["source"], {})
                    handle = ups[0].get("sourceHandle")
                    path = src_paths.get(handle) if handle in src_paths else next(iter(src_paths.values()), None)
                    if path:
                        output_paths[node_id] = {"input": path}
                        primary_outputs[node_id] = load_output(path)
                event("node_cached", node_id, {"fingerprint": fp})
                return

        event("node_start", node_id, {"fingerprint": fp})
        started = time.monotonic()
        try:
            # Load upstream values from disk (paths only in parent for large tables —
            # we load when needed for non-sandbox execute)
            upstream_values: dict[str, Any] = {}
            upstream_paths: dict[str, str] = {}
            for e in ups:
                src_paths = output_paths.get(e["source"], {})
                handle = e.get("sourceHandle")
                path = None
                if handle and handle in src_paths:
                    path = src_paths[handle]
                elif src_paths:
                    path = next(iter(src_paths.values()))
                if path:
                    target_handle = e.get("targetHandle") or "input"
                    upstream_paths[target_handle] = path
                    upstream_values[target_handle] = load_output(path)

            ctx = {
                "node": node,
                "params": params,
                "inputs": upstream_values,
                "input_paths": upstream_paths,
                "code": code,
                "code_locked": _node_code_locked(node),
                "ai_generator": ai_generator,
                "event": event,
                "node_id": node_id,
                "cache_dir": cache_dir,
                "spec": spec,
                "locale": locale,
            }

            event("node_log", node_id, {"message": "正在执行节点处理逻辑"})
            result = _execute_node(ctx)

            paths: dict[str, str] = {}
            port_ids = {p.id for p in spec.outputs}
            # A port-map dict must use known port ids. Raw figure/stats JSON dicts
            # (keys like data/layout) must NOT be treated as port maps.
            is_port_map = (
                isinstance(result, dict)
                and bool(result)
                and bool(port_ids)
                and set(result.keys()) <= port_ids
            )
            if is_port_map:
                for port_id, value in result.items():
                    if value is None:
                        continue
                    out_port = next(p for p in spec.outputs if p.id == port_id)
                    base = cache_dir / fp / port_id
                    path = save_output(value, base, kind=out_port.type)
                    paths[port_id] = str(path)
                    if port_id == spec.outputs[0].id:
                        primary_outputs[node_id] = value
            elif spec.outputs:
                port = spec.outputs[0]
                path = save_output(result, cache_dir / fp / port.id, kind=port.type)
                paths[port.id] = str(path)
                primary_outputs[node_id] = result
            else:
                # no outputs (preview): pass-through
                (cache_dir / fp).mkdir(parents=True, exist_ok=True)
                (cache_dir / fp / "_done").write_text("1", encoding="utf-8")
                if ups and upstream_paths:
                    first = next(iter(upstream_paths.values()))
                    paths["input"] = first
                    primary_outputs[node_id] = load_output(first)

            output_paths[node_id] = paths
            schema_payload = None
            for path in paths.values():
                sch = load_schema_for(path)
                if sch is not None:
                    schema_payload = schema_public(sch)
                    break
            event(
                "node_done",
                node_id,
                {
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "path": next(iter(paths.values()), None),
                    "paths": paths,
                    "fingerprint": fp,
                    "schema": schema_payload,
                },
            )
        except Exception as exc:
            event(
                "node_error",
                node_id,
                {"message": str(exc), "traceback": traceback.format_exc()},
            )
            raise

    for layer in layers:
        # Parallel AI calls to ZenMux often hit connection/TLS flakes; keep AI nodes serial.
        ai_ids = [
            nid
            for nid in layer
            if (spec := get_spec((nodes[nid].get("type") or ""))) and spec.is_ai
        ]
        if len(layer) == 1 or concurrency <= 1 or len(ai_ids) >= 1:
            for nid in layer:
                run_node(nid)
        else:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(layer))) as pool:
                futures = {pool.submit(run_node, nid): nid for nid in layer}
                for fut in as_completed(futures):
                    fut.result()  # propagate errors

    event("run_done", None, {"run_id": run_id})
    return run_id, primary_outputs


def _execute_node(ctx: dict) -> Any:
    spec: NodeSpec = ctx["spec"]
    if spec.execute is not None:
        return spec.execute(ctx)

    # AI / sandboxed code path via build_code
    if spec.build_code is not None or spec.is_ai:
        return _execute_ai_or_code(ctx)

    raise RuntimeError(f"节点 {spec.type} 尚未实现")


def _execute_ai_or_code(ctx: dict) -> Any:
    spec: NodeSpec = ctx["spec"]
    event = ctx["event"]
    node_id = ctx["node_id"]
    code = ctx["code"]
    params = ctx["params"]
    inputs = ctx["inputs"]

    # Acquire code: non-AI custom build_code → locked/node → AI generate
    if spec.custom and not spec.is_ai and spec.build_code is not None:
        code = spec.build_code(ctx)
    elif not code:
        if spec.build_code is not None:
            code = spec.build_code(ctx)
            ctx["node"].setdefault("data", {})["code"] = code
        elif spec.is_ai:
            if not ctx["ai_generator"]:
                raise RuntimeError(f"{spec.label} 没有可执行代码，且 AI 生成器不可用")
            table = None
            for v in inputs.values():
                if isinstance(v, pd.DataFrame):
                    table = v
                    break
            event(
                "node_log",
                node_id,
                {"message": f"正在请求模型 {params.get('model', '默认模型')} 生成代码"},
            )
            ai_params = dict(params)
            if getattr(spec, "ai_prompt_hint", ""):
                hint = spec.ai_prompt_hint.strip()
                user_intent = str(ai_params.get("intent") or ai_params.get("ai_intent") or "")
                ai_params["intent"] = (
                    f"{hint}\n\n用户意图：{user_intent}" if user_intent else hint
                )
            generated = ctx["ai_generator"](spec.type, ai_params, table)
            code = generated["code"]
            event("node_log", node_id, {"message": generated.get("explanation", "AI 代码已生成")})
            ctx["node"].setdefault("data", {})["code"] = code
            if generated.get("steps") is not None:
                ctx["node"]["data"]["steps"] = generated["steps"]
        else:
            raise RuntimeError(f"{spec.label} 没有可执行代码")
    elif spec.is_ai and not ctx["code_locked"] and not code:
        pass  # unreachable; kept for clarity

    # Heal loop (AI nodes only)
    last_error = None
    last_tb = None
    max_attempts = 3 if spec.is_ai else 1
    for attempt in range(max_attempts):  # initial + up to 2 heals for AI
        if attempt > 0:
            if not spec.is_ai or not ctx["ai_generator"]:
                break
            event("node_log", node_id, {"message": f"正在请求 AI 修复代码（第 {attempt} 次）"})
            table = next((v for v in inputs.values() if isinstance(v, pd.DataFrame)), None)
            fix_params = {
                **params,
                "intent": params.get("intent", ""),
                "_heal_traceback": last_tb,
                "_heal_code": code,
            }
            if getattr(spec, "ai_prompt_hint", ""):
                hint = spec.ai_prompt_hint.strip()
                user_intent = str(fix_params.get("intent") or "")
                fix_params["intent"] = (
                    f"{hint}\n\n用户意图：{user_intent}" if user_intent else hint
                )
            generated = ctx["ai_generator"](spec.type, fix_params, table)
            code = generated["code"]
            ctx["node"].setdefault("data", {})["code"] = code

        out_kind = spec.outputs[0].type if spec.outputs else "table"
        result_var = {"figure": "fig", "stats": "result", "text": "result", "table": "result"}.get(
            out_kind, "result"
        )
        # Map input paths for sandbox: use df for first table
        input_paths: dict[str, str] = {}
        for handle, path in ctx["input_paths"].items():
            if str(path).endswith(".parquet"):
                input_paths[handle if handle != "table_in" else "df"] = path
        if not input_paths and ctx["input_paths"]:
            # write temp parquet from in-memory if needed
            pass

        if out_kind == "table" and input_paths:
            with tempfile.TemporaryDirectory(dir=ctx["cache_dir"], prefix="dataflash-") as tmp:
                out = Path(tmp) / "output.parquet"
                # normalize keys to df
                paths = input_paths
                if "df" not in paths:
                    first = next(iter(paths))
                    paths = {"df": paths[first]}
                result = run_sandboxed(
                    code=code,
                    input_paths=paths,
                    output_path=out,
                    result_var=result_var,
                    result_kind="table",
                    profile=spec.code_profile,
                )
                if result.ok:
                    if result.stdout:
                        event("node_log", node_id, {"message": result.stdout[-500:]})
                    return pd.read_parquet(out)
                last_error = result.error
                last_tb = result.traceback
                event("node_log", node_id, {"message": f"执行失败：{result.error}"})
                continue

        # Non-table or no parquet path: run with temp inputs written
        with tempfile.TemporaryDirectory(dir=ctx["cache_dir"], prefix="dataflash-") as tmp:
            paths = {}
            for handle, value in inputs.items():
                if isinstance(value, pd.DataFrame):
                    p = Path(tmp) / f"{handle}.parquet"
                    value.to_parquet(p)
                    paths["df" if handle in ("table_in", "input", "df") else handle] = str(p)
            if not paths:
                raise RuntimeError("AI 节点缺少表格输入")
            if "df" not in paths:
                paths = {"df": next(iter(paths.values()))}
            suffix = { "figure": ".figure.json", "stats": ".json", "text": ".md" }.get(out_kind, ".parquet")
            out = Path(tmp) / f"output{suffix}"
            result = run_sandboxed(
                code=code,
                input_paths=paths,
                output_path=out,
                result_var="fig" if out_kind == "figure" else "result",
                result_kind=out_kind if out_kind in ("table", "figure") else "stats",
                profile=spec.code_profile,
            )
            if result.ok:
                return load_output(out)
            last_error = result.error
            last_tb = result.traceback
            continue

    raise RuntimeError(
        f"{spec.label} 执行失败（已自愈 {attempt} 次）：{last_error}"
    )
