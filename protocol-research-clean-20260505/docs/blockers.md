# 阻塞项

## B001：价格库存真实独立接口未知

状态：打开，已缩小范围

说明：当前目标是价格库存阶段，但尚未在本目录重新确认它是否存在独立接口，还是只能通过 `addWithSchema/editWithSchema` envelope 进入。

2026-05-05 只读探针已确认：

- `sku_detail.price` 是 SKU 必填列。
- `sku_detail.stock_info` 是 SKU 必填列。
- 前端提交 schema 中存在 `stock` 与 `stock_info` 字段形状。

仍未确认：

- 是否存在价格库存独立写接口。
- 如果没有独立接口，是否只能通过 `addWithSchema/editWithSchema` envelope 写入。
- `stock` 与 `stock_info.stock_num` 是否都必须同时存在。

2026-05-05 离线复核旧 deep 样本：

- 产物：`outputs/price_stock_capture_analysis_legacy_20260504.json`
- 参考样本中 `sku_detail.value[].price` 完整出现。
- 参考样本中 `sku_detail.value[].stock_info.stock_num` 完整出现。
- 参考样本中未发现独立价格库存写接口。
- 该证据仍是旧样本复核，不代表本目录当前 live 实证。

需要证据：

- 价格库存字段所在请求体。
- 服务端接受价格库存变更的最小字段集。
- `stock` 与 `stock_info` 的真实关系。

## B002：SKU 标识依赖关系未知

状态：打开

说明：价格库存写入可能依赖 `sku_detail[].id`、`sku_id`、`spec_detail_ids` 或规格值 ID。若这些标识无法稳定映射，价格库存阶段不能独立落地。

2026-05-05 离线复核旧样本：

- `outputs/price_stock_capture_analysis_legacy_20260504.json` 中 7 行 SKU 均有 `id` 与可用 `spec_detail_ids`。
- `outputs/price_stock_capture_analysis_submit_preflight_legacy_20260504.json` 因 `<max-depth>` 截断，不能证明完整映射。

需要证据：

- 本地 SKU 与页面 SKU 行的稳定对应关系。
- 协议 body 中 SKU 行标识与页面显示规格的映射。

## B003：敏感请求不能直接落盘

状态：常驻

说明：请求中可能带 token、签名参数、cookie、店铺信息等敏感数据。研究产物必须去敏，必要时只保存字段形状、摘要和差异。

## B005：SKU 规格图 sku_pic 字段已确认但未截获真实请求体验证

状态：打开（新，可缩小范围）

说明：2026-05-07 提交探针（submit probe）通过 Webpack 源码分析确认了 `sku_detail[].sku_pic` 字段形状为 `array<string>`，且 `addWithSchema` body 合并路径清晰。

已确认：

- `sku_pic: y.YOg(y.YjP()).optional()` — 直接接受 URL 字符串数组。
- `addWithSchema` 请求体可由 schema 对象 + context + pass_through_extra 组装。
- 规格图不经过 `saveMaterial`/`batchApplyMaterial`（这些是主图装修/白底图专用的）。

仍未确认：

- 局部补丁：能否通过 `editWithSchema` 仅修改单个 SKU 的 `sku_pic` 而不携带完整商品数据？
- 服务端接受的最小 `sku_detail` 条目结构（是否必须包含 `id`、`spec_detail_ids` 等标识字段）。
- 多个 SKU 批量上传规格图时，接口链的最优编排（先全部 batchupload → 再一次性 addWithSchema，还是其它顺序）。

需要证据：

- 一个真实的 `addWithSchema` 请求体，包含 `sku_detail[].sku_pic` 的非空值。
- 或一个 `editWithSchema` 请求体，只补丁 `sku_pic` 字段。

## B004：截停产物脱敏深度不足会破坏证据

状态：打开

说明：如果抓包产物中出现 `<max-depth>` 或 `<unsupported>`，只能证明字段或请求大致存在，不能证明完整字段映射。

已发现样本：

- `outputs/price_stock_capture_analysis_submit_preflight_legacy_20260504.json`

处理规则：

- 有截断标记的样本不能作为完整 `spec_detail/sku_detail` 映射证据。
- 后续 capture 必须提高脱敏深度或为 `spec_detail`、`sku_detail` 输出专用摘要。

2026-05-05 已处理一部分：

- `mcp-server/scripts/capture-fxg-submit-preflight.mjs` 的默认脱敏深度和输出上限已提高。
- 该 blocker 对旧样本和非一键脚本产物仍然有效。
