# 接口地图

本文件只记录本目录重新验证后的接口状态。旧目录结论不能直接复制为已实证。

| 接口 | 方向 | 当前状态 | 证据文件 | 备注 |
| --- | --- | --- | --- | --- |
| `/product/tproduct/searchCategoryN` | 只读 | `readonly_verified` | `schemas/fxg_schema_long_socks_20260505.json` | 关键词 `长筒袜`，命中叶子类目 `1000010275` |
| `/product/tproduct/getSchema` | 只读 | `readonly_verified` | `schemas/fxg_schema_long_socks_20260505.json` | `modelKeyCount=53`，确认类目属性、规格轴、SKU 列 |
| `/product/tproduct/refetchSchema?action=freight_template_options_load` | 只读 | `readonly_verified` | `schemas/fxg_freight_long_socks_20260505.json` | 当前 `中通包邮=300713474`，模板数 8 |
| `/product/img/batchupload` | 写入 | `server_accept_verified` | `captures/fxg_upload_sample_c975_white_bg_ascii_20260505.json`、`captures/fxg_upload_batch_c975_main_images_20260505.json`、`docs/upload-evidence-review-20260505.md` | C-975 单图和批量真实上传验收通过：HTTP 200、`code=0`；单图字段 `image`，批量字段 `image[0]`/`image[1]` |
| `/product/tproduct/material/imageTextVideo/submitImgOptimizeTask4PC` | 写入/任务 | `source_hint` | `schemas/fxg_upload_probe_scan_20260505.json`、`schemas/fxg_material_probe_20260505.json` | 媒体优化/视频任务候选，未触发 |
| `/product/tproduct/material/imageTextVideo/queryImgOptimizeTask4PC` | 只读/任务查询 | `source_hint` | `schemas/fxg_upload_probe_scan_20260505.json` | 媒体任务查询候选 |
| `/common/img/IsWhiteBackgroundPic` | 只读/校验 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 白底检测候选，请求形状含图片 URL、商品名、商品 ID 等；未触发 |
| `/product/tproduct/img/IntelligentOptimizeVerify` | 校验/候选 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 图片智能优化校验候选 |
| `/product/img/trans_img_style` | 写入/生成 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | AI 白底图生成候选，未触发 |
| `/product/tproduct/saveMaterial` | 写入 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 素材保存候选，未触发 |
| `/product/tproduct/materialDetail` | 只读/详情 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 素材详情候选 |
| `/product/tproduct/material/batchApplyMaterial` | 写入 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 批量应用素材候选，未触发 |
| `/product/tproduct/submitWhiteImg` | 写入 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 白底图送审候选，`action_list` 仍缺真实值 |
| `/product/tproduct/batchApprovalWhiteImgs` | 写入 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 白底图审核候选 |
| `/product/tproduct/CancelProductMaterialPicAudit` | 写入 | `source_hint` | `schemas/fxg_material_probe_20260505.json` | 白底图审核撤销候选 |
| `/ffa/grs/qualification/list` | 只读/页面跳转 | `source_hint` | `schemas/fxg_qualification_probe_20260505.json` | 资质中心入口候选 |
| `/ffa/mshop/qualification/list` | 只读/页面跳转 | `source_hint` | `schemas/fxg_qualification_probe_20260505.json` | 店铺资质入口候选 |
| `/product/tproduct/addWithSchema` | 写入 | `source_hint` | `schemas/fxg_submit_probe_20260505.json`、`docs/sku-spec-image-binding-evidence-20260507.md` | 已确认 `sku_detail[].sku_pic` 字段（array<string>），可直接接受图片 URL；仍缺本地截停完整请求体 |
| `/product/tproduct/editWithSchema` | 写入 | `source_hint` | `schemas/fxg_submit_probe_20260505.json`、`docs/sku-spec-image-binding-evidence-20260507.md` | 同 addWithSchema，含 `product_id` 参数，可作为 SKU 补丁入口候选 |
| `/product/img/batchupload` → `sku_detail[].sku_pic` | 写入链 | **`schema_confirmed`** | `docs/sku-spec-image-binding-evidence-20260507.md` | **新增**：规格图上传后直接填入 `addWithSchema` 的 `sku_detail[].sku_pic`，不经过 `saveMaterial`/`batchApplyMaterial` |

## 旧样本离线复核

以下结论来自旧 `tmp_runtime_probe_live` 样本的离线复核，只能作为参考证据，不升级本目录当前 live 接口状态。

| 样本 | 复核产物 | 可证明 | 不能证明 |
| --- | --- | --- | --- |
| `fxg_protocol_submit_only_deep_9222_2026-05-04_09-55-56.json` | `outputs/price_stock_capture_analysis_legacy_20260504.json` | `addWithSchema` 中存在完整 `sku_detail.value[].price`、`stock_info.stock_num`、可用 `spec_detail_ids` | 独立价格库存接口、服务端最小接受字段集、不同类目通用性 |
| `fxg_protocol_submit_only_block_9222_2026-05-04_08-51-48.json` | `outputs/price_stock_capture_analysis_submit_preflight_legacy_20260504.json` | 存在 `addWithSchema` submit-preflight 请求 | 因 `<max-depth>` 截断，不能证明完整 SKU 映射和库存字段 |

## 状态定义

- `待复核`：旧项目或代码里有线索，但本目录还没有重新实证。
- `候选`：已发现请求或模块线索，但不能证明服务端接受。
- `已实证`：有去敏证据、字段来源和结果解释。
- `排除`：确认不是当前目标阶段必经链。
- `阻塞`：接口存在，但关键字段或校验规则缺失。

## 当前阶段接口判断

第一阶段继续锁定价格库存：

- 已确认 `sku_detail` 中 `price` 和 `stock_info` 为必填列。
- 已确认前端模块里存在 `sku_detail.price`、`stock`、`stock_info`、`spec_detail_ids` 字段形状。
- 尚未确认真实请求体里 `stock` 与 `stock_info` 的最终关系。
- 尚未确认 SKU 行 ID、规格值 ID 和页面 SKU 的稳定映射。
