# SPEC 增补 v2 — Orange3 借鉴与架构调整

状态：经 AI 决策委员会评审通过，含风险守门员两条强制前置条件。
关系：本文是 `2026-07-25-ai-dataflow-app-design.md`（下称「原 SPEC」）的**增补**。
凡冲突处以本文为准，且每条均标注其覆盖或补充的原 SPEC 章节。
研究来源：Orange3（`biolab/orange3`）、`orange-widget-base`、`orange-canvas-core`。

---

## 0. 现状体检（本增补的起因之一）

工作区在本增补起草前已有一份约 1300 行的遗留原型。体检结论：

| 原 SPEC 条款 | 遗留原型实际 | 处置 |
|---|---|---|
| 3.3 父进程不持有 DataFrame，只传路径 | 引擎在父进程内存中传递 DataFrame | 重写 |
| 2.3 每个节点计算在子进程 | 仅 `ai_clean` 走沙箱，其余在父进程直接执行 | 重写 |
| 5.3 AST **白名单** | `security.py` 为黑名单 | 已由 `app/sandbox/validator.py` 取代 |
| 5.3 AI 自愈 ≤2 次并回传 traceback | 无自愈循环 | 新建 |
| 6 表 Export 支持 MD/PDF/HTML/CSV/XLSX | Export 节点原样返回参数，无 `/api/export` | 新建 |
| 6 表 AI Analyze / AI Chart / AI Report 为 AI 节点 | 三者均为写死的 Python，未调用 AI；Report 返回占位字符串 | 重写 |
| 5.4 成本护栏 | `AI_CALL_LIMIT` 已定义但无人读取 | 新建 |
| 7.1 `runs` / `node_runs` 落库 | 未写入 | 新建 |
| 7.2 `POST /api/run/:id/cancel` | `cancelled` 标志无任何代码读取 | 重写 |
| 1 前端 React 19 + React Flow 12 + Vite + TS | 仅有 `package.json`，`src/` 为空；实际界面为 32 行 vanilla JS | 新建 |

**保留项**（经评估质量可用）：`store.py` 的表结构、`crypto.py`、`ai.py` 中的
`parse_model_payload`（已正确处理 markdown 围栏剥离与输出契约校验）、`api.py` 的路由清单。

---

## 1. 借鉴分档总表

筛选判据（委员会共识）：**不现在做，P0 之后就要返工** —— 满足者进 P0，否则进 backlog。

### 1.1 进 P0（六项）

| # | 借鉴项 | Orange 出处 | 返工理由 |
|---|---|---|---|
| A | 类型化 Schema（kind + role + 统计 + 脱敏样本） | `Orange/data/domain.py:158`、`variable.py:328` | 嵌入 artifact 格式、指纹、AI 上下文、precheck 四处 |
| B | 注册表元数据扩展 | `OWBaseWidget` 类属性（widget.py:138-262） | 后加要动全部 29 个节点文件 |
| C | 声明式消息目录 | `Msg` / `MessageGroup`（utils/messages.py） | precheck 与运行期共用，后改要重写所有错误路径 |
| D | 多输出通道 + `default` + 端口摘要 | `Output(default=True)`、`auto_summary`（signals.py:172） | 端口契约变更会动 graph 格式 |
| E | 工作流格式版本化 + `replaces` 迁移 | `.ows` version、`resolve_replaced`（readwrite.py） | 格式定了再改就要写迁移器 |
| F | 参数控件封闭白名单 | `PreprocessAction` 注册表（owpreprocess.py:1329） | 守住原 SPEC 2.1，防止被静默突破 |

### 1.2 P1（P0 全部验收通过后启动）

| 借鉴项 | Orange 出处 | 触发条件 |
|---|---|---|
| Domain Editor 可编辑列网格 | `utils/domaineditor.py` | P0 验收通过 + 控件白名单已支持 `schema_editor` |
| 拖线到空白 → 类型过滤搜索菜单 | `NewLinkAction` + `QuickMenu` | P0 验收通过 |
| 内置示例数据集 + 编号示例工作流 | `Orange/datasets/`、`canvas/workflows/110-*.ows` | P0 验收通过 |
| 每节点帮助文档（`?` / F1） | `doc/widgets.json` + `WIDGET_HELP_PATH` | 节点总数 ≥ 15 |
| 可堆叠步骤节点（AI 产出 steps） | `PreprocessorList` + `owpreprocess.py` | `steps` 字段已有真实数据积累 |
| 边上数据摘要（`1523 × 12`） | `format_summary_details`（state_summary.py:66） | P0 验收通过 |
| auto-run + 防抖 / 信号压缩 | `commit.deferred`、`compress_signals()` | 用户反馈手动 Run 太繁琐 |
| 列名+类型模糊匹配（简化版 Context） | `DomainContextHandler.match`（settings.py:205） | P1 其余项完成 |

### 1.3 明确不做（含理由）

| 不做项 | 理由 |
|---|---|
| 完整 `ContextSetting` / 域匹配评分体系 | 研究估 2–4 周；在无用户阶段 ROI 最低。降级为 P1 的简化模糊匹配 |
| `compute_value` 惰性派生列 / `Table.transform` | 我们的指纹缓存 + 可重跑工作流已达成等价目标，无需第二套机制 |
| 推送式 `SignalManager` | 无 Qt 事件循环；保持 batch + dirty 下游闭包 |
| pickle 持久化（`.ows` 的 properties 回退） | Web 场景同时踩安全与跨版本兼容两个坑 |
| Orange `Table`（numpy X/Y/metas）与负索引 metas | 与 pandas 原生模型冲突；AI 生成的是 pandas 代码 |
| 从 `project_name` 隐式推断依赖 | 应显式声明 |
| 文件内递增 int node id | 协作与合并困难，沿用 UUID |

---

## 2. P0 新增与修改条款

### 2.1 类型化 Schema（补充原 SPEC 2.2、4.2；修改 3.1、3.3）

`table` 端口不再只是一个 parquet 文件，而是 **parquet + schema 侧车**。

```python
@dataclass(frozen=True)
class Column:
    name: str
    kind: Literal["numeric", "categorical", "datetime", "text", "boolean"]
    dtype: str                              # 底层 pandas dtype，保留真相
    role: Literal["feature", "target", "meta", "skip"] = "feature"
    null_pct: float = 0.0
    n_unique: int = 0
    categories: tuple[str, ...] | None = None   # kind=categorical 且基数 ≤50 时填充
    stats: dict | None = None                   # numeric: min/max/mean/std；datetime: min/max
    samples: tuple[str, ...] = ()               # 已按 2.6 脱敏，≤3 个
    attributes: dict = field(default_factory=dict)   # 借鉴 Orange var.attributes：origin/unit/...

@dataclass(frozen=True)
class TableSchema:
    columns: tuple[Column, ...]
    row_count: int
```

**类型推断阈值**（借鉴 Orange，但阈值须在代码中具名常量化并写入文档）：

- 数值列且 `n_unique <= 3` 且取值 ⊆ `{0,1}` 或 `{1,2}` → `boolean`
  （出处：`variable.py:31` `DISCRETE_MAX_VALUES = 3`）
- 非数值列且 `n_unique <= round(n ** 0.7)` 且 `n_unique <= 100` → `categorical`
  （出处：`variable.py:48-104` `is_discrete_values`，`DISCRETE_MAX_ALLOWED_VALUES = 100`）
- 尝试 ISO 及常见日期格式解析，成功率 ≥ 95% → `datetime`
- 其余非数值 → `text`；其余数值 → `numeric`

**P0 范围限定**：只实现推断与只读展示。可编辑的 Domain Editor 网格属 P1。

**对原 SPEC 3.1 指纹的影响**：`table` 类型的上游指纹参与项由「上游节点指纹」扩展为
「上游节点指纹 + 上游输出 schema 的指纹」。schema 变化必须触发下游失效。

### 2.2 Artifact 格式（修改原 SPEC 3.3）

每个输出端口落盘为一个产物 + 一个 `.meta.json` 侧车：

```
.cache/<fingerprint>/<port_id>.parquet        # kind=table
.cache/<fingerprint>/<port_id>.meta.json      # {kind, schema?, summary, created_at}
.cache/<fingerprint>/<port_id>.figure.json    # kind=figure（plotly JSON）
.cache/<fingerprint>/<port_id>.stats.json     # kind=stats
.cache/<fingerprint>/<port_id>.md             # kind=text
```

`summary` 字段供端口摘要 UI 使用（借鉴 `format_summary_details`），例如
`{"brief": "1523 × 12", "detail": "1523 行，12 列：8 numeric、3 categorical、1 datetime"}`。

### 2.3 节点注册表元数据扩展（修改原 SPEC 2.1）

```python
NodeSpec(
    type="ai_clean",
    category="clean",
    label="AI 清洗",
    label_en="AI Clean",
    description="用自然语言描述清洗意图，由 AI 生成 pandas 代码",
    keywords=("清洗", "缺失值", "去重", "clean", "dedupe"),   # 供快速搜索
    icon="clean",
    priority=100,                       # 分类内排序
    inputs=[Port("table_in", "table")],
    outputs=[Port("table_out", "table", default=True)],
    params_schema=[...],
    messages=MessageCatalog(...),       # 见 2.4
    is_ai=True,
    code_profile="ai",                  # 见 2.7
    schema_version=1,
    replaces=(),                        # 旧 type 名，供工作流迁移
    doc_md="nodes/ai_clean.md",
    build_code=...,                     # 或 execute
)
```

`GET /api/nodes` 返回全部上述字段，前端据此渲染面板、搜索、排序、帮助入口。

### 2.4 声明式消息目录（修改原 SPEC 5.2）

每个节点声明自己的消息目录，precheck 与运行期共用同一套 code：

```python
messages = MessageCatalog(
    error={
        "missing_column": ("列「{col}」不存在于上游数据", "请检查上游节点输出或重新选择列"),
        "empty_result":   ("清洗后结果为空表", "放宽清洗条件或检查上游数据"),
    },
    warning={
        "high_null": ("列「{col}」缺失率达 {pct}", "考虑先用 Missing Value Handler 处理"),
    },
    info={
        "sampled": ("已按「{policy}」策略采样 {n} 行", ""),
    },
)
```

对外契约与原 SPEC 5.2 完全兼容，仍为
`{node_id, level, code, message, fix_hint}`，只是来源从散装字符串变为声明式目录。
好处：消息可枚举、可测试、可在前端按 code 做本地化，且运行期错误与体检错误共用同一展示通路。

### 2.5 端口扩展（修改原 SPEC 2.2、5.1）

```python
Port(id, type, label, required=True, multiple=False, default=False)
```

- `default=True`：两节点间存在多组类型兼容端口时的默认连接目标
  （借鉴 `Output(default=True)`，出处 `owselectrows.py:143`）
- `multiple=True`：该输入端口可接多条连线（Concat 等节点需要）
- 原 SPEC 5.1「一个输入端口只能连一条线」的约束改为：
  **`multiple=False` 时只能连一条（新连线替换旧连线）；`multiple=True` 时可接多条。**

**多输出通道的直接应用**：Filter 节点输出改为
`matched`（default）与 `unmatched` 两个 `table` 端口，借鉴 `OWSelectRows`。

### 2.6 样本值 PII 脱敏（补充原 SPEC 4.2、4.6）

**风险守门员强制条款。** 发送给模型的 `samples` 必须先经过基于正则的 PII 脱敏：

- 手机号、身份证号、银行卡号、邮箱、连续 ≥11 位数字串 → 掩码为 `<masked:phone>` 等类型标签
- 其余值保留原样但截断至 32 字符

注意**不是**一刀切掩码：原 SPEC 4.2 的示例里 `" 北京"` / `"shanghai "` 恰恰是模型判断需要标准化的依据，
一刀切会直接摧毁 AI 生成质量。设置项 `send_raw_samples` 默认 `false`，需用户显式开启。

### 2.7 沙箱双档校验（修改原 SPEC 5.3）

原 SPEC 的禁用清单存在一个具体缺口：`pd.read_csv('/etc/passwd')` 不在任何禁用项内。
引入两档校验档位：

| 档位 | 适用 | 策略 |
|---|---|---|
| `trusted` | 内置节点的模板代码（File Input 需 `pd.read_csv(INPUT_PATH)`） | 白名单 + 允许 IO helper |
| `ai` | AI 生成代码、用户手改代码 | 额外禁用全部 `read_*` / `to_*` / `*_json` 等 IO 方法；数据只能经父进程注入的 `df` 变量进入 |

档位由 `NodeSpec.code_profile` 声明，由执行器强制，**不接受运行时提升**。

### 2.8 子进程隔离（补充原 SPEC 5.3）

**风险守门员强制条款。** 以下六项须各自有独立的对抗测试，全绿之前 AI 生成代码不得自动执行：

| 项 | 实现 | 备注 |
|---|---|---|
| CPU 限制 | `RLIMIT_CPU = 30s` | macOS 有效 |
| 内存限制 | `RLIMIT_AS = 2GB` + **RSS 轮询看门狗** | macOS 上 `RLIMIT_AS` 常被忽略，必须有看门狗兜底 |
| 网络禁用 | 子进程内替换 `socket.socket` / `socket.create_connection` 为抛异常 | 与校验器禁用 `urlopen`/`connect` 形成双保险 |
| 文件系统 | `cwd` = 临时目录；`__builtins__` 移除 `open`；`ai` 档禁全部 IO 方法 | |
| 超时 | 父进程 35s 硬 kill | |
| 逃逸 | 复用现有 44 条 AST 对抗测试 + 子进程侧实测 | |

启动方式固定为 `multiprocessing` 的 **spawn**，不继承父进程状态。

### 2.9 工作流格式版本化（修改原 SPEC 7.2 的 import/export）

```json
{
  "format_version": 2,
  "nodes": [
    {"id": "uuid", "type": "ai_clean", "schema_version": 1,
     "position": {"x": 0, "y": 0}, "title": "清洗城市字段",
     "params": {}, "code": null, "code_locked": false}
  ],
  "edges": [{"id": "...", "source": "...", "sourceHandle": "table_out",
             "target": "...", "targetHandle": "table_in"}],
  "annotations": []
}
```

- 加载时按 `NodeSpec.replaces` 映射旧 `type` 名（借鉴 `resolve_replaced`）
- 节点 `schema_version` 低于当前值时调用 `NodeSpec.migrate_params(params, from_version)`
- **禁止 pickle**，任何情况下只用 JSON
- `annotations`（画布文字/箭头注释）在 P0 只做**存储直通**，渲染属 P1

### 2.10 AI 输出契约预留 `steps`（补充原 SPEC 4.3）

```json
{"code": "...", "explanation": "...", "assumptions": ["..."], "steps": null}
```

`steps` 为可选字段。**P0 只持久化到 `node_runs`，不消费。**
P1 实现消费后，AI 可产出结构化步骤列表（借鉴 `PreprocessorList`），
使 AI 输出从「消耗品」变为可审计、可重放、可跨数据集迁移的「资产」。
现在预留是为了避免 P1 时的存储格式返工。

### 2.11 参数控件封闭白名单（守卫原 SPEC 2.1）

`params_schema` 中的 `type` 只能取自下列封闭集合，由通用渲染器统一实现：

**P0 基础控件**：`string` `text` `number` `boolean` `select` `multiselect`
`column` `columns` `expression` `code` `file` `model` `json`

**P1 复合控件**：`schema_editor`（Domain Editor 网格）、`step_stack`（可拖拽排序的步骤栈）、
`condition_builder`（条件树）

**硬性条款**：新增控件类型必须先加入本白名单并由通用渲染器实现。
**任何情况下不得为单个节点手写前端组件** —— 这是原 SPEC 2.1 的实现底线，
也是反推顾问识别出的第 7 号死法（前端被富交互需求逼迫架空声明式架构）的防线。

`column` / `columns` 控件按 `Column.kind` 与 `role` 过滤候选列（借鉴 `DomainModel`）。

---

## 3. 修订后的 P0 验收条件

在原 SPEC 第 8 节 11 条清单之上，追加/修改：

- [ ] **（门禁）子进程隔离六项对抗测试全绿** —— 未通过则 AI 代码不得自动执行
- [ ] **（门禁）样本值 PII 脱敏默认开启** —— 未通过则不得对接真实 ZenMux
- [ ] `TableSchema` 推断实现，并参与指纹计算；schema 变化触发下游失效
- [ ] 每个节点声明 `MessageCatalog`，precheck 与运行期共用
- [ ] `params_schema` 控件类型全部落在白名单内，无任何单节点定制前端组件
- [ ] 工作流 JSON 带 `format_version`，`replaces` 迁移有测试覆盖
- [ ] AI 双档校验（`trusted` / `ai`）由执行器强制，有测试覆盖
- [ ] **主链路端到端跑通并产出真实 PDF**（> 20KB 且含图像对象），由 E2E 测试断言

最后一条是唯一可信的完成信号。前 7 条打勾但最后一条未过，视为 P0 未完成。

---

## 4. 七天最小验证计划

| 日 | 动作 | 花费 | 观测指标 |
|---|---|---|---|
| D1–D2 | 重写内核：Schema 模型、注册表、沙箱子进程隔离、执行引擎 | $0（全程 mock AI） | AST 对抗测试 44 条 + 子进程隔离 6 条全绿 |
| D3 | P0 八节点 + 导出层 | $0（mock AI） | E2E 用 mock AI 跑通主链路，PDF > 20KB 且含图像对象 |
| D4–D5 | React 19 + React Flow 12 前端 | $0 | vitest 覆盖：连线类型拦截、环拒绝、撤销栈 ≥20 步 |
| D6 | **首次接真实 ZenMux** | **上限 $5，超支即停** | 同一份 iris.csv 跑 10 次主链路 |
| D7 | 复盘 | — | 见下方判据 |

**D6 三项硬指标**：

1. AI 首次生成代码通过 AST 校验的比例 **≥ 70%**
2. 自愈（≤2 次）后最终成功率 **≥ 95%**
3. 单次完整运行 token 消耗 **< 15k**

**D7 复盘判据**：

- 首次通过率 **< 50%** → 白名单过严或 prompt 不足。此时**不得继续加节点**，
  必须先调整校验策略或 prompt，重跑 D6。（对应反推顾问第 3 号死法）
- 首次通过率 **≥ 70%** 且 PDF 产出正常 → P0 验收通过，按 §1.2 进入 P1
- token > 30k/次 → 检查是否误发了整表数据（原 SPEC 4.2 边界被破坏）

---

## 5. 委员会未决事项（需用户拍板）

1. 遗留原型的 `app/static/*`（vanilla JS 界面）在 React 前端就位后是否删除
2. D6 的 $5 预算是否可接受，或需先用更便宜的模型试跑
