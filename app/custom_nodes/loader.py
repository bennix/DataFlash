"""Load / register sandboxed custom nodes from instance/custom_nodes/."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from app.registry import (
    PARAM_CONTROL_TYPES,
    NodeSpec,
    Port,
    PortType,
    get_spec,
    register,
    unregister,
)
from app.sandbox import validate_for_profile
from app.sandbox.validator import CodeRejected

CUSTOM_PREFIX = "custom."
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_PORT_TYPES: frozenset[str] = frozenset(
    {"table", "figure", "stats", "text", "file", "any"}
)
_RESULT_KINDS: frozenset[str] = frozenset({"table", "stats", "figure", "text"})

BUNDLE_SAMPLE_DIR = Path(__file__).resolve().parent / "sample_scale_numeric"
BUNDLE_AI_SAMPLE_DIR = Path(__file__).resolve().parent / "sample_ai_flag_rows"


def custom_nodes_root(instance_path: str | Path) -> Path:
    root = Path(instance_path) / "custom_nodes"
    root.mkdir(parents=True, exist_ok=True)
    return root


def node_dir(instance_path: str | Path, custom_id: str) -> Path:
    return custom_nodes_root(instance_path) / custom_id


def full_type(custom_id: str) -> str:
    return f"{CUSTOM_PREFIX}{custom_id}"


def validate_id(custom_id: str) -> str:
    custom_id = (custom_id or "").strip().lower()
    if custom_id.startswith(CUSTOM_PREFIX):
        custom_id = custom_id[len(CUSTOM_PREFIX) :]
    if not _ID_RE.match(custom_id):
        raise ValueError(
            "节点 id 须为 2–48 位小写字母/数字/下划线，且以字母开头"
        )
    return custom_id


def _parse_port(raw: dict[str, Any], *, default_required: bool = True) -> Port:
    pid = str(raw.get("id") or "").strip()
    ptype = str(raw.get("type") or "table").strip()
    if not pid:
        raise ValueError("端口缺少 id")
    if ptype not in _PORT_TYPES:
        raise ValueError(f"不支持的端口类型：{ptype}")
    return Port(
        id=pid,
        type=ptype,  # type: ignore[arg-type]
        label=str(raw.get("label") or pid),
        required=bool(raw.get("required", default_required)),
        multiple=bool(raw.get("multiple", False)),
        default=bool(raw.get("default", False)),
    )


def _parse_params_schema(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("params_schema 必须是数组")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("params_schema 项必须是对象")
        key = str(item.get("key") or "").strip()
        typ = str(item.get("type") or "string").strip()
        if not key:
            raise ValueError("params_schema 项缺少 key")
        if typ not in PARAM_CONTROL_TYPES:
            raise ValueError(
                f"参数控件类型 «{typ}» 不在白名单中；允许：{sorted(PARAM_CONTROL_TYPES)}"
            )
        field = dict(item)
        field["key"] = key
        field["type"] = typ
        field["label"] = str(item.get("label") or key)
        field["required"] = bool(item.get("required", False))
        out.append(field)
    return out


def read_manifest(path: Path) -> dict[str, Any]:
    meta = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        raise ValueError("manifest.json 必须是 JSON 对象")
    return meta


def validate_package_dir(package_dir: Path) -> tuple[dict[str, Any], str]:
    """Validate a package directory; return (manifest, transform_source).

    AI custom nodes (``is_ai: true``) may omit ``transform.py`` and instead
    rely on model-generated sandbox code driven by ``intent`` / ``prompt.md``.
    """
    manifest_path = package_dir / "manifest.json"
    transform_path = package_dir / "transform.py"
    if not manifest_path.is_file():
        raise FileNotFoundError("缺少 manifest.json")

    meta = read_manifest(manifest_path)
    custom_id = validate_id(str(meta.get("id") or package_dir.name))
    meta["id"] = custom_id
    is_ai = bool(meta.get("is_ai"))

    code = ""
    if transform_path.is_file():
        code = transform_path.read_text(encoding="utf-8")
        if code.strip():
            try:
                validate_for_profile(code, "ai")
            except CodeRejected as exc:
                raise ValueError(f"transform.py 未通过安全校验：{exc}") from exc
            except RuntimeError as exc:
                raise ValueError(f"transform.py 未通过安全校验：{exc}") from exc
    elif not is_ai:
        raise FileNotFoundError("缺少 transform.py（非 AI 自定义节点必须提供）")

    inputs_raw = meta.get("inputs")
    outputs_raw = meta.get("outputs")
    if not inputs_raw:
        inputs_raw = [{"id": "table_in", "type": "table", "label": "表格", "default": False}]
    if not outputs_raw:
        result_kind = str(meta.get("result_kind") or "table")
        out_id = {
            "table": "table_out",
            "stats": "stats_out",
            "figure": "figure_out",
            "text": "text_out",
        }.get(result_kind, "table_out")
        outputs_raw = [
            {"id": out_id, "type": result_kind if result_kind in _PORT_TYPES else "table", "label": "输出", "default": True}
        ]

    # Validate ports / params early
    [_parse_port(p) for p in inputs_raw]
    [_parse_port(p, default_required=False) for p in outputs_raw]
    params_schema = _parse_params_schema(meta.get("params_schema"))
    if is_ai:
        keys = {str(f.get("key")) for f in params_schema}
        if "intent" not in keys:
            params_schema.insert(
                0,
                {
                    "key": "intent",
                    "type": "textarea",
                    "label": "处理意图",
                    "required": True,
                },
            )
        if "model" not in keys:
            params_schema.append(
                {"key": "model", "type": "model", "label": "AI 模型", "required": False}
            )
        meta["params_schema"] = params_schema
    result_kind = str(meta.get("result_kind") or "table")
    if result_kind not in _RESULT_KINDS:
        raise ValueError(f"result_kind 无效：{result_kind}")

    # Forbid clobbering builtins
    node_type = full_type(custom_id)
    existing = get_spec(node_type)
    if existing is not None and not existing.custom:
        raise ValueError(f"禁止覆盖内置节点：{node_type}")
    bare = get_spec(custom_id)
    if bare is not None and not bare.custom:
        raise ValueError(f"id «{custom_id}» 与内置节点冲突")

    return meta, code


def params_preamble(params: dict[str, Any] | None) -> str:
    """Emit ``params = {...}`` as a Python literal (not JSON)."""

    def lit(value: Any) -> str:
        if value is None or isinstance(value, (bool, int, float, str)):
            return repr(value)
        if isinstance(value, list):
            return "[" + ", ".join(lit(v) for v in value) + "]"
        if isinstance(value, dict):
            items = ", ".join(f"{lit(k)}: {lit(v)}" for k, v in value.items())
            return "{" + items + "}"
        return repr(str(value))

    return f"params = {lit(params or {})}\n"


def _make_build_code(package_dir: Path):
    def build_code(ctx: dict[str, Any]) -> str:
        raw = (package_dir / "transform.py").read_text(encoding="utf-8")
        return params_preamble(ctx.get("params") or {}) + raw

    return build_code


def build_spec(package_dir: Path, meta: dict[str, Any] | None = None) -> NodeSpec:
    checked, _code = validate_package_dir(package_dir)
    meta = {**(meta or {}), **checked}
    custom_id = meta["id"]
    node_type = full_type(custom_id)
    is_ai = bool(meta.get("is_ai"))
    inputs_raw = meta.get("inputs") or [
        {"id": "table_in", "type": "table", "label": "表格"}
    ]
    outputs_raw = meta.get("outputs")
    if not outputs_raw:
        rk = str(meta.get("result_kind") or "table")
        out_id = {
            "table": "table_out",
            "stats": "stats_out",
            "figure": "figure_out",
            "text": "text_out",
        }.get(rk, "table_out")
        outputs_raw = [{"id": out_id, "type": rk, "label": "输出", "default": True}]

    inputs = [_parse_port(p) for p in inputs_raw]
    outputs = [_parse_port(p, default_required=False) for p in outputs_raw]
    if outputs and not any(p.default for p in outputs):
        outputs[0] = Port(
            id=outputs[0].id,
            type=outputs[0].type,
            label=outputs[0].label,
            required=outputs[0].required,
            multiple=outputs[0].multiple,
            default=True,
        )

    prompt_hint = str(meta.get("ai_prompt_hint") or "").strip()
    prompt_file = package_dir / "prompt.md"
    if prompt_file.is_file():
        file_hint = prompt_file.read_text(encoding="utf-8").strip()
        if file_hint:
            prompt_hint = f"{prompt_hint}\n\n{file_hint}".strip() if prompt_hint else file_hint

    templates_raw = meta.get("intent_templates") or []
    intent_templates: list[dict[str, Any]] = []
    if isinstance(templates_raw, list):
        for item in templates_raw:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id") or "").strip()
            body = str(item.get("body") or "").strip()
            if not tid or not body:
                continue
            intent_templates.append(
                {
                    "id": tid,
                    "label": str(item.get("label") or tid),
                    "description": str(item.get("description") or ""),
                    "body": body,
                    "slots": item.get("slots") or [],
                }
            )

    return NodeSpec(
        type=node_type,
        category=str(meta.get("category") or "custom"),
        label=str(meta.get("label") or custom_id),
        label_en=str(meta.get("label_en") or meta.get("label") or custom_id),
        description=str(meta.get("description") or ""),
        keywords=tuple(meta.get("keywords") or ("custom", custom_id)),
        icon=str(meta.get("icon") or ("ai" if is_ai else "custom")),
        priority=int(meta.get("priority") or 50),
        inputs=inputs,
        outputs=outputs,
        params_schema=_parse_params_schema(meta.get("params_schema")),
        is_ai=is_ai,
        code_profile="ai",
        custom=True,
        custom_id=custom_id,
        doc_md=str(meta.get("doc_md") or ""),
        ai_prompt_hint=prompt_hint,
        intent_templates=intent_templates,
        # Fixed transform only for non-AI custom nodes
        build_code=None if is_ai else _make_build_code(package_dir),
    )


def load_custom_node(instance_path: str | Path, custom_id: str) -> NodeSpec:
    custom_id = validate_id(custom_id)
    package_dir = node_dir(instance_path, custom_id)
    if not package_dir.is_dir():
        raise FileNotFoundError(f"未安装自定义节点：{custom_id}")
    meta, _ = validate_package_dir(package_dir)
    spec = build_spec(package_dir, meta)
    register(spec, replace=True)
    return spec


def load_all_custom_nodes(instance_path: str | Path) -> list[str]:
    root = custom_nodes_root(instance_path)
    loaded: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not (child / "manifest.json").is_file():
            continue
        try:
            spec = load_custom_node(instance_path, child.name)
            loaded.append(spec.custom_id)
        except Exception:
            # Skip broken packages; list_installed will surface errors separately
            continue
    return loaded


def list_installed(instance_path: str | Path) -> list[dict[str, Any]]:
    root = custom_nodes_root(instance_path)
    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if not (child / "manifest.json").is_file():
            continue
        try:
            meta, _ = validate_package_dir(child)
            custom_id = meta["id"]
            spec = get_spec(full_type(custom_id))
            items.append(
                {
                    "id": custom_id,
                    "type": full_type(custom_id),
                    "label": meta.get("label") or custom_id,
                    "label_en": meta.get("label_en") or meta.get("label") or custom_id,
                    "description": meta.get("description") or "",
                    "category": meta.get("category") or "custom",
                    "result_kind": meta.get("result_kind") or "table",
                    "params_schema": meta.get("params_schema") or [],
                    "is_ai": bool(meta.get("is_ai")),
                    "loaded": bool(spec and spec.custom),
                    "error": None,
                }
            )
        except Exception as exc:
            items.append(
                {
                    "id": child.name,
                    "type": full_type(child.name),
                    "label": child.name,
                    "description": "",
                    "loaded": False,
                    "error": str(exc),
                }
            )
    return items


def uninstall_custom_node(instance_path: str | Path, custom_id: str) -> None:
    custom_id = validate_id(custom_id)
    unregister(full_type(custom_id))
    path = node_dir(instance_path, custom_id)
    if path.is_dir():
        shutil.rmtree(path)


def ensure_sample_installed(instance_path: str | Path) -> str:
    """Copy bundled scale_numeric sample if missing; load it. Returns custom id."""
    return _ensure_bundled(instance_path, "scale_numeric", BUNDLE_SAMPLE_DIR)


def ensure_ai_sample_installed(instance_path: str | Path) -> str:
    """Copy bundled AI custom sample if missing; load it. Returns custom id."""
    return _ensure_bundled(instance_path, "ai_flag_rows", BUNDLE_AI_SAMPLE_DIR)


def ensure_samples_installed(instance_path: str | Path) -> list[str]:
    """Install all bundled custom node samples that are missing."""
    ids = [
        ensure_sample_installed(instance_path),
        ensure_ai_sample_installed(instance_path),
    ]
    return ids


def _ensure_bundled(instance_path: str | Path, sample_id: str, bundle: Path) -> str:
    dest = node_dir(instance_path, sample_id)
    if not dest.is_dir():
        if not bundle.is_dir():
            raise FileNotFoundError(f"内置样例包缺失：{sample_id}")
        shutil.copytree(bundle, dest)
    load_custom_node(instance_path, sample_id)
    return sample_id
