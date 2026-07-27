"""Declarative node registry (SPEC 2.1 + Orange3 delta §2.3–2.5, §2.11)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal

PortType = Literal["table", "figure", "stats", "text", "file", "any"]
CodeProfile = Literal["trusted", "ai"]

# Closed whitelist of param control types (SPEC delta §2.11). P0 only.
PARAM_CONTROL_TYPES: frozenset[str] = frozenset(
    {
        "string",
        "text",
        "textarea",
        "number",
        "boolean",
        "select",
        "multiselect",
        "column",
        "columns",
        "expression",
        "code",
        "file",
        "model",
        "json",
    }
)


@dataclass(frozen=True)
class Port:
    id: str
    type: PortType
    label: str = ""
    required: bool = True
    multiple: bool = False
    default: bool = False

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Message:
    code: str
    template: str
    fix_hint: str = ""

    def render(self, **kwargs: Any) -> tuple[str, str]:
        try:
            return self.template.format(**kwargs), self.fix_hint.format(**kwargs) if self.fix_hint else ""
        except KeyError:
            return self.template, self.fix_hint


@dataclass
class MessageCatalog:
    error: dict[str, Message] = field(default_factory=dict)
    warning: dict[str, Message] = field(default_factory=dict)
    info: dict[str, Message] = field(default_factory=dict)

    def issue(
        self,
        level: Literal["error", "warning", "info", "warn"],
        code: str,
        node_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Accept "warn" as alias for "warning" (SPEC uses warn)
        group_name = "warning" if level == "warn" else level
        group = getattr(self, group_name, {})
        msg = group.get(code)
        if msg is None:
            message = kwargs.get("message", code)
            fix_hint = kwargs.get("fix_hint", "")
        else:
            message, fix_hint = msg.render(**kwargs)
        out_level = "warn" if group_name == "warning" else group_name
        return {
            "node_id": node_id,
            "level": out_level,
            "code": code,
            "message": message,
            "fix_hint": fix_hint,
        }

    def public(self) -> dict[str, Any]:
        def pack(group: dict[str, Message]) -> dict[str, dict[str, str]]:
            return {k: {"template": v.template, "fix_hint": v.fix_hint} for k, v in group.items()}

        return {"error": pack(self.error), "warning": pack(self.warning), "info": pack(self.info)}


@dataclass
class NodeSpec:
    type: str
    category: str
    label: str
    inputs: list[Port]
    outputs: list[Port]
    params_schema: list[dict[str, Any]]
    is_ai: bool = False
    description: str = ""
    keywords: tuple[str, ...] = ()
    icon: str = ""
    priority: int = 100
    messages: MessageCatalog = field(default_factory=MessageCatalog)
    code_profile: CodeProfile = "trusted"
    schema_version: int = 1
    replaces: tuple[str, ...] = ()
    doc_md: str = ""
    label_en: str = ""
    custom: bool = False
    custom_id: str = ""
    ai_prompt_hint: str = ""
    intent_templates: list[dict[str, Any]] = field(default_factory=list)
    # execute(ctx) -> dict[port_id, value]  OR build_code(ctx) -> str then sandboxed
    execute: Callable[..., Any] | None = None
    build_code: Callable[..., str] | None = None
    migrate_params: Callable[[dict, int], dict] | None = None

    def __post_init__(self) -> None:
        for field_def in self.params_schema:
            ctrl = field_def.get("type", "string")
            if ctrl not in PARAM_CONTROL_TYPES:
                raise ValueError(
                    f"节点 {self.type} 的参数控件类型 «{ctrl}» 不在白名单中；"
                    f"允许：{sorted(PARAM_CONTROL_TYPES)}"
                )

    def public(self, locale: str | None = None) -> dict[str, Any]:
        from app.ai.intent_templates import templates_for
        from app.i18n import is_en
        from app.i18n.catalog import (
            CATEGORY_EN,
            localize_params_schema,
            localize_ports,
            node_description,
        )

        label = (self.label_en or self.label) if is_en(locale) else self.label
        category = CATEGORY_EN.get(self.category, self.category) if is_en(locale) else self.category
        desc = (
            self.description
            if self.custom
            else node_description(self.type, self.description, locale)
        )
        return {
            "type": self.type,
            "category": category,
            "label": label,
            "label_en": self.label_en or self.label,
            "label_zh": self.label,
            "description": desc,
            "description_zh": self.description,
            "keywords": list(self.keywords),
            "icon": self.icon or self.category,
            "priority": self.priority,
            "inputs": localize_ports(self.inputs, locale),
            "outputs": localize_ports(self.outputs, locale),
            "params_schema": localize_params_schema(self.type, self.params_schema, locale),
            "is_ai": self.is_ai,
            "intent_templates": (
                list(self.intent_templates)
                if self.intent_templates
                else (templates_for(self.type, locale) if self.is_ai else [])
            ),
            "messages": self.messages.public(),
            "code_profile": self.code_profile,
            "schema_version": self.schema_version,
            "replaces": list(self.replaces),
            "doc_md": self.doc_md,
            "custom": self.custom,
            "custom_id": self.custom_id,
            "source": "user" if self.custom else "builtin",
            "locale": "en" if is_en(locale) else "zh-CN",
        }


_REGISTRY: dict[str, NodeSpec] = {}
_REPLACES: dict[str, str] = {}


def register(spec: NodeSpec, *, replace: bool = False) -> NodeSpec:
    """Register a node. ``replace=True`` only allowed for ``custom.*`` types."""
    if spec.type in _REGISTRY:
        if not (replace and spec.type.startswith("custom.")):
            raise ValueError(f"节点类型已注册：{spec.type}")
        unregister(spec.type)
    _REGISTRY[spec.type] = spec
    for old in spec.replaces:
        _REPLACES[old] = spec.type
    return spec


def unregister(node_type: str) -> bool:
    """Remove a registered type. Returns True if it existed."""
    spec = _REGISTRY.pop(node_type, None)
    if spec is None:
        return False
    for old, new in list(_REPLACES.items()):
        if new == node_type or old == node_type:
            _REPLACES.pop(old, None)
    return True


def get_spec(node_type: str) -> NodeSpec | None:
    resolved = _REPLACES.get(node_type, node_type)
    return _REGISTRY.get(resolved)


def resolve_type(node_type: str) -> str:
    return _REPLACES.get(node_type, node_type)


def all_specs() -> list[NodeSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: (s.category, s.priority, s.type))


def param(key: str, typ: str = "string", required: bool = False, label: str = "", **more: Any) -> dict[str, Any]:
    return {"key": key, "label": label or key, "type": typ, "required": required, **more}


def clear_registry() -> None:
    """Test helper."""
    _REGISTRY.clear()
    _REPLACES.clear()
