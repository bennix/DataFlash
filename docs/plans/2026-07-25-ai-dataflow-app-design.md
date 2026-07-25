# AI 驱动数据分析可视化 Flask 应用 — SPEC

状态：已与用户完成头脑风暴确认，交付实现方前的最终设计文档。
实现方：另一个 AI（非本对话）。本文档是唯一权威 SPEC。

---

## 0. 一句话描述

一个本地运行的 Flask 应用，用户像 ComfyUI 一样拖拽节点、连线搭建数据处理流水线：拖入 CSV/Excel/JSON/SQLite 数据 → 经过 AI 驱动的清洗/规整/分析/可视化/报告节点 → 导出 MD/PDF/HTML。AI 通过 ZenMux 平台调用，节点执行代码在本地沙箱运行，数据不出本机。

---

## 1. 技术栈

- **后端**：Flask（Python 3.11+），SQLite 持久化，SSE 推送执行状态
- **前端**：React 19 + React Flow 12 + Vite + TypeScript，构建产物由 Flask 托管（`app/static/dist/`）
- **AI**：ZenMux（OpenAI 兼容 API），`base_url="https://zenmux.ai/api/v1"`
- **PDF**：Markdown → HTML → WeasyPrint；图表经 kaleido 导出 PNG 内嵌
- **沙箱**：AST 白名单校验 + `multiprocessing` 子进程 + 资源限制（无 Docker 依赖）
- **数据规模**：单文件 ≤ 200MB / ≤ 50 万行；超限拦截并要求用户选择采样策略

---

## 2. 整体架构

```
┌─────────────────── 浏览器 ───────────────────┐
│  React 19 + React Flow 12 + Vite + TS        │
│  ├ Canvas      节点拖拽/连线/缩放/框选/minimap │
│  ├ NodePanel   每节点参数表单 + 代码编辑器      │
│  ├ Inspector   数据预览(前100行) / 图表 / 日志  │
│  └ Settings    API-KEY / 模型列表管理           │
└──────────────── REST + SSE ──────────────────┘
                      ↓
┌─────────────────── Flask ────────────────────┐
│  api/          蓝图: workflows, run, ai,      │
│                nodes, settings, export        │
│  engine/       DAG拓扑排序 · 指纹缓存 · 执行器  │
│  sandbox/      AST校验 → 子进程 → 资源限制      │
│  ai/           ZenMux客户端 · Prompt模板 · 重试 │
│  nodes/        节点注册表(声明式 schema)        │
│  store/        SQLite: workflows/runs/settings │
│  cache/        .cache/<run_id>/<node>.parquet  │
└──────────────────────────────────────────────┘
```

### 2.1 声明式节点注册表（核心架构决定）

每个节点类型是一个后端 Python 文件，导出一个 `NodeSpec`：

```python
NodeSpec(
    type="ai_clean",
    category="clean",
    label="AI Clean",
    inputs=[Port("table_in", "table")],
    outputs=[Port("table_out", "table")],
    params_schema=[...],       # 前端自动渲染表单
    is_ai=True,
    execute=ai_clean_execute,  # 或 generate_code + run_sandboxed
)
```

前端启动时 `GET /api/nodes` 拉取全部定义，**据此自动渲染节点外观、端口、参数表单**。新增节点类型只需新增一个后端文件并注册，前端零改动。这是 20+ 节点数量可控的前提，实现方不得偏离此模式（例如为每个节点手写前端组件）。

### 2.2 端口类型系统（连线防呆基础）

类型集合：`table`（DataFrame）、`figure`（plotly JSON）、`stats`（分析结果 dict）、`text`（Markdown 字符串）、`file`（文件路径）。

拖拽连线时，类型不兼容的目标端口置灰（`opacity: 0.25`）且拒绝吸附。

### 2.3 进程模型

Flask 单进程 + 线程池执行 DAG（同层无依赖节点并发，默认并发数 4）。每个节点的实际计算（尤其 AI 生成代码）在 `multiprocessing` 子进程中执行，父子进程间只传递文件路径和状态，不通过 IPC 传递 DataFrame。

---

## 3. 执行引擎

### 3.1 指纹（fingerprint）与增量缓存

```
fp(node) = sha256(
    node.type            +
    canonical(params)    +   # 参数排序后序列化
    code_hash            +   # AI 生成或用户手改的代码
    ''.join(fp(upstream)) +  # 上游所有节点的指纹，按端口顺序拼接
    input_file_mtime_size    # 仅文件输入类节点携带
)
```

- 指纹命中 `.cache/<fp>.parquet`（或 `.json`，非表格输出）→ 跳过执行，节点状态标记为 `cached`
- 指纹未命中 → 标记 `dirty`，需要重新执行
- 修改任意上游参数/代码 → 该节点及其所有下游指纹链式失效，自动标记 dirty，用户无需手动管理依赖关系
- 支持"运行到指定节点"（只跑该节点及其未缓存的祖先），也支持"运行全部"

### 3.2 执行流程

```
POST /api/run  {workflow_id, target_node?}
  ↓
1. 拓扑排序（Kahn 算法），同时检测环
   → 有环：不执行，HTTP 422，返回环上涉及的 node_id 列表
2. 执行前体检（见第 5 节），存在 error 级问题
   → 不执行，HTTP 422，返回结构化问题清单
3. 按拓扑序遍历；同一"层"（无相互依赖）的节点用线程池并发处理
4. 对每个节点：
   a. 计算指纹，命中缓存则直接跳过，读取缓存产物
   b. 未命中：
      - 若为 AI 节点，先调用 AI 生成代码（除非用户已锁定自定义代码）
      - AST 白名单校验代码
      - 子进程执行，注入受限命名空间
      - 成功 → 写入 `.cache/<fp>.parquet` 或对应格式
      - 失败 → 见 5.3 自愈流程
5. 全程通过 SSE 推送事件：
   node_start / node_log / node_done / node_error / node_cached / run_done
```

### 3.3 数据传递方式

父进程不持有子进程计算出的 DataFrame。子进程启动后：
1. 从磁盘读取所有上游节点的 parquet 产物为 `df`（或多个 `df1, df2...`，Join 类节点）
2. 构造受限命名空间，仅注入 `df`（或多个）、`pd`、`np`、`plotly`（及节点类型特定的白名单符号）
3. `exec()` 该代码
4. 将命名空间中约定变量名的结果（如 `result` / `fig`）序列化写回磁盘
5. 通过 `multiprocessing.Pipe` 仅回传执行状态、stdout/stderr、耗时 —— 不回传 DataFrame 本体

### 3.4 大文件保护

文件输入节点读取前先用 `pd.read_csv(nrows=0)` 探测列结构，再检查文件大小。超过 200MB 或预估行数超过 50 万行时：
- 不静默处理，也不直接拒绝
- 前端弹窗，提供三个选项：**取前 N 行** / **随机采样 N 行** / **仍然全量处理（附警告：可能很慢）**
- 用户选择被记录进节点参数，参与指纹计算

---

## 4. AI 层与 ZenMux 集成

### 4.1 客户端

- OpenAI 兼容 SDK，`base_url="https://zenmux.ai/api/v1"`
- 统一封装在 `ai/client.py`；调用带指数退避重试（仅对 429/5xx，最多 3 次）
- 单次调用超时 60s
- 每次调用记录 `token_in` / `token_out` / 预估费用，写入 `runs` 表

### 4.2 发送给模型的上下文 —— 严格限量，数据不出本机

**只发 schema + 每列 ≤3 个样本值 + 统计摘要，绝不发送整表数据。**

```json
{
  "node_type": "ai_clean",
  "intent": "去掉空值并把城市标准化",
  "schema": [
    {"col": "name", "dtype": "object", "null_pct": 0, "n_unique": 8421,
     "samples": ["张伟", "李娜", "王芳"]},
    {"col": "age", "dtype": "float64", "null_pct": 0.12,
     "min": 18, "max": 87, "mean": 34.2},
    {"col": "city", "dtype": "object", "null_pct": 0.03, "n_unique": 31,
     "samples": [" 北京", "shanghai ", "广州"]}
  ],
  "row_count": 152340
}
```

这既是隐私边界（原始数据不出本机），也是成本边界（单次 prompt 稳定在 1–2k token，不随数据量增长）。

### 4.3 输出契约

模型必须返回严格 JSON：

```json
{"code": "...", "explanation": "...", "assumptions": ["..."]}
```

- 解析失败 → 重试一次，prompt 中附带解析错误信息
- 再次失败 → 节点标记为 error，展示模型原始返回供人工查看
- `explanation` 和 `assumptions` 展示在节点面板，让用户一眼看出 AI 做了什么假设

### 4.4 Prompt 分层

- **system prompt**：角色定义 + 安全约束（"只能使用注入的 df/pd/np/plotly，禁止 import、文件 IO、网络访问"）+ 输出格式要求，由代码固定，用户不可修改
- **user prompt**：意图描述 + schema 摘要，动态拼装

system prompt 里的安全声明与 AST 校验器（第 5.3 节）形成双保险 —— 前者约束模型倾向，后者是真正的强制边界。

### 4.5 模型管理（设置页）

预置 5 个模型，可增删：
- `anthropic/claude-sonnet-4.6`
- `z-ai/glm-5v-turbo`
- `openai/gpt-5.4`
- `anthropic/claude-opus-5`
- `moonshotai/kimi-k3`

每个节点可单独指定模型，默认继承全局设置。建议默认：代码生成类节点 → `anthropic/claude-sonnet-4.6`；报告写作类节点（AI Report / AI Insight）→ `anthropic/claude-opus-5`。

### 4.6 API-KEY 存储

- Fernet 对称加密后存入 SQLite `settings` 表
- 加密密钥派生自机器标识 + 应用盐，存放于 `~/.dataflash/.keyfile`（权限 0600）
- `GET /api/settings` 只返回 `{"configured": true, "masked": "sk-••••a3f2"}`，**明文永不传输到前端**
- 明文仅在服务端调用 ZenMux 时于内存中短暂解密使用
- 未配置 API-KEY 时，首页横幅提示并引导至邀请链接：`https://zenmux.ai/invite/GBQMC5`

---

## 5. 防呆机制（硬性验收条件）

### 5.1 连线合法性

- 拖拽开始时，所有类型不兼容的端口立即置灰（`opacity: 0.25`），无法吸附连线
- 每次 `onConnect` 前执行环检测（DFS），会形成环的连线被拒绝，toast 提示环路径（node id 序列）
- 一个输入端口只能连一条线（新连线自动替换旧连线）；一个输出端口可扇出多条线

**验收标准**：
- `table` 类型输出端口无法连接到 `figure` 类型输入端口
- 建立 A→B→C 后，尝试连接 C→A 必须被拒绝并提示

### 5.2 执行前体检

运行前调用 `POST /api/precheck`，一次性返回所有问题：

```json
[{"node_id": "...", "level": "error|warn", "code": "...",
  "message": "...", "fix_hint": "..."}]
```

检查项：

| 检查项 | 级别 |
|---|---|
| 孤立节点 / 必填输入口未连接 | error |
| 必填参数为空 | error |
| AI 节点但 API-KEY 未配置 | error |
| 输入文件不存在或已被外部修改 | error |
| 参数中引用的列名不存在于上游 schema | error |
| 文件超 200MB / 50 万行 | warn（需用户确认） |
| 存在下游无终端（Export/Preview）的分支 | warn |

任一 `error` 级问题存在 → `POST /api/run` 返回 HTTP 422，**不启动任何执行**；前端自动展开问题面板并高亮对应节点。绝不允许"跑到一半才报错"。

### 5.3 AI 输出校验 + 自愈

```
生成代码
  ↓
AST 白名单校验：
  禁止 = Import / ImportFrom 语句、以 __ 开头的属性访问、
         调用 open/eval/exec/compile/globals/getattr/__import__
  允许 = 表达式、赋值、if/for/while、函数定义、lambda、
         对已注入白名单符号（df/pd/np/plotly 等）的操作
  违规 → 不执行，节点标红，展示具体拦截原因
         （如"检测到 os.system 调用，已拦截"）
  ↓ 通过
子进程执行：
  RLIMIT_CPU = 30s
  RLIMIT_AS  = 2GB
  cwd        = 临时目录
  网络       = 禁用
  ↓
成功 → 落盘缓存
失败 → traceback 回传给 AI 请求修复
       （最多重试 2 次，每次 prompt 附带上一次的完整 traceback）
       仍失败 → 节点标红，展示人话错误摘要 + 建议，
                原始 traceback 折叠在"查看详情"区域
```

自愈上限 2 次是硬性约束，防止 AI 陷入无限重试消耗 token。

**AST 校验器必须附带专门的对抗测试集**（见第 7 节测试策略），覆盖以下攻击样本，每条都要有独立断言证明被拦截：
- `os.system(...)`
- `__builtins__`
- `getattr(df, '__class__')`
- `eval('...')`
- `open('/etc/passwd')`
- `exec(base64.b64decode(...))`
- 通过 `df.__class__.__bases__` 等间接路径进行的沙箱逃逸尝试

### 5.4 撤销与成本护栏

- `Ctrl+Z` / `Ctrl+Shift+Z` 撤销/重做，撤销栈深度 ≥ 20 步，覆盖节点增删、连线增删、参数修改、节点移动
- 破坏性操作需二次确认弹窗：删除节点、清空画布、覆盖同名工作流、删除 API-KEY
- 画布每 30 秒自动快照到 SQLite `snapshots` 表，保留最近 10 个，应用崩溃后可从快照恢复
- 顶部状态栏实时显示当前运行的 token 消耗与估算费用（USD）
- 单次运行的 AI 调用次数存在上限（默认 50，可在设置中调整），达到上限后暂停执行并询问用户是否继续

---

## 6. 节点清单（20+，分三批交付）

| 分类 | 节点 | 输入→输出 | AI | 批次 |
|---|---|---|---|---|
| **输入** | File Input (CSV/XLSX/JSON 拖放) | – → table | | P0 |
| | SQLite Query | – → table | | P1 |
| | Database Connector (PG/MySQL) | – → table | | P2 |
| | HTTP API Fetch | – → table | | P2 |
| | Manual Table (手输小表) | – → table | | P1 |
| **清洗** | AI Clean（缺失值/去重/异常/标准化） | table → table | ✦ | P0 |
| | Type Cast | table → table | | P1 |
| | Rename / Drop Columns | table → table | | P1 |
| | Deduplicate | table → table | | P1 |
| | Missing Value Handler | table → table | | P1 |
| **规整** | Filter（表达式 / AI 自然语言） | table → table | ✦ | P0 |
| | Aggregate (groupby) | table → table | | P1 |
| | Join / Merge | table×2 → table | | P1 |
| | Pivot / Unpivot | table → table | | P1 |
| | Sort / Top-N | table → table | | P1 |
| | Derived Column（AI 写公式） | table → table | ✦ | P1 |
| | Concat (纵向合并) | table×N → table | | P2 |
| **分析** | AI Analyze（描述统计/相关/异常/分布） | table → stats | ✦ | P0 |
| | Correlation Matrix | table → stats+figure | | P1 |
| | Time Series (重采样/趋势/季节性) | table → stats+figure | ✦ | P2 |
| | Regression / Clustering | table → stats+figure | ✦ | P2 |
| **可视化** | AI Chart（plotly，自动选图型） | table → figure | ✦ | P0 |
| | Chart Builder（手动配 x/y/color） | table → figure | | P1 |
| | Data Table View | table → – | | P1 |
| **报告** | AI Report（MD 正文 + 内嵌图表） | stats+figure+table → text | ✦ | P0 |
| | AI Insight（要点摘要） | stats → text | ✦ | P1 |
| | Report Compose（多段拼装 + 模板） | text×N → text | | P2 |
| **输出** | Export（MD / PDF / HTML / CSV / XLSX） | any → file | | P0 |
| | Preview（调试用，看任意端口） | any → – | | P0 |

### 6.1 交付批次纪律（硬性）

- **P0（骨架 + 8 节点）**：完整执行引擎、沙箱、AI 层、四条防呆机制（第 5 节）、SQLite 持久化、SSE 推送、设置页，加上能跑通以下主链路：
  `File Input → AI Clean → Filter → AI Analyze → AI Chart → AI Report → Export(PDF)`
  **P0 必须端到端可用，不是半成品或占位符。**
- **P1（+13 节点）**：纯 Python 或轻量 AI 的常规节点，依托声明式节点注册表接入，不修改引擎核心逻辑。
- **P2（+7 节点）**：涉及外部依赖（数据库连接、HTTP 拉取）和较重算法（时序分解、回归/聚类），风险最高，放最后交付。

**验收门禁**：P0 全部通过验收前，不允许开始 P1 的开发。此条款防止实现方将全部节点写成空壳而无一可用。

---

## 7. 数据模型、API 契约与测试

### 7.1 SQLite 表结构

```sql
workflows(id, name, graph_json, created_at, updated_at)

runs(id, workflow_id, status, started_at, finished_at,
     token_in, token_out, cost_usd, error_json)

node_runs(id, run_id, node_id, fingerprint, status,
          duration_ms, cache_hit, code, error, output_path)

settings(key, value_encrypted, updated_at)

snapshots(id, workflow_id, graph_json, created_at)
-- 自动快照，保留最近 10 个
```

### 7.2 REST + SSE 契约

```
GET    /api/nodes                     节点注册表(前端据此渲染所有节点类型)
GET    /api/workflows                 工作流列表
POST   /api/workflows                 新建工作流
GET    /api/workflows/:id             读取工作流
PUT    /api/workflows/:id             保存(自动保存也走此接口)
DELETE /api/workflows/:id             删除
POST   /api/workflows/:id/import      导入 .flow.json
GET    /api/workflows/:id/export      导出 .flow.json

POST   /api/precheck                  执行前体检 → 200 或 422 + 问题清单
POST   /api/run                       启动执行 → {run_id}
GET    /api/run/:id/stream            SSE 事件流
POST   /api/run/:id/cancel            中断执行

POST   /api/ai/generate               为单节点生成代码(仅生成，不执行)

GET    /api/preview/:run_id/:node_id  预览节点输出(前100行 / figure JSON)

POST   /api/export                    导出 MD/PDF/HTML/CSV/XLSX

GET    /api/settings                  {configured, masked_key, models[]}
PUT    /api/settings                  保存 API-KEY / 模型列表
POST   /api/settings/test             测试 ZenMux 连通性
```

### 7.3 测试策略（验收凭据）

| 层级 | 内容 | 工具 |
|---|---|---|
| 单元 | 指纹计算、拓扑排序、环检测、AST 校验器（含 20+ 恶意样本，须全部拦截）、体检规则 | pytest |
| 集成 | 每个节点的 execute 独立测试；沙箱超时/超内存/崩溃三种失败路径 | pytest |
| AI 层 | ZenMux 客户端用 mock 响应测试；JSON 解析失败重试路径；自愈上限 2 次的边界测试 | pytest + responses |
| E2E | 主链路：上传 CSV → 跑全图 → 导出 PDF，断言 PDF 非空且包含图表 | pytest + 真实 fixture |
| 前端 | 连线类型拦截、环拒绝、撤销栈行为 | vitest |

AST 校验器的对抗测试集清单见第 5.3 节，是本应用唯一的真安全边界，实现方必须为每一条攻击样本提供独立的拦截断言，不能只用一个笼统的"恶意代码被拒绝"测试覆盖。

---

## 8. 交付清单（供实现方自查）

- [ ] 声明式节点注册表跑通，新增节点无需改前端
- [ ] 端口类型系统 + 连线合法性拦截（含环检测）
- [ ] 执行引擎：拓扑排序、指纹缓存、链式失效、SSE 推送
- [ ] 沙箱：AST 白名单 + 子进程 + 资源限制，全部对抗测试样本通过
- [ ] AI 层：schema-only 上下文、JSON 输出契约、自愈重试上限 2 次
- [ ] 执行前体检：全部检查项、错误时不执行
- [ ] 撤销栈（≥20步）+ 破坏性操作二次确认 + 自动快照
- [ ] 成本护栏：token/费用实时显示 + AI 调用次数上限
- [ ] API-KEY 加密存储，前端永不获取明文
- [ ] P0 主链路端到端跑通并导出 PDF
- [ ] P0 通过全部验收后再开始 P1，P1 完成后再开始 P2
