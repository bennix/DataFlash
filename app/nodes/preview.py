from app.registry import MessageCatalog, NodeSpec, Port, register


def _execute(ctx: dict):
    value = ctx["inputs"].get("input")
    return value  # no outputs; executor stores pass-through


SPEC = register(
    NodeSpec(
        type="preview",
        category="output",
        label="预览",
        label_en="Preview",
        description="调试用，查看任意端口数据",
        keywords=("preview", "预览", "debug"),
        icon="preview",
        priority=210,
        inputs=[Port("input", "any", "输入")],
        outputs=[],
        params_schema=[],
        messages=MessageCatalog(),
        code_profile="trusted",
        execute=_execute,
    )
)
