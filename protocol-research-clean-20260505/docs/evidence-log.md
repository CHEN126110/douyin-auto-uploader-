# 证据日志

本文件按时间记录本目录产出的证据。每条证据必须能回答：来源是什么、证明了什么、不能证明什么。

## 2026-05-05

- 创建干净研究区。
- 生成第一轮代码基线：`docs/source-baseline.md`。
- 当前未产生新 live 接口实证。
- 旧目录、旧文档、旧抓包只能作为参考线索，不能直接作为本目录结论。
- 收到用户贴出的 Cookie-Editor 导出内容。原始 Cookie 未写入本目录；只补充 `docs/cookie-handling.md` 和去敏脚本 `scripts/sanitize_cookie_export.py`。
- 明确核心目标为“协议化自动化流水线”，新增 `docs/protocol-pipeline-goal.md` 与 `docs/interface-discovery-plan.md`。
- 启动专用 CDP Chrome，并确认发布页环境可用。
- 完成第一批只读探针，产物写入 `schemas/`。
- 新增 `docs/first-probe-summary-20260505.md`，并更新 `docs/interface-map.md` 与 `docs/blockers.md`。
- 发现探针原始产物包含 `publishId/session_publish_id`，已新增 `scripts/sanitize_fxg_probe_outputs.py` 并对本轮 `schemas/fxg_*.json` 就地脱敏。
- 继续运行上传模块扫描、素材模块扫描、资质模块扫描；未设置 `UPLOAD_IMAGE_PATH`，未触发样本上传。
- 更新接口矩阵，补入媒体、素材、白底图和资质接口候选。
- 新增离线价格库存截停样本分析脚本：`scripts/analyze_price_stock_capture.py`。
- 用旧 deep 样本生成 `outputs/price_stock_capture_analysis_legacy_20260504.json`：确认参考样本里 `price` 与 `stock_info.stock_num` 位于 `schema.model.sku_detail.value[]`，但仍未发现独立价格库存接口。
- 用旧 submit-preflight 样本生成 `outputs/price_stock_capture_analysis_submit_preflight_legacy_20260504.json`：发现该样本存在 `<max-depth>` 截断，只能证明请求存在，不能证明完整 SKU 映射。
- 新增 `docs/price-stock-evidence-review-20260505.md`，明确旧样本只能作为参考证据，不升级为本目录当前 live 实证。
- 调整 `mcp-server/scripts/capture-fxg-submit-preflight.mjs` 默认输出参数：提高 `POST_DATA_PREVIEW_LIMIT`、`SANITIZE_MAX_DEPTH`、`SANITIZE_ARRAY_LIMIT`、`SANITIZE_OBJECT_LIMIT`，降低后续 `spec_detail/sku_detail` 被 `<max-depth>` 截断的概率；该调整不改变本地截停语义。
- 运行 `npm run check:cdp`，确认 `http://127.0.0.1:9333/json/list` 下有可用 FXG 发布页，页面非登录页且可见 `主图`、`商品标题`；当前仍在发布第一页，适合只读探针，不适合立即截停 `addWithSchema`。
- 使用 `项目备份 禁止改动使用 只参考/C-975/主图/白底.jpg` 执行真实单图上传验收。首次请求成功但产物中的中文文件名出现 mojibake；随后为 `mcp-server/fxg-upload-probe.js` 增加 `UPLOAD_FILE_NAME`，用 `c975-white-bg.jpg` 重新上传并通过。
- 正式采信产物：`captures/fxg_upload_sample_c975_white_bg_ascii_20260505.json`。结果：`POST /product/img/batchupload` HTTP 200、`code=0`、返回 1 条平台图片 URL。
- 为 `mcp-server/fxg-upload-probe.js` 增加 `UPLOAD_IMAGE_PATHS` / `UPLOAD_FILE_NAMES`，支持多图 batch 验收。
- 使用 `C-975/主图/TM.png` 与 `C-975/主图/白底.jpg` 执行真实批量上传验收。正式采信产物：`captures/fxg_upload_batch_c975_main_images_20260505.json`。结果：`POST /product/img/batchupload?_bid=ffa_goods` HTTP 200、`code=0`、返回 2 条平台图片 URL。
- 新增 `docs/upload-evidence-review-20260505.md`，并将 `/product/img/batchupload` 标记为 `server_accept_verified`。

## 记录模板

### YYYY-MM-DD HH:mm

- 目标：
- 操作：
- 产物：
- 已证明：
- 未证明：
- blocker：
- 下一步：
