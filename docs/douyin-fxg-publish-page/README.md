# 抖店商品发布页 — 元素清单（本地归档）

本目录用于保存 **MCP 浏览器无障碍快照** 与 **人工整理后的结构化清单**，便于对照自动化脚本（`src/utils.py` / `tauri-app/python-sidecar/app.py`）。


| 文件                                    | 说明                                                                  |
| ------------------------------------- | ------------------------------------------------------------------- |
| `publish-page-element-inventory.yaml` | **主文档**：分区说明、`attr-field-id` / `#skuValue-`* 对照、各 `ref` 注释（合法 YAML） |
| `mcp-a11y-snapshot-raw.txt`           | MCP `browser_snapshot` 原始树（末尾含平台导出的重复 key，**勿当严格 YAML 解析**）         |


**隐藏元素**：无障碍树无法等价于「含 `display:none` 的完整 DOM」。若需完整 HTML，请在自动化浏览器中对目标容器执行 `outerHTML` 导出。

**更新**：在 Cursor MCP 浏览器打开目标页 → `browser_snapshot` → 覆盖或追加 `mcp-a11y-snapshot-raw.txt`，并同步修改 `publish-page-element-inventory.yaml`。