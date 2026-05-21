# 价格库存证据复核

日期：2026-05-05

## 复核范围

本轮只做离线复核，不发送请求、不 replay、不接入正式上传。

分析脚本：

- `scripts/analyze_price_stock_capture.py`

输入样本：

- `tmp_runtime_probe_live/fxg_protocol_submit_only_deep_9222_2026-05-04_09-55-56.json`
- `tmp_runtime_probe_live/fxg_protocol_submit_only_block_9222_2026-05-04_08-51-48.json`

输出产物：

- `outputs/price_stock_capture_analysis_legacy_20260504.json`
- `outputs/price_stock_capture_analysis_submit_preflight_legacy_20260504.json`

## 可采信结论

旧 deep 样本可作为参考证据，证明当页面生成 `addWithSchema` 请求时，价格库存字段位于：

- `schema.model.sku_detail.value[].price`
- `schema.model.sku_detail.value[].stock_info.stock_num`

该样本中：

- `sku_count=7`
- `price_count=7`
- `stock_info_stock_num_count=7`
- `usable_spec_detail_ids_count=7`
- 未发现独立价格库存写接口

这只能证明“当前样本的最终提交 envelope 中包含价格库存字段”，不能证明价格库存可独立协议写入。

## 弱证据样本

`fxg_protocol_submit_only_block_9222_2026-05-04_08-51-48.json` 是 submit-preflight 样本，但其提交体存在 `<max-depth>` 截断。

复核结果：

- 可证明存在 `addWithSchema` 请求。
- 不能证明完整 `spec_detail_ids` 映射。
- 不能证明 `stock_info.stock_num` 字段细节。
- 不能作为价格库存字段映射闭环证据。

对应 blocker：

- `CAPTURE_SANITIZED_DEPTH_LIMIT`
- `SKU_SPEC_ID_GAP`
- `SKU_STOCK_INFO_GAP`

## 仍未闭环

- 未发现价格库存独立写接口。
- 未确认顶层 `stock` 与 `stock_info.stock_num` 的服务端关系。
- 未确认同一商品只改价格库存时，`sku_detail[].id` 与 `spec_detail_ids` 是否稳定。
- 未确认不同类目、多规格轴、SKU 图场景下字段形状是否一致。

## 下一步

下一步必须重新截停当前页面生成的 `addWithSchema/editWithSchema`，并提高脱敏深度，确保 `spec_detail.value[]`、`sku_detail.value[]`、`stock_info` 不被截断。

完成前不能把价格库存协议写入接入正式上传按钮。
