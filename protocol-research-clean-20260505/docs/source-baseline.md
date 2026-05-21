# 第一轮代码基线

采集日期：2026-05-05

本文件只记录当前源码中的入口和线索。它不代表接口已在本目录完成 live 实证。

## 正式上传流水线

正式上传入口位于：

- `tauri-app/python-sidecar/app.py`
- 函数：`_execute_upload_flow`
- 任务 API：`POST /api/upload/start`

当前源码中的阶段顺序：

1. `open_publish_page`
2. `fill_title`
3. `upload_main_images`
4. `select_category`
5. `fill_category_attributes`
6. `upload_media_assets`
7. `configure_sku_entries`
8. `configure_sku_structure`
9. `fill_price_and_stock`
10. `submit_publish`

阶段耗时由 `_run_stage_with_timing` 记录。后续如果要判断“慢在哪里”，优先读取阶段耗时日志，而不是凭体感改代码。

## 当前最该观察的阶段

第一优先级：`fill_price_and_stock`

源码位置：

- `tauri-app/python-sidecar/app.py`
- 函数：`_fill_price_stock_and_delivery`

原因：

- 该阶段处于 SKU 结构之后、最终提交之前。
- DOM 写入表格天然慢且容易受虚拟滚动、输入框状态和页面渲染影响。
- 如果能形成独立协议执行器，收益清晰且影响面比完整提交小。

## 现有协议化骨架

协议化发布骨架位于：

- `tauri-app/python-sidecar/protocol_publish/engine.py`

源码中已有阶段模型：

- `session`
- `open_publish_page`
- `title`
- `main_images`
- `category_selection`
- `category_attributes`
- `media`
- `sku_entries`
- `sku_structure`
- `price_stock`
- `submit`

当前判断：这是阶段模型和研究承载层，不等同于正式协议上传能力。

## 价格库存旧实验分支

源码位置：

- `tauri-app/python-sidecar/protocol_publish/stages/price_stock_runtime.py`
- `tauri-app/python-sidecar/protocol_publish/stages/price_stock_protocol.py`

观察到的门禁：

- `DYIN_PRICE_STOCK_WRITE_MODE`
- `DYIN_PRICE_STOCK_ENABLE_SAVE_DRAFT_PROBE`

当前判断：

- 该分支仍依赖保存草稿抓包和 replay 思路。
- 它可以作为研究参考。
- 不能直接当作新研究区的正式阶段执行器。

## 2026-05-05 实现复核补充

发布侧：

- 正式入口 `POST /api/upload/start` 仍走 `tauri-app/python-sidecar/app.py` 的 DOM 上传主链。
- `protocol_publish` 目录当前是 dry-run、探针、字段审计和阶段骨架；没有接管正式上传。
- 旧价格库存协议分支默认 `DYIN_PRICE_STOCK_WRITE_MODE=dom`，协议分支还需要 `DYIN_PRICE_STOCK_ENABLE_SAVE_DRAFT_PROBE=1`，不能作为正式能力。

采集侧：

- `protocol_capture` 当前是运行记录和产物骨架，不是独立协议采集执行器。
- 1688 采集已有页面状态对象提取基础，但仍不是完整接口化采集。
- 淘宝/天猫商品采集仍以 DOM 和页面状态混合为主。

## 可复用但不直接改动的工具入口

现有 MCP/CDP 工具位于：

- `mcp-server/package.json`
- `mcp-server/cdp-tools.js`
- `mcp-server/fxg-protocol-capture.js`

脚本入口：

- `npm run start:fxg-cdp`
- `npm run check:cdp`
- `npm run probe:fxg-schema`
- `npm run probe:fxg-runtime-options`
- `npm run probe:fxg-freight`
- `npm run probe:fxg-submit`
- `npm run capture:fxg-protocol`
- `npm run capture:fxg-submit-preflight`

当前策略：

- 可以把这些脚本当作只读探针或截停工具。
- 不在本目录第一阶段修改这些脚本。
- 需要新增逻辑时，优先在本目录 `scripts/` 下写离线分析脚本。

## 下一步

下一步只做价格库存重新实证：

1. 先确认当前页面/CDP 环境是否可用。
2. 只观察价格库存阶段相关请求，不主动提交完整商品。
3. 输出去敏证据到 `captures/`。
4. 将字段状态回写到 `docs/interface-map.md` 和 `docs/blockers.md`。
