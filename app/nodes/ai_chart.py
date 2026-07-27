from app.registry import Message, MessageCatalog, NodeSpec, Port, param, register

SPEC = register(
    NodeSpec(
        type="ai_chart",
        category="visualize",
        label="AI 图表",
        label_en="AI Chart",
        description="由 AI 选择图型并生成 plotly 图表",
        keywords=("chart", "plot", "图表", "可视化"),
        icon="chart",
        priority=100,
        inputs=[Port("table_in", "table", "表格")],
        outputs=[Port("figure_out", "figure", "图表", default=True)],
        params_schema=[
            param("columns", "columns", False, "关注字段"),
            param("x", "column", False, "X 轴字段"),
            param("y", "column", False, "Y 轴字段"),
            param("color", "column", False, "颜色字段"),
            param("intent", "textarea", False, "图表意图"),
            param("model", "model", False, "AI 模型"),
        ],
        is_ai=True,
        code_profile="ai",
        messages=MessageCatalog(
            error={
                "missing_column": Message(
                    "missing_column", "列「{col}」不存在于上游数据", "重新选择列"
                ),
            },
        ),
    )
)
