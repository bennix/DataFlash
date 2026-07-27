# DataFlash

本地 AI 数据分析流水线：拖拽节点构图 → 清洗 / 分析 / 可视化 / 报告 → 导出 MD / PDF / HTML。

**English:** [README below ↓](#dataflash-english)

---

## 中文

### 特性

- **可视化编排**：React Flow 画布，节点拖拽、连线、撤销重做
- **内置节点**：文件输入、筛选、Join、GroupBy、预览、导出，以及 AI 清洗 / 分析 / 图表 / 报告
- **自定义节点**：上传 `manifest.json` + `transform.py`（沙箱 AST 白名单）；可声明 `is_ai: true` 按意图生成代码
- **安全**：用户 / AI 代码默认在沙箱执行；ZenMux API Key **仅本机加密存储**，不进入仓库、不明文回传前端
- **示例与导入导出**：预置示例工作流；支持 `.flow.json` 导入导出

### 安全与密钥

| 内容 | 是否进仓库 |
| --- | --- |
| 源码、示例数据集、内置自定义节点样例 | ✅ |
| `instance/`（本地 SQLite、上传文件、用户自定义节点安装目录） | ❌ |
| `~/.dataflash/.keyfile`、`.env`、真实 API Key | ❌ |
| 前端构建产物 `app/static/dist`、`node_modules` | ❌（需本地构建） |

请在应用「设置」中填写 ZenMux API Key。邀请注册：https://zenmux.ai/invite/GBQMC5

### 环境要求

- Python ≥ 3.11（推荐 3.12）
- Node.js ≥ 18（前端构建）
- macOS 导出 PDF 时建议安装：`brew install pango libffi`

### 快速开始

```bash
git clone https://github.com/bennix/DataFlash.git
cd DataFlash

# 后端
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
# macOS + WeasyPrint：
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib

# 前端（构建到 app/static/dist，由 Flask 托管）
cd frontend && npm install && npm run build && cd ..

# 启动
./start.sh
# 或：.venv/bin/python -m app
```

浏览器打开 http://127.0.0.1:5000 ，在「设置」中配置 API Key 后即可使用 AI 节点。

无 Key 时可本地 mock（仅便于开发 / 测试）：

```bash
# 终端 1
AI_MOCK=1 .venv/bin/python -c "from app import create_app; create_app({'AI_MOCK': True}).run(port=5000, debug=True)"
# 终端 2（热更新）
cd frontend && npm run dev
```

### 自定义节点

1. 左侧「+ 上传 / 管理自定义节点」，或顶栏「自定义节点」
2. 下载样例 zip：
   - **沙箱样例** `scale_numeric`：固定 `transform.py`
   - **AI 样例** `ai_flag_rows`：`is_ai: true`，按意图生成代码
3. 修改后打 zip 上传；类型为 `custom.<id>`，不可覆盖内置节点

包结构示例：

```text
my_node/
  manifest.json    # id / ports / params_schema / is_ai?
  transform.py     # 非 AI 包必填；赋值 result（或 fig）
  prompt.md        # 可选，AI 包的生成约束
```

### 测试

```bash
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
.venv/bin/python -m pytest
cd frontend && npm test
```

### 文档

- 设计 SPEC：`docs/plans/2026-07-25-ai-dataflow-app-design.md`
- Orange3 借鉴增补：`docs/plans/2026-07-26-orange3-spec-delta.md`

### 许可证

源码默认按仓库所有者约定使用；若后续添加 `LICENSE` 文件则以该文件为准。

---

<a id="dataflash-english"></a>

## DataFlash (English)

Local AI data-analysis pipeline: drag-and-drop nodes → clean / analyze / visualize / report → export Markdown, PDF, or HTML.

### Features

- **Visual editor**: React Flow canvas with drag, connect, undo/redo
- **Built-in nodes**: file input, filter, Join, GroupBy, preview, export, plus AI clean / analyze / chart / report
- **Custom nodes**: upload `manifest.json` + `transform.py` (sandboxed AST allowlist); set `is_ai: true` to generate code from natural-language intent
- **Security**: user/AI code runs in a sandbox by default; ZenMux API keys are **encrypted on this machine only** — never committed, never returned in plaintext to the browser
- **Examples & I/O**: bundled example workflows; import/export `.flow.json`

### Secrets

| Item | In git? |
| --- | --- |
| Source, sample datasets, bundled custom-node samples | Yes |
| `instance/` (SQLite, uploads, installed user nodes) | No |
| `~/.dataflash/.keyfile`, `.env`, real API keys | No |
| `app/static/dist`, `node_modules` | No (build locally) |

Configure the ZenMux API key in **Settings**. Invite: https://zenmux.ai/invite/GBQMC5

### Requirements

- Python ≥ 3.11 (3.12 recommended)
- Node.js ≥ 18
- On macOS for PDF export: `brew install pango libffi`

### Quick start

```bash
git clone https://github.com/bennix/DataFlash.git
cd DataFlash

uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib   # macOS + WeasyPrint

cd frontend && npm install && npm run build && cd ..
./start.sh
# or: .venv/bin/python -m app
```

Open http://127.0.0.1:5000 and set your API key in Settings.

Mock AI (dev/test only, no key):

```bash
AI_MOCK=1 .venv/bin/python -c "from app import create_app; create_app({'AI_MOCK': True}).run(port=5000, debug=True)"
cd frontend && npm run dev
```

### Custom nodes

1. Use **+ Upload / manage custom nodes** in the left palette (or the top-bar button)
2. Download sample zips:
   - **Sandbox** `scale_numeric` — fixed `transform.py`
   - **AI** `ai_flag_rows` — `is_ai: true`, intent-driven codegen
3. Zip and upload; type is `custom.<id>` (cannot override builtins)

```text
my_node/
  manifest.json
  transform.py     # required unless is_ai
  prompt.md        # optional AI hint
```

### Tests

```bash
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
.venv/bin/python -m pytest
cd frontend && npm test
```

### Docs

- Design SPEC: `docs/plans/2026-07-25-ai-dataflow-app-design.md`
- Orange3 delta: `docs/plans/2026-07-26-orange3-spec-delta.md`
