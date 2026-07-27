# 样例：AI 自定义节点 `custom.ai_flag_rows`

与 `scale_numeric`（固定 `transform.py`）不同，本包声明：

```json
{ "is_ai": true }
```

- **不需要** `transform.py`
- 运行时根据 `intent` + 可选 `prompt.md` 调用模型生成沙箱代码
- 仍走 AST 白名单沙箱，可自愈最多 2 次

上传 zip 后，左侧 CUSTOM 会出现带 AI 徽标的「AI 行标记」。
