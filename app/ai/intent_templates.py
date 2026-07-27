"""User-facing intent prompt templates for AI-capable nodes.

Templates use ``{{slot}}`` placeholders. Slots of type ``column`` / ``columns``
are filled from upstream field names in the inspector UI.
"""

from __future__ import annotations

import re
from typing import Any

_SLOT_RE = re.compile(r"\{\{(\w+)\}\}")

_COL = {"type": "columns", "required": True}
_COL_OPT = {"type": "columns", "required": False}
_ONE = {"type": "column", "required": True}
_ONE_OPT = {"type": "column", "required": False}
_NUM = {"kinds": ["numeric"]}
_CAT = {"kinds": ["categorical", "boolean", "text"]}
_TXT = {"kinds": ["text", "categorical"]}
_DT = {"kinds": ["datetime", "text"]}


def _slot(key: str, label: str, base: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"key": key, "label": label, **base, **extra}


# slot: key, label, type (column|columns|text), optional kinds filter
_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "ai_clean": [
        {
            "id": "auto_clean",
            "label": "一键基础清洗",
            "description": "缺失/重复/格式通扫",
            "body": "自动检测并处理字段 {{columns}} 的缺失值、重复行与明显格式问题，尽量保留原始语义，最后返回清洗后的表",
            "slots": [_slot("columns", "关注字段", _COL_OPT)],
        },
        {
            "id": "drop_nulls",
            "label": "删除空值行",
            "description": "指定字段任一为空则删",
            "body": "删除字段 {{columns}} 中任一为空的行，并返回清洗后的表",
            "slots": [_slot("columns", "空值检测字段", _COL)],
        },
        {
            "id": "drop_all_null_cols",
            "label": "删除全空列",
            "description": "去掉完全无值的列",
            "body": "删除整列均为空的字段；若指定了 {{columns}} 则仅在这些字段中检查",
            "slots": [_slot("columns", "检查范围（可选）", _COL_OPT)],
        },
        {
            "id": "dedupe",
            "label": "按字段去重",
            "description": "保留每个键的首条",
            "body": "按字段 {{columns}} 去重，保留第一条，删除重复行",
            "slots": [_slot("columns", "去重键", _COL)],
        },
        {
            "id": "normalize_text",
            "label": "文本标准化",
            "description": "去空格并转小写",
            "body": "将字段 {{columns}} 去首尾空格并转为小写",
            "slots": [_slot("columns", "文本字段", _COL, **_TXT)],
        },
        {
            "id": "title_case",
            "label": "类别名规范化",
            "description": "去空格、统一大小写",
            "body": "规范化类别字段 {{columns}}：去首尾空格、合并连续空白，并统一为小写（或 Title Case，保持一致即可）",
            "slots": [_slot("columns", "类别字段", _COL, **_CAT)],
        },
        {
            "id": "fill_median",
            "label": "中位数填缺失",
            "description": "数值列中位数填充",
            "body": "对数值字段 {{columns}} 的缺失值用该列中位数填充",
            "slots": [_slot("columns", "数值字段", _COL, **_NUM)],
        },
        {
            "id": "fill_mean",
            "label": "均值填缺失",
            "description": "数值列均值填充",
            "body": "对数值字段 {{columns}} 的缺失值用该列均值填充",
            "slots": [_slot("columns", "数值字段", _COL, **_NUM)],
        },
        {
            "id": "fill_mode",
            "label": "众数填缺失",
            "description": "类别列众数填充",
            "body": "对类别字段 {{columns}} 的缺失值用该列众数填充",
            "slots": [_slot("columns", "类别字段", _COL, **_CAT)],
        },
        {
            "id": "fill_const",
            "label": "常量填缺失",
            "description": "用固定标记填充",
            "body": "将字段 {{columns}} 的缺失值填充为「未知」或 0（数值用 0，文本/类别用「未知」），并在结果中可区分原缺失",
            "slots": [_slot("columns", "填充字段", _COL)],
        },
        {
            "id": "clip_outliers",
            "label": "截断异常值",
            "description": "按分位裁剪极端值",
            "body": "对数值字段 {{columns}} 按 1%–99% 分位截断异常值（winsorize），避免极端值扭曲后续分析",
            "slots": [_slot("columns", "数值字段", _COL, **_NUM)],
        },
        {
            "id": "drop_outliers_iqr",
            "label": "IQR 删异常行",
            "description": "四分位距外删除",
            "body": "对数值字段 {{columns}} 用 IQR 规则识别异常行并删除（低于 Q1-1.5IQR 或高于 Q3+1.5IQR）",
            "slots": [_slot("columns", "数值字段", _COL, **_NUM)],
        },
        {
            "id": "to_numeric",
            "label": "转为数值",
            "description": "清洗后转 numeric",
            "body": "将字段 {{columns}} 转为数值类型：去掉千分位逗号与货币符号，无法解析的记为缺失",
            "slots": [_slot("columns", "待转数值字段", _COL)],
        },
        {
            "id": "to_datetime",
            "label": "解析日期时间",
            "description": "字符串转 datetime",
            "body": "将字段 {{columns}} 解析为日期时间类型，无法解析的记为缺失，并统一时区无关的本地时间",
            "slots": [_slot("columns", "日期字段", _COL, **_DT)],
        },
        {
            "id": "bin_numeric",
            "label": "数值分箱",
            "description": "等频/等宽分箱",
            "body": "对数值字段 {{column}} 做分箱（优先等频 5 箱），新增分箱列，保留原列",
            "slots": [_slot("column", "分箱字段", _ONE, **_NUM)],
        },
        {
            "id": "encode_bool",
            "label": "是/否规范化",
            "description": "统一布尔取值",
            "body": "将字段 {{columns}} 中的是/否、Y/N、true/false、1/0 等统一为布尔或 0/1，无法识别的记为缺失",
            "slots": [_slot("columns", "布尔类字段", _COL, **_CAT)],
        },
        {
            "id": "drop_cols",
            "label": "删除指定列",
            "description": "丢弃无关字段",
            "body": "删除字段 {{columns}}，保留其余列",
            "slots": [_slot("columns", "删除字段", _COL)],
        },
        {
            "id": "keep_cols",
            "label": "仅保留指定列",
            "description": "投影到关注字段",
            "body": "仅保留字段 {{columns}}，按该顺序输出",
            "slots": [_slot("columns", "保留字段", _COL)],
        },
    ],
    "ai_analyze": [
        {
            "id": "describe",
            "label": "描述统计",
            "description": "均值、分位、缺失率",
            "body": "对字段 {{columns}} 做描述统计，输出样本量、均值、中位数、分位数与缺失率",
            "slots": [_slot("columns", "分析字段", _COL)],
        },
        {
            "id": "profile",
            "label": "字段画像",
            "description": "类型/唯一值/缺失总览",
            "body": "为字段 {{columns}} 生成数据画像：类型推断、唯一值数量、缺失率、高频取值（类别）或分布摘要（数值）",
            "slots": [_slot("columns", "画像字段", _COL_OPT)],
        },
        {
            "id": "groupby",
            "label": "分组汇总",
            "description": "按类别聚合均值计数",
            "body": "按 {{group}} 分组，对 {{columns}} 计算均值与计数，并比较各组差异",
            "slots": [
                _slot("group", "分组字段", _ONE, **_CAT),
                _slot("columns", "汇总字段", _COL, **_NUM),
            ],
        },
        {
            "id": "groupby_multi_agg",
            "label": "多指标分组",
            "description": "均值/中位/求和一并出",
            "body": "按 {{group}} 分组，对 {{columns}} 同时计算均值、中位数、求和与计数，按样本量降序排列",
            "slots": [
                _slot("group", "分组字段", _ONE, **_CAT),
                _slot("columns", "指标字段", _COL, **_NUM),
            ],
        },
        {
            "id": "value_counts",
            "label": "类别频次",
            "description": "取值分布与占比",
            "body": "统计字段 {{column}} 的取值频次与占比，列出 Top 取值，并报告缺失占比",
            "slots": [_slot("column", "类别字段", _ONE, **_CAT)],
        },
        {
            "id": "crosstab",
            "label": "交叉表",
            "description": "两类别联合分布",
            "body": "对 {{row}} 与 {{col}} 做交叉表（计数与行占比），指出占比最高的组合",
            "slots": [
                _slot("row", "行字段", _ONE, **_CAT),
                _slot("col", "列字段", _ONE, **_CAT),
            ],
        },
        {
            "id": "correlate",
            "label": "相关分析",
            "description": "数值两两相关",
            "body": "分析字段 {{columns}} 之间的相关关系，标出较强相关对（|r| 较高者）",
            "slots": [_slot("columns", "相关字段", _COL, **_NUM)],
        },
        {
            "id": "target_drivers",
            "label": "目标变量关联",
            "description": "找与目标相关的字段",
            "body": "以 {{target}} 为目标，评估字段 {{columns}} 与其的关联强度（数值用相关，类别用分组均值/占比差异），列出最值得关注的驱动因素",
            "slots": [
                _slot("target", "目标字段", _ONE),
                _slot("columns", "候选特征", _COL),
            ],
        },
        {
            "id": "rate_by_group",
            "label": "分组比率",
            "description": "如转化率/存活率",
            "body": "按 {{group}} 分组，计算 {{target}} 的比率（均值或正例占比）与样本量，按比率排序并标出高低组",
            "slots": [
                _slot("group", "分组字段", _ONE, **_CAT),
                _slot("target", "比率目标（0/1 或数值）", _ONE),
            ],
        },
        {
            "id": "quantile_slice",
            "label": "分位切片对比",
            "description": "高低分位人群差异",
            "body": "按字段 {{metric}} 分成低/中/高分位组，对比各组在 {{columns}} 上的差异",
            "slots": [
                _slot("metric", "分位依据", _ONE, **_NUM),
                _slot("columns", "对比字段", _COL),
            ],
        },
        {
            "id": "missing_audit",
            "label": "缺失审计",
            "description": "缺失分布与模式",
            "body": "审计字段 {{columns}} 的缺失率；若可能，检查缺失是否与 {{group}} 相关（分组缺失率）",
            "slots": [
                _slot("columns", "审计字段", _COL_OPT),
                _slot("group", "对照分组（可选）", _ONE_OPT, **_CAT),
            ],
        },
        {
            "id": "top_bottom",
            "label": "极值清单",
            "description": "最大/最小若干行",
            "body": "按字段 {{metric}} 分别列出最高与最低各 10 行，展示字段 {{columns}}",
            "slots": [
                _slot("metric", "排序字段", _ONE, **_NUM),
                _slot("columns", "展示字段", _COL_OPT),
            ],
        },
        {
            "id": "time_trend",
            "label": "时间趋势汇总",
            "description": "按日/月聚合",
            "body": "以 {{time}} 为时间轴（按合适粒度重采样），对 {{columns}} 求均值或求和，描述趋势与异常波动",
            "slots": [
                _slot("time", "时间字段", _ONE, **_DT),
                _slot("columns", "指标字段", _COL, **_NUM),
            ],
        },
        {
            "id": "segment_compare",
            "label": "人群对比",
            "description": "两段人群指标差",
            "body": "对比不同 {{group}} 人群在 {{columns}} 上的差异，给出效应方向与简要解释（注意样本量）",
            "slots": [
                _slot("group", "人群字段", _ONE, **_CAT),
                _slot("columns", "对比指标", _COL, **_NUM),
            ],
        },
    ],
    "ai_chart": [
        {
            "id": "scatter",
            "label": "散点图",
            "description": "双变量 + 可选着色",
            "body": "绘制散点图：横轴 {{x}}，纵轴 {{y}}，按 {{color}} 着色，并加合适标题与坐标轴标签",
            "slots": [
                _slot("x", "X 轴", _ONE),
                _slot("y", "Y 轴", _ONE),
                _slot("color", "颜色字段", _ONE_OPT, kinds=["categorical", "boolean", "numeric"]),
            ],
        },
        {
            "id": "scatter_trend",
            "label": "散点+趋势线",
            "description": "关系与拟合线",
            "body": "绘制 {{x}} 对 {{y}} 的散点图，叠加趋势线；若有 {{color}} 则分组着色",
            "slots": [
                _slot("x", "X 轴", _ONE, **_NUM),
                _slot("y", "Y 轴", _ONE, **_NUM),
                _slot("color", "颜色字段", _ONE_OPT, **_CAT),
            ],
        },
        {
            "id": "bar",
            "label": "柱状图（均值）",
            "description": "类别均值对比",
            "body": "按 {{x}} 分组，对 {{y}} 求均值，用柱状图展示；若有 {{color}} 则分组着色",
            "slots": [
                _slot("x", "类别轴", _ONE, **_CAT),
                _slot("y", "数值轴", _ONE, **_NUM),
                _slot("color", "颜色字段", _ONE_OPT),
            ],
        },
        {
            "id": "bar_count",
            "label": "柱状图（计数）",
            "description": "类别样本量",
            "body": "统计字段 {{x}} 各类别的行数，绘制柱状图；按计数降序；若有 {{color}} 则堆叠或分组",
            "slots": [
                _slot("x", "类别字段", _ONE, **_CAT),
                _slot("color", "细分颜色", _ONE_OPT, **_CAT),
            ],
        },
        {
            "id": "bar_rate",
            "label": "比率柱状图",
            "description": "分组成功率/转化率",
            "body": "按 {{x}} 分组计算 {{y}} 的比率（均值或正例占比），柱状图展示并标注样本量",
            "slots": [
                _slot("x", "分组字段", _ONE, **_CAT),
                _slot("y", "比率目标", _ONE),
            ],
        },
        {
            "id": "box",
            "label": "箱线图",
            "description": "分布对比",
            "body": "绘制箱线图：展示 {{y}} 在 {{x}} 各组的分布",
            "slots": [
                _slot("x", "分组字段", _ONE, **_CAT),
                _slot("y", "数值字段", _ONE, **_NUM),
            ],
        },
        {
            "id": "violin",
            "label": "小提琴图",
            "description": "分布形态对比",
            "body": "绘制小提琴图（或密度箱线组合）：对比 {{y}} 在 {{x}} 各组的分布形态",
            "slots": [
                _slot("x", "分组字段", _ONE, **_CAT),
                _slot("y", "数值字段", _ONE, **_NUM),
            ],
        },
        {
            "id": "hist",
            "label": "直方图",
            "description": "单变量分布",
            "body": "绘制字段 {{x}} 的直方图，展示分布形态；如有 {{color}} 则分组对比",
            "slots": [
                _slot("x", "数值字段", _ONE, **_NUM),
                _slot("color", "分组颜色", _ONE_OPT),
            ],
        },
        {
            "id": "density",
            "label": "密度曲线",
            "description": "平滑分布对比",
            "body": "绘制字段 {{x}} 的核密度/平滑分布曲线；若有 {{color}} 则分组叠加对比",
            "slots": [
                _slot("x", "数值字段", _ONE, **_NUM),
                _slot("color", "分组字段", _ONE_OPT, **_CAT),
            ],
        },
        {
            "id": "line",
            "label": "折线趋势",
            "description": "时间/有序序列",
            "body": "以 {{x}} 为横轴、{{y}} 为纵轴绘制折线图；若有 {{color}} 则多系列对比，注意排序与缺失",
            "slots": [
                _slot("x", "横轴（时间/有序）", _ONE),
                _slot("y", "纵轴指标", _ONE, **_NUM),
                _slot("color", "系列字段", _ONE_OPT, **_CAT),
            ],
        },
        {
            "id": "area",
            "label": "面积图",
            "description": "累计或堆叠趋势",
            "body": "以 {{x}} 为横轴、{{y}} 为纵轴绘制面积图；若有 {{color}} 则堆叠展示构成",
            "slots": [
                _slot("x", "横轴", _ONE),
                _slot("y", "纵轴", _ONE, **_NUM),
                _slot("color", "堆叠类别", _ONE_OPT, **_CAT),
            ],
        },
        {
            "id": "heatmap",
            "label": "相关热力图",
            "description": "数值相关矩阵",
            "body": "对字段 {{columns}} 计算相关矩阵并绘制热力图，标注相关系数",
            "slots": [_slot("columns", "数值字段", _COL, **_NUM)],
        },
        {
            "id": "pie",
            "label": "饼图/环形图",
            "description": "构成占比",
            "body": "按字段 {{x}} 统计占比，绘制饼图或环形图；类别过多时合并为「其他」",
            "slots": [_slot("x", "构成字段", _ONE, **_CAT)],
        },
        {
            "id": "facet_hist",
            "label": "分面直方图",
            "description": "按组看分布",
            "body": "按 {{color}} 分面，分别绘制 {{x}} 的直方图，便于比较组间分布",
            "slots": [
                _slot("x", "数值字段", _ONE, **_NUM),
                _slot("color", "分面字段", _ONE, **_CAT),
            ],
        },
        {
            "id": "pareto",
            "label": "帕累托图",
            "description": "频次+累计占比",
            "body": "对字段 {{x}} 绘制帕累托图：柱为频次，线为累计占比，突出头部贡献",
            "slots": [_slot("x", "类别字段", _ONE, **_CAT)],
        },
    ],
    "ai_report": [
        {
            "id": "brief",
            "label": "分析简报",
            "description": "样本量+发现+结论",
            "body": "围绕字段 {{columns}} 撰写简洁分析简报：样本量、关键分布、主要发现与一句话结论",
            "slots": [_slot("columns", "报告字段", _COL_OPT)],
        },
        {
            "id": "chart_read",
            "label": "图表解读",
            "description": "结合统计与图",
            "body": "结合上游统计与图表，解读与字段 {{columns}} 相关的发现，并给出可执行建议",
            "slots": [_slot("columns", "关注字段", _COL_OPT)],
        },
        {
            "id": "exec_summary",
            "label": "管理层摘要",
            "description": "非技术读者向",
            "body": "写给非技术读者的管理层摘要：用业务语言解释与 {{columns}} 相关的 3 个要点、1 个风险与 1 个下一步，避免堆砌术语",
            "slots": [_slot("columns", "业务关注字段", _COL_OPT)],
        },
        {
            "id": "data_quality",
            "label": "数据质量报告",
            "description": "缺失/异常/一致性",
            "body": "撰写数据质量报告，聚焦字段 {{columns}}：缺失、异常值、重复与明显不一致，并给出修复优先级",
            "slots": [_slot("columns", "质检字段", _COL_OPT)],
        },
        {
            "id": "segment_story",
            "label": "分群洞察",
            "description": "人群差异叙事",
            "body": "围绕分组相关发现撰写分群洞察，重点解释字段 {{columns}} 在不同人群中的差异及可能原因（注明相关非因果）",
            "slots": [_slot("columns", "洞察字段", _COL_OPT)],
        },
        {
            "id": "hypothesis",
            "label": "假设与验证",
            "description": "提出可检验假设",
            "body": "基于当前结果，围绕 {{columns}} 提出 2–3 个可检验假设，说明已有证据支持/反对之处，以及还缺什么数据",
            "slots": [_slot("columns", "假设相关字段", _COL_OPT)],
        },
        {
            "id": "method_note",
            "label": "方法说明",
            "description": "可复现分析笔记",
            "body": "撰写可复现的方法说明：数据范围、关键字段 {{columns}}、清洗与筛选逻辑、统计/可视化做法与局限",
            "slots": [_slot("columns", "关键字段", _COL_OPT)],
        },
        {
            "id": "action_list",
            "label": "行动项清单",
            "description": "结论→待办",
            "body": "把与 {{columns}} 相关的分析结论转化为 3–5 条可执行行动项（谁/做什么/看什么指标），每条附一句依据",
            "slots": [_slot("columns", "相关字段", _COL_OPT)],
        },
        {
            "id": "full_markdown",
            "label": "完整 Markdown 报告",
            "description": "章节齐全长文",
            "body": "输出完整 Markdown 报告，建议结构：背景与问题、数据概览、质量说明、关键发现（围绕 {{columns}}）、图表解读、结论与建议、局限与下一步",
            "slots": [_slot("columns", "主线字段", _COL_OPT)],
        },
    ],
    "filter": [
        {
            "id": "eq_filter",
            "label": "等值筛选",
            "description": "单字段条件",
            "body": "仅保留字段 {{column}} 满足业务条件的行（请在意图中补充具体取值或条件）",
            "slots": [_slot("column", "筛选字段", _ONE)],
        },
        {
            "id": "in_list",
            "label": "白名单取值",
            "description": "保留若干类别",
            "body": "仅保留字段 {{column}} 属于指定取值集合的行（请在意图正文中列出允许的取值）",
            "slots": [_slot("column", "类别字段", _ONE, **_CAT)],
        },
        {
            "id": "not_null",
            "label": "非空筛选",
            "description": "关键字段均有值",
            "body": "仅保留字段 {{columns}} 均非空的行",
            "slots": [_slot("columns", "非空字段", _COL)],
        },
        {
            "id": "range_filter",
            "label": "数值范围",
            "description": "区间内/排除异常",
            "body": "筛选字段 {{column}} 落在合理业务范围内的行，排除明显异常值（可在正文写明上下界）",
            "slots": [_slot("column", "数值字段", _ONE, **_NUM)],
        },
        {
            "id": "top_n",
            "label": "Top N",
            "description": "按指标取前 N",
            "body": "按字段 {{column}} 降序取前 100 行（可在正文改 N）；若需分组 Top，请说明分组字段",
            "slots": [_slot("column", "排序字段", _ONE, **_NUM)],
        },
        {
            "id": "bottom_n",
            "label": "Bottom N",
            "description": "按指标取后 N",
            "body": "按字段 {{column}} 升序取前 100 行（即最小的 N 条，可在正文改 N）",
            "slots": [_slot("column", "排序字段", _ONE, **_NUM)],
        },
        {
            "id": "multi_filter",
            "label": "多字段条件",
            "description": "自然语言多条件",
            "body": "基于字段 {{columns}} 编写筛选条件，只保留同时满足业务规则的行",
            "slots": [_slot("columns", "涉及字段", _COL)],
        },
        {
            "id": "exclude_values",
            "label": "排除取值",
            "description": "黑名单过滤",
            "body": "排除字段 {{column}} 等于指定取值的行（请在正文列出要排除的值）",
            "slots": [_slot("column", "字段", _ONE)],
        },
        {
            "id": "text_contains",
            "label": "文本包含",
            "description": "关键字匹配",
            "body": "保留字段 {{column}} 文本包含指定关键字的行（请在正文写明关键字；默认不区分大小写）",
            "slots": [_slot("column", "文本字段", _ONE, **_TXT)],
        },
        {
            "id": "date_window",
            "label": "时间窗口",
            "description": "最近一段时间",
            "body": "按字段 {{column}} 筛选时间窗口内的行（请在正文写明起止日期或「最近 30 天」等）",
            "slots": [_slot("column", "时间字段", _ONE, **_DT)],
        },
        {
            "id": "percentile_keep",
            "label": "分位内保留",
            "description": "去掉两端极端",
            "body": "仅保留字段 {{column}} 位于 5%–95% 分位之间的行（可在正文调整分位）",
            "slots": [_slot("column", "数值字段", _ONE, **_NUM)],
        },
        {
            "id": "balanced_sample",
            "label": "分层抽样",
            "description": "按类别近似均衡",
            "body": "按字段 {{column}} 做分层抽样，使各类别样本量尽量均衡（正文可写每类上限或总样本）",
            "slots": [_slot("column", "分层字段", _ONE, **_CAT)],
        },
    ],
}


def templates_for(node_type: str, locale: str | None = None) -> list[dict[str, Any]]:
    """Public list of templates for a node type (empty if none), localized."""
    from app.ai.intent_templates_en import EN
    from app.i18n import is_en

    raw = _TEMPLATES.get(node_type, [])
    if not is_en(locale):
        return [
            {
                "id": t["id"],
                "label": t["label"],
                "description": t.get("description", ""),
                "body": t["body"],
                "slots": [
                    {k: v for k, v in s.items() if k != "label_en"}
                    for s in (t.get("slots") or [])
                ],
            }
            for t in raw
        ]

    overlays = EN.get(node_type, {})
    out: list[dict[str, Any]] = []
    for t in raw:
        ov = overlays.get(t["id"], {})
        slot_labels = ov.get("slots") or {}
        slots = []
        for s in t.get("slots") or []:
            slot = {k: v for k, v in s.items() if k != "label_en"}
            if s.get("key") in slot_labels:
                slot["label"] = slot_labels[s["key"]]
            slots.append(slot)
        out.append(
            {
                "id": t["id"],
                "label": ov.get("label") or t["label"],
                "description": ov.get("description") or t.get("description", ""),
                "body": ov.get("body") or t["body"],
                "slots": slots,
            }
        )
    return out


def get_template(
    node_type: str, template_id: str, locale: str | None = None
) -> dict[str, Any] | None:
    for item in templates_for(node_type, locale):
        if item["id"] == template_id:
            return item
    return None


def format_slot_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return "、".join(parts)
    return str(value).strip()


def fill_template(body: str, slots: dict[str, Any], *, pending: str = "（待选）") -> str:
    """Replace ``{{key}}`` with slot values; known-empty slots become ``pending``."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in slots:
            return match.group(0)
        filled = format_slot_value(slots[key])
        return filled if filled else pending

    return _SLOT_RE.sub(repl, body)


def slot_keys(body: str) -> list[str]:
    return list(dict.fromkeys(_SLOT_RE.findall(body)))
