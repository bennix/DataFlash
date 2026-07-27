"""REST + SSE API (SPEC 7.2)."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from . import store
from .ai import DEFAULT_MODELS, generate, mock_generate, summarize_dataframe
from .crypto import decrypt, encrypt
from .engine import PrecheckError, execute, load_output, precheck
from .nodes import NODES
from .i18n import pick, resolve_request_locale
from .registry import all_specs
from .schema import schema_public
from .schema_resolve import (
    resolve_node_output_schema,
    resolve_table_input_schemas,
    resolve_upstream_schema,
    selected_columns_from_params,
)

api = Blueprint("api", __name__)
runs: dict[str, dict] = {}


def init_app(app) -> None:
    store.init_db(app.config["DATABASE"])
    # Ensure nodes are registered
    from . import nodes as _nodes  # noqa: F401


def setting(name: str):
    with store.db(current_app.config["DATABASE"]) as con:
        row = con.execute("SELECT value_encrypted FROM settings WHERE key=?", (name,)).fetchone()
    return decrypt(row[0], current_app.config["SECRET_DIR"]) if row else None


def put_setting(name: str, value: str) -> None:
    with store.db(current_app.config["DATABASE"]) as con:
        con.execute(
            "INSERT OR REPLACE INTO settings VALUES(?,?,?)",
            (name, encrypt(value, current_app.config["SECRET_DIR"]), store.now()),
        )


def _request_locale(payload: dict | None = None) -> str:
    data = payload or {}
    return resolve_request_locale(
        explicit=data.get("locale") or request.args.get("locale"),
        accept_language=request.headers.get("Accept-Language"),
        stored=setting("locale"),
    )


@api.get("/nodes")
def nodes():
    locale = _request_locale()
    return jsonify([n.public(locale) for n in all_specs()])


@api.get("/examples")
def examples():
    from .examples import list_examples

    locale = _request_locale()
    return jsonify(list_examples(locale=locale))


@api.post("/examples/<example_id>/instantiate")
def instantiate_example(example_id: str):
    """Copy bundled dataset into instance/ and return a ready-to-run workflow graph."""
    from .examples import instantiate_example as materialize

    locale = _request_locale()
    try:
        payload = materialize(
            example_id, instance_path=current_app.instance_path, locale=locale
        )
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    created = store.create_workflow(
        current_app.config["DATABASE"],
        payload["title"],
        payload["graph"],
    )
    return jsonify(
        {
            "workflow": created,
            "title": payload["title"],
            "description": payload["description"],
            "dataset_path": payload["dataset_path"],
            "export_path": payload["export_path"],
        }
    ), 201


@api.get("/custom-nodes")
def custom_nodes_list():
    from .custom_nodes import list_installed

    return jsonify(list_installed(current_app.instance_path))


@api.get("/custom-nodes/sample")
def custom_nodes_sample():
    from .custom_nodes import sample_ai_zip_bytes, sample_zip_bytes

    which = (request.args.get("id") or "scale_numeric").strip().lower()
    try:
        if which in {"ai_flag_rows", "ai", "ai-flag-rows"}:
            data = sample_ai_zip_bytes()
            filename = "ai_flag_rows.zip"
        else:
            data = sample_zip_bytes()
            filename = "scale_numeric.zip"
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 404
    return Response(
        data,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )


@api.post("/custom-nodes/upload")
def custom_nodes_upload():
    locale = _request_locale()
    from .custom_nodes import install_from_files, install_from_zip

    try:
        zip_file = request.files.get("file") or request.files.get("zip")
        if zip_file and zip_file.filename:
            info = install_from_zip(current_app.instance_path, zip_file.read())
            return jsonify(info), 201

        manifest = request.files.get("manifest")
        transform = request.files.get("transform")
        if manifest and transform:
            info = install_from_files(
                current_app.instance_path,
                manifest_text=manifest.read().decode("utf-8"),
                transform_text=transform.read().decode("utf-8"),
            )
            return jsonify(info), 201

        # JSON body fallback: {manifest, transform}
        data = request.get_json(silent=True) or {}
        if data.get("manifest") and data.get("transform"):
            manifest_text = data["manifest"]
            transform_text = data["transform"]
            if isinstance(manifest_text, dict):
                manifest_text = json.dumps(manifest_text, ensure_ascii=False)
            info = install_from_files(
                current_app.instance_path,
                manifest_text=str(manifest_text),
                transform_text=str(transform_text),
            )
            return jsonify(info), 201
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        return jsonify(error=str(exc)), 400
    except zipfile.BadZipFile:
        return jsonify(
            error=pick(locale, "无效的 zip 文件", "Invalid zip file")
        ), 400

    return jsonify(
        error=pick(
            locale,
            "请上传 zip，或同时提供 manifest.json 与 transform.py",
            "Upload a zip, or both manifest.json and transform.py",
        )
    ), 400


@api.delete("/custom-nodes/<custom_id>")
def custom_nodes_delete(custom_id: str):
    from .custom_nodes import uninstall_custom_node

    try:
        uninstall_custom_node(current_app.instance_path, custom_id)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return ("", 204)


@api.post("/custom-nodes/<custom_id>/debug")
def custom_nodes_debug(custom_id: str):
    from .custom_nodes import debug_custom_node

    data = request.get_json(silent=True) or {}
    try:
        payload = debug_custom_node(
            current_app.instance_path,
            custom_id,
            csv_text=data.get("csv_text"),
            path=data.get("path"),
            params=data.get("params") if isinstance(data.get("params"), dict) else {},
            preview_rows=int(data.get("preview_rows") or 20),
        )
    except (ValueError, FileNotFoundError) as exc:
        return jsonify(error=str(exc)), 400
    status = 200 if payload.get("ok") else 422
    return jsonify(payload), status


@api.post("/upload")
def upload():
    locale = _request_locale()
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error=pick(locale, "请选择数据文件", "Please choose a data file")), 400
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls", ".json"}:
        return jsonify(
            error=pick(
                locale,
                "仅支持 CSV、Excel（.xlsx/.xls）和 JSON 文件",
                "Only CSV, Excel (.xlsx/.xls), and JSON are supported",
            )
        ), 415
    if request.content_length and request.content_length > 200 * 1024 * 1024:
        return jsonify(
            error=pick(
                locale,
                "文件超过 200MB；请先选择采样策略",
                "File exceeds 200MB; choose a sampling policy first",
            )
        ), 413
    directory = Path(current_app.instance_path) / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
    file.save(path)
    if path.stat().st_size > 200 * 1024 * 1024:
        path.unlink(missing_ok=True)
        return jsonify(
            error=pick(
                locale,
                "文件超过 200MB；请先选择采样策略",
                "File exceeds 200MB; choose a sampling policy first",
            )
        ), 413
    return jsonify(path=str(path), name=file.filename, size=path.stat().st_size), 201


@api.get("/workflows")
def workflows():
    return jsonify(store.list_workflows(current_app.config["DATABASE"]))


@api.post("/workflows")
def create_workflow():
    d = request.get_json() or {}
    locale = _request_locale(d)
    default_name = pick(locale, "未命名工作流", "Untitled workflow")
    return jsonify(
        store.create_workflow(
            current_app.config["DATABASE"], d.get("name", default_name), d.get("graph")
        )
    ), 201


@api.get("/workflows/<ident>")
def workflow(ident):
    locale = _request_locale()
    value = store.get_workflow(current_app.config["DATABASE"], ident)
    return (
        (jsonify(value), 200)
        if value
        else (jsonify(error=pick(locale, "未找到工作流", "Workflow not found")), 404)
    )


@api.put("/workflows/<ident>")
def save_workflow(ident):
    d = request.get_json() or {}
    locale = _request_locale(d)
    store.save_workflow(
        current_app.config["DATABASE"],
        ident,
        d.get("name", pick(locale, "未命名工作流", "Untitled workflow")),
        d.get("graph", {}),
    )
    return "", 204


@api.delete("/workflows/<ident>")
def delete_workflow(ident):
    locale = _request_locale()
    return ("", 204) if store.delete_workflow(current_app.config["DATABASE"], ident) else (
        jsonify(error=pick(locale, "未找到", "Not found")),
        404,
    )


@api.get("/workflows/<ident>/export")
def export_flow(ident):
    value = store.get_workflow(current_app.config["DATABASE"], ident)
    if not value:
        return jsonify(error="未找到"), 404
    graph = value["graph"]
    if "format_version" not in graph:
        graph = {**graph, "format_version": 2}
    # .flow.json package: name + graph
    return jsonify({"format": "dataflash.flow", "version": 2, "name": value["name"], "graph": graph})


@api.post("/workflows/<ident>/import")
def import_flow(ident):
    d = request.get_json() or {}
    graph = d.get("graph", d)
    store.save_workflow(
        current_app.config["DATABASE"],
        ident,
        d.get("name", "导入工作流"),
        graph,
    )
    return "", 204


@api.post("/workflows/import")
def import_new_workflow():
    """Create a new workflow from a .flow.json payload."""
    d = request.get_json() or {}
    graph = d.get("graph")
    if graph is None and ("nodes" in d or "edges" in d):
        graph = d
    if not isinstance(graph, dict):
        return jsonify(error="无效的工作流文件：缺少 graph"), 400
    if "format_version" not in graph:
        graph = {**graph, "format_version": 2}
    name = d.get("name") or "导入工作流"
    created = store.create_workflow(current_app.config["DATABASE"], name, graph)
    return jsonify(created), 201


@api.post("/precheck")
def check():
    d = request.get_json() or {}
    locale = _request_locale(d)
    configured = bool(setting("api_key")) or bool(current_app.config.get("AI_MOCK", False))
    problems = precheck(d.get("graph", {}), configured, locale=locale)
    status = 422 if any(p["level"] == "error" for p in problems) else 200
    return jsonify(problems), status


@api.post("/run")
def run():
    d = request.get_json() or {}
    graph = d.get("graph")
    if not graph and d.get("workflow_id"):
        wf = store.get_workflow(current_app.config["DATABASE"], d["workflow_id"])
        graph = wf and wf["graph"]
    api_key = setting("api_key")
    use_mock = bool(current_app.config.get("AI_MOCK", False))
    configured = bool(api_key) or use_mock
    locale = _request_locale(d)
    problems = precheck(graph or {}, configured, locale=locale)
    if any(p["level"] == "error" for p in problems):
        return jsonify(problems), 422

    run_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    done = threading.Event()
    cancel_flag = {"value": False}
    runs[run_id] = {
        "queue": q,
        "outputs": {},
        "output_paths": {},
        "schemas": {},
        "cancelled": cancel_flag,
        "current_node": None,
        "current_started": None,
        "token_in": 0,
        "token_out": 0,
        "ai_calls": 0,
        "locale": locale,
    }
    cache_dir = current_app.config["CACHE_DIR"]
    target_node = d.get("target_node")
    ai_limit = int(current_app.config.get("AI_CALL_LIMIT", 50))

    def generate_for_node(node_type, params, df):
        info = runs[run_id]
        if info["ai_calls"] >= ai_limit:
            raise RuntimeError(
                f"AI call limit reached ({ai_limit})"
                if locale == "en"
                else f"AI 调用次数已达上限（{ai_limit}），已暂停"
            )
        info["ai_calls"] += 1
        heal_tb = params.pop("_heal_traceback", None) if isinstance(params, dict) else None
        heal_code = params.pop("_heal_code", None) if isinstance(params, dict) else None
        if use_mock:
            # restore heal keys for mock
            p = dict(params)
            if heal_tb:
                p["_heal_traceback"] = heal_tb
                p["_heal_code"] = heal_code
            return mock_generate(node_type, p, df, locale=info.get("locale") or locale)
        summary = summarize_dataframe(df) if df is not None else {"schema": [], "row_count": 0}
        selected = selected_columns_from_params(params)
        if selected:
            summary["selected_columns"] = selected
        result, usage = generate(
            api_key,
            params.get("model") or DEFAULT_MODELS[0],
            node_type,
            params.get("intent") or params.get("ai_intent") or "",
            summary,
            heal_traceback=heal_tb,
            heal_code=heal_code,
            locale=info.get("locale") or locale,
        )
        info["token_in"] += getattr(usage, "prompt_tokens", 0) or 0
        info["token_out"] += getattr(usage, "completion_tokens", 0) or 0
        return result

    def worker():
        def event(kind, node, payload):
            if kind == "node_start":
                runs[run_id].update(current_node=node, current_started=time.monotonic())
            if kind in {"node_done", "node_cached"} and node:
                if payload.get("paths"):
                    runs[run_id]["output_paths"][node] = payload["paths"]
                elif payload.get("path"):
                    runs[run_id]["output_paths"][node] = payload["path"]
                if payload.get("schema"):
                    runs[run_id].setdefault("schemas", {})[node] = payload["schema"]
                path = payload.get("path")
                if path:
                    try:
                        runs[run_id]["outputs"][node] = load_output(path)
                    except Exception:
                        pass
            q.put({"event": kind, "node_id": node, **(payload or {})})
            if kind in {"node_done", "node_cached", "node_error"} and runs[run_id].get("current_node") == node:
                runs[run_id].update(current_node=None, current_started=None)

        try:
            _, outputs = execute(
                graph,
                cache_dir,
                event,
                configured=configured or use_mock,
                target=target_node,
                ai_generator=generate_for_node if (api_key or use_mock) else None,
                cancelled=lambda: cancel_flag["value"],
                locale=locale,
            )
            runs[run_id]["outputs"] = outputs
        except PrecheckError as e:
            q.put({"event": "node_error", "node_id": None, "message": str(e), "problems": e.problems})
        except Exception as e:
            q.put({"event": "node_error", "node_id": None, "message": str(e)})
        finally:
            done.set()
            q.put({"event": "__end"})

    def heartbeat():
        while not done.wait(5):
            node = runs[run_id].get("current_node")
            started = runs[run_id].get("current_started")
            if node and started:
                elapsed = int(time.monotonic() - started)
                q.put(
                    {
                        "event": "node_log",
                        "node_id": node,
                        "message": f"仍在处理中，已等待 {elapsed} 秒",
                    }
                )

    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=heartbeat, daemon=True).start()
    return jsonify(run_id=run_id)


@api.get("/run/<run_id>/stream")
def stream(run_id):
    info = runs.get(run_id)
    if not info:
        return jsonify(error="未找到运行"), 404

    def events():
        while True:
            item = info["queue"].get()
            if item["event"] == "__end":
                break
            yield f"event: {item['event']}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"

    return Response(events(), mimetype="text/event-stream")


@api.post("/run/<run_id>/cancel")
def cancel(run_id):
    if run_id not in runs:
        return jsonify(error="未找到运行"), 404
    runs[run_id]["cancelled"]["value"] = True
    return "", 204


@api.post("/ai/generate")
def ai_generate():
    d = request.get_json() or {}
    secret = setting("api_key")
    locale = _request_locale(d)
    if current_app.config.get("AI_MOCK"):
        result = mock_generate(d["node_type"], d, None)
        return jsonify(result, token_in=0, token_out=0)
    if not secret:
        return jsonify(
            error="Configure a ZenMux API key first" if locale == "en" else "请先配置 ZenMux API Key"
        ), 422
    result, usage = generate(
        secret,
        d.get("model", DEFAULT_MODELS[0]),
        d["node_type"],
        d.get("intent", ""),
        d.get("schema", []),
        locale=locale,
    )
    return jsonify(
        result,
        token_in=getattr(usage, "prompt_tokens", 0),
        token_out=getattr(usage, "completion_tokens", 0),
    )


def _run_output(run_id: str, node_id: str):
    info = runs.get(run_id, {})
    out = info.get("outputs", {}).get(node_id)
    artifact = info.get("output_paths", {}).get(node_id)
    if out is None and artifact:
        try:
            path = next(iter(artifact.values())) if isinstance(artifact, dict) else artifact
            out = load_output(path)
        except Exception as exc:
            raise FileNotFoundError(f"无法读取节点产物：{exc}") from exc
    return out, artifact


@api.post("/schema/resolve")
def resolve_schema():
    """Resolve output / upstream table schema for inspector column pickers."""
    d = request.get_json() or {}
    graph = d.get("graph") or {}
    node_id = d.get("node_id")
    if not node_id:
        return jsonify(error="缺少 node_id"), 400
    run_id = d.get("run_id")
    run_paths = runs.get(run_id, {}).get("output_paths") if run_id else None
    cached_schemas = runs.get(run_id, {}).get("schemas") if run_id else None

    try:
        output = resolve_node_output_schema(graph, node_id, run_paths=run_paths)
    except Exception as exc:
        return jsonify(error=str(exc)), 400

    upstream = None
    source_node_id = None
    source_port = None
    try:
        upstream, source_node_id, source_port = resolve_upstream_schema(
            graph,
            node_id,
            target_handle=d.get("target_handle"),
            run_paths=run_paths,
        )
    except Exception as exc:
        return jsonify(error=str(exc)), 400

    out_pub = schema_public(output)
    up_pub = schema_public(upstream)
    if up_pub is None and source_node_id and cached_schemas and source_node_id in cached_schemas:
        up_pub = cached_schemas[source_node_id]

    inputs_pub: dict[str, Any] = {}
    try:
        for port_id, schema in resolve_table_input_schemas(
            graph, node_id, run_paths=run_paths
        ).items():
            pub = schema_public(schema)
            if pub is not None:
                inputs_pub[port_id] = pub
    except Exception:
        inputs_pub = {}

    # Prefer live run schema cache when probe unavailable
    if out_pub is None and cached_schemas and node_id in cached_schemas:
        out_pub = cached_schemas[node_id]

    picker = up_pub or out_pub
    return jsonify(
        output=out_pub,
        upstream=up_pub,
        inputs=inputs_pub,
        source_node_id=source_node_id,
        source_port=source_port,
        columns=(picker or {}).get("columns") or [],
    )


def _looks_like_filepath(value: str) -> bool:
    """True only for short path-like strings — never markdown/report bodies."""
    if not value or len(value) > 512 or "\n" in value or "\r" in value:
        return False
    stripped = value.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("{"):
        return False
    # Absolute/relative path with an extension, or an existing file.
    path = Path(stripped).expanduser()
    if path.is_file():
        return True
    return bool(path.suffix) and ("/" in stripped or "\\" in stripped or stripped.endswith(path.suffix))


def _extract_file_path(out) -> Path | None:
    """Resolve a filesystem path from export/file node outputs."""
    candidates: list[str] = []
    if isinstance(out, str):
        candidates.append(out)
    elif isinstance(out, dict):
        for key in ("path", "file_out"):
            val = out.get(key)
            if isinstance(val, str):
                candidates.append(val)
    for raw in candidates:
        if not _looks_like_filepath(raw):
            continue
        path = Path(raw).expanduser()
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def _allowed_file(path: Path) -> bool:
    """Only serve files under instance / cache / home .dataflash."""
    roots = []
    try:
        roots.append(Path(current_app.instance_path).resolve())
    except Exception:
        pass
    for key in ("CACHE_DIR", "SECRET_DIR"):
        raw = current_app.config.get(key)
        if raw:
            roots.append(Path(raw).resolve())
    roots.append((Path.home() / ".dataflash").resolve())
    try:
        resolved = path.resolve()
    except Exception:
        return False
    return any(resolved == root or root in resolved.parents for root in roots)


def _is_plotly_figure(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("data"), list)
        and "layout" in value
    )


@api.get("/preview/<run_id>/<node_id>")
def preview(run_id, node_id):
    try:
        out, _artifact = _run_output(run_id, node_id)
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 500
    if out is None:
        return jsonify(error="无输出"), 404
    if hasattr(out, "head"):
        rows = json.loads(out.head(100).to_json(orient="records", date_format="iso"))
        return jsonify(
            type="table",
            columns=[str(c) for c in out.columns],
            rows=rows,
            row_count=len(out),
        )
    # Report/markdown bodies are plain strings — classify before path probing.
    if isinstance(out, str) and not _looks_like_filepath(out):
        sample = out.lstrip()[:2000]
        is_md = (
            sample.startswith("#")
            or "\n#" in sample
            or "![" in sample
            or "| " in sample
            or "```" in sample
        )
        return jsonify(type="markdown" if is_md else "text", text=out)
    file_path = _extract_file_path(out)
    if file_path is not None and _allowed_file(file_path):
        suffix = file_path.suffix.lower().lstrip(".")
        return jsonify(
            type="file",
            path=str(file_path),
            name=file_path.name,
            format=suffix or "bin",
            size=file_path.stat().st_size,
            file_url=f"/api/preview/{run_id}/{node_id}/file",
        )
    if _is_plotly_figure(out):
        return jsonify(type="figure", figure=out)
    if isinstance(out, str):
        return jsonify(type="text", text=out)
    safe = json.loads(json.dumps(out, default=str, ensure_ascii=False))
    if _is_plotly_figure(safe):
        return jsonify(type="figure", figure=safe)
    return jsonify(type="value", value=safe)


@api.get("/preview/<run_id>/<node_id>/file")
def preview_file(run_id, node_id):
    try:
        out, _artifact = _run_output(run_id, node_id)
    except FileNotFoundError as exc:
        return jsonify(error=str(exc)), 500
    if out is None:
        return jsonify(error="无输出"), 404
    path = _extract_file_path(out)
    if path is None or not path.is_file():
        return jsonify(error="该节点没有可下载的文件产物"), 404
    if not _allowed_file(path):
        return jsonify(error="文件路径不在允许范围内"), 403
    return send_file(path, as_attachment=False, download_name=path.name)


@api.post("/export")
def export_api():
    """Standalone export endpoint (SPEC 7.2)."""
    d = request.get_json() or {}
    from .nodes.export_node import _execute

    class _Evt:
        def __call__(self, *a, **k):
            pass

    ctx = {
        "params": {"format": d.get("format", "md"), "path": d["path"]},
        "inputs": {"input": d.get("content")},
        "event": lambda *a, **k: None,
        "node_id": "export",
        "cache_dir": current_app.config["CACHE_DIR"],
    }
    # If run_id/node_id provided, load from run
    if d.get("run_id") and d.get("node_id"):
        info = runs.get(d["run_id"], {})
        ctx["inputs"]["input"] = info.get("outputs", {}).get(d["node_id"])
    result = _execute(ctx)
    return jsonify(result)


@api.get("/settings")
def get_settings():
    secret = setting("api_key")
    models_raw = setting("models")
    locale = resolve_request_locale(
        explicit=request.args.get("locale"),
        accept_language=request.headers.get("Accept-Language"),
        stored=setting("locale"),
    )
    return jsonify(
        configured=bool(secret),
        masked_key=(secret[:3] + "••••" + secret[-4:] if secret else None),
        models=json.loads(models_raw) if models_raw else DEFAULT_MODELS,
        locale=locale,
    )


@api.put("/settings")
def save_settings():
    d = request.get_json() or {}
    if "api_key" in d:
        put_setting("api_key", d["api_key"])
    if "models" in d:
        put_setting("models", json.dumps(d["models"]))
    if "locale" in d and d["locale"]:
        put_setting("locale", resolve_request_locale(explicit=d["locale"]))
    return "", 204


@api.post("/settings/test")
def test_settings():
    if not setting("api_key"):
        return jsonify(ok=False, message="未配置 API Key"), 422
    return jsonify(ok=True, message="API Key 已配置；将在首次运行时验证连接")
