# 样例自定义节点：`custom.scale_numeric`

包结构：

- `manifest.json` — 类型、端口、参数控件
- `transform.py` — 沙箱内执行（可用 `df` / `params`，最终赋值 `result`）

修改本目录后，可打成 zip 上传，或直接放到 `instance/custom_nodes/<id>/`。

安全：代码经 AST 白名单校验，禁止 `open` / `import` / 文件 IO 等。
