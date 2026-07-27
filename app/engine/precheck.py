"""Pre-run health check (SPEC 5.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.i18n import is_en, pick
from app.i18n.catalog import localize_params_schema
from app.registry import get_spec, resolve_type

from .topology import CycleError, graph_order


def _needs_ai_call(node: dict, spec, params: dict) -> bool:
    """True if this node will call the model during execution."""
    data = node.get("data") or {}
    if data.get("code_locked") and (data.get("code") or node.get("code")):
        return False
    if data.get("code") or node.get("code"):
        return False
    if spec.type == "filter" and (params.get("expression") or "").strip():
        return False
    return True


def _node_label(spec, locale: str | None) -> str:
    if is_en(locale) and getattr(spec, "label_en", None):
        return spec.label_en
    return spec.label


def precheck(
    graph: dict[str, Any], configured: bool, *, locale: str | None = None
) -> list[dict[str, Any]]:
    problems: list[dict[str, Any]] = []
    node_map = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])

    try:
        graph_order(graph)
    except CycleError as exc:
        problems.append(
            {
                "node_id": None,
                "level": "error",
                "code": "cycle",
                "message": pick(locale, "工作流包含环", "Workflow contains a cycle"),
                "fix_hint": pick(locale, "删除形成环的连线", "Remove the edge that forms the cycle"),
                "cycle_nodes": exc.node_ids,
            }
        )

    has_terminal = False

    for node in node_map.values():
        raw_type = node.get("type", "")
        node_type = resolve_type(raw_type)
        # mutate for migration visibility in later stages
        node["type"] = node_type
        spec = get_spec(node_type)
        params = (node.get("data") or {}).get("params") or node.get("params") or {}

        if not spec:
            problems.append(
                {
                    "node_id": node["id"],
                    "level": "error",
                    "code": "unknown_node",
                    "message": pick(
                        locale,
                        f"未知节点类型：{raw_type}",
                        f"Unknown node type: {raw_type}",
                    ),
                    "fix_hint": pick(
                        locale,
                        "替换为已注册的节点类型",
                        "Replace with a registered node type",
                    ),
                }
            )
            continue

        label = _node_label(spec, locale)
        params_schema = localize_params_schema(spec.type, spec.params_schema, locale)

        if spec.category == "output":
            has_terminal = True

        for field in params_schema:
            if field.get("required") and not params.get(field["key"]):
                field_label = field.get("label", field["key"])
                problems.append(
                    {
                        "node_id": node["id"],
                        "level": "error",
                        "code": "required_param",
                        "message": pick(
                            locale,
                            f"{label}：缺少「{field_label}」",
                            f'{label}: missing "{field_label}"',
                        ),
                        "fix_hint": pick(
                            locale,
                            f"选中 {label} 节点并填写「{field_label}」",
                            f'Select the {label} node and fill "{field_label}"',
                        ),
                    }
                )

        for port in spec.inputs:
            if not port.required:
                continue
            connected = any(
                e["target"] == node["id"] and e.get("targetHandle") == port.id for e in edges
            )
            if not connected:
                problems.append(
                    {
                        "node_id": node["id"],
                        "level": "error",
                        "code": "missing_input",
                        "message": pick(
                            locale,
                            f"输入端口 {port.id} 未连接",
                            f"Input port {port.id} is not connected",
                        ),
                        "fix_hint": pick(
                            locale,
                            "连接兼容的上游输出",
                            "Connect a compatible upstream output",
                        ),
                    }
                )

        if spec.is_ai and not configured and _needs_ai_call(node, spec, params):
            problems.append(
                {
                    "node_id": node["id"],
                    "level": "error",
                    "code": "api_key_missing",
                    "message": pick(locale, "AI 节点需要 API Key", "AI nodes require an API key"),
                    "fix_hint": pick(
                        locale,
                        "在设置中配置 ZenMux API Key",
                        "Configure the ZenMux API key in Settings",
                    ),
                }
            )

        if node_type == "file_input":
            path = params.get("path")
            if path and not Path(path).is_file():
                problems.append(
                    {
                        "node_id": node["id"],
                        "level": "error",
                        "code": "missing_file",
                        "message": pick(locale, "输入文件不存在", "Input file does not exist"),
                        "fix_hint": pick(locale, "重新选择文件", "Reselect the file"),
                    }
                )
            elif path and Path(path).is_file():
                size = Path(path).stat().st_size
                if size > 200 * 1024 * 1024 and not params.get("sample_policy"):
                    problems.append(
                        {
                            "node_id": node["id"],
                            "level": "warn",
                            "code": "file_too_large",
                            "message": pick(locale, "文件超过 200MB", "File exceeds 200MB"),
                            "fix_hint": pick(
                                locale,
                                "选择采样策略：取前 N 行 / 随机采样 / 全量（可能很慢）",
                                "Choose a sampling policy: first N rows / random sample / full (may be slow)",
                            ),
                        }
                    )

    # Isolated nodes (no edges at all and not a pure source with outputs unused)
    for node in node_map.values():
        spec = get_spec(node.get("type", ""))
        if not spec:
            continue
        has_in = any(e["target"] == node["id"] for e in edges)
        has_out = any(e["source"] == node["id"] for e in edges)
        if not has_in and not has_out and spec.inputs:
            problems.append(
                {
                    "node_id": node["id"],
                    "level": "error",
                    "code": "orphan_node",
                    "message": pick(
                        locale,
                        "孤立节点：必填输入未连接且无输出连线",
                        "Orphan node: required inputs unconnected and no outgoing edges",
                    ),
                    "fix_hint": pick(
                        locale,
                        "连接该节点或删除它",
                        "Connect this node or delete it",
                    ),
                }
            )

    if node_map and not has_terminal and not any(
        get_spec(n.get("type", "")) and get_spec(n.get("type", "")).type in {"preview", "export"}
        for n in node_map.values()
    ):
        # Soft warn if no Export/Preview present
        if len(node_map) > 1:
            problems.append(
                {
                    "node_id": None,
                    "level": "warn",
                    "code": "no_terminal",
                    "message": pick(
                        locale,
                        "存在下游无终端（Export/Preview）的分支",
                        "A branch has no terminal (Export/Preview)",
                    ),
                    "fix_hint": pick(
                        locale,
                        "添加 Preview 或 Export 节点",
                        "Add a Preview or Export node",
                    ),
                }
            )

    return problems
