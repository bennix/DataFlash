from app.registry import MessageCatalog, NodeSpec, Port, param, register

SPEC = register(
    NodeSpec(
        type="ai_analyze",
        category="analyze",
        label="AI 分析",
        label_en="AI Analyze",
        description="描述统计 / 相关 / 异常 / 分布分析",
        keywords=("analyze", "统计", "分析", "describe"),
        icon="analyze",
        priority=100,
        inputs=[Port("table_in", "table", "表格")],
        outputs=[Port("stats_out", "stats", "统计", default=True)],
        params_schema=[
            param("columns", "columns", False, "分析字段"),
            param("intent", "textarea", False, "分析意图"),
            param("model", "model", False, "AI 模型"),
        ],
        is_ai=True,
        code_profile="ai",
        messages=MessageCatalog(),
    )
)
