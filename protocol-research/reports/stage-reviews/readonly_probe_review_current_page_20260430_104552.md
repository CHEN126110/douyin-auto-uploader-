# 第一轮只读探针复盘

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 阶段名称 | 第一轮只读探针 |
| `run_id` | `run_20260430_104552` |
| 样本 | `current_page` |
| 执行时间 | `2026-04-30 10:45:52` |
| 页面基线 | FXG 发布页，类目为 `服装 > 内衣裤袜 > 袜子 > 长筒袜` |
| 执行类型 | 只读探针 |

## 本轮实际执行内容

- 执行 `check:cdp` 前置环境检查。
- 执行 schema probe。
- 执行 runtime options probe。
- 执行 freight probe。
- 执行 submit probe。
- 执行 qualification probe。
- 执行 material probe。
- 执行 category matrix probe。

## 实际产物

- `captures/environment/env_check_current_page_20260430_104552.json`
- `schemas/live/fxg_schema_probe_current_page_20260430_104552.json`
- `schemas/runtime/fxg_runtime_options_current_page_20260430_104552.json`
- `schemas/freight/fxg_freight_probe_current_page_20260430_104552.json`
- `schemas/submit/fxg_submit_probe_current_page_20260430_104552.json`
- `captures/qualification/fxg_qualification_probe_current_page_20260430_104552.json`
- `captures/material/fxg_material_probe_current_page_20260430_104552.json`
- `schemas/category-matrix/fxg_category_matrix_socks_20260430_104552.json`

## 已确认事实

- 当前 live 页面确实是 FXG 发布页，且可被 CDP 命中。
- 当前样本类目为 `长筒袜`，叶子类目 ID 为 `1000010275`。
- 当前 live schema 中，`title/goods_category/category_properties/pic/description/freight_id/spec_detail/sku_detail` 都是必填字段。
- 当前 runtime options 已确认：
  - `pickup_method` 为必填，且当前只有 `使用物流配送`
  - `start_sale_type` 为必填，当前有 `上架/下架`
  - `product_type` 为必填，当前有 `普通商品/虚拟商品`
  - `presell_type` 为必填，当前至少有 `现货/现货预售混合`
- 当前 freight probe 已确认：
  - live runtime 里能读到 8 个运费模板选项
  - 当前预填值为 `300713474`
  - schema 中存在 `refetchSchema?action=freight_template_options_load`
- 当前 submit probe 已确认：
  - `white_background_pic` 形状为 `array<{ url: string }>`
  - `main_pic_video` 形状为 `array<{ resource_id: string, ... }>`
  - `qualification` 形状为 `record<string, unknown>`
  - `spec_detail` / `sku_detail` / `spec_detail_ids` / `sku_pic` / `stock_info` 都存在明确 frontend submit schema 线索
  - `addWithSchema/editWithSchema` 的前端装配方式已被模块级证据命中
- 当前 material probe 已确认：
  - `/product/img/batchupload`
  - `/product/tproduct/saveMaterial`
  - `/product/tproduct/materialDetail`
  - `/product/tproduct/material/batchApplyMaterial`
  - `/product/tproduct/submitWhiteImg`
  - `/product/tproduct/batchApprovalWhiteImgs`
  - `/product/img/trans_img_style`
- 当前 category matrix 已确认：
  - `长筒袜/中筒袜/短袜/船袜` 的必填属性存在真实差异
  - 规格轴数量和名称也存在类目差异
  - SKU 列 key 集合在这四个袜子类目内基本一致

## 未确认事项

- 还没有真实 `addWithSchema` 被阻断后的请求体。
- `description` 目前只确认是字符串字段，仍未确认提交接受的最终序列化格式。
- `stock_info` 只确认到 frontend submit schema 形状，仍未确认它与 `stock` 的真实提交约束关系。
- `qualification` 只确认到 `record<string, unknown>`，真实子键和值仍未拿到。
- `submitWhiteImg.action_list` 的具体取值仍未拿到。
- 还没有任何媒体上传、资质提交、最终提交的真实写请求体证据。

## 字段影响

| 字段 | 变化前状态 | 变化后状态 | 依据 |
| --- | --- | --- | --- |
| `title` | 候选推断 | 已知形状 | schema probe + submit/live schema |
| `description` | 候选推断 | 已知形状 | schema probe + submit probe |
| `freight_id` | 已实证 | 已实证 | freight probe |
| `sale_channel_type` | 已知形状 | 已知形状且确认 runtime 必填 | runtime probe + submit probe |
| `spec_detail` | 已知形状 | 已知形状且确认 live 类目存在 3 个规格轴 | runtime probe + submit probe |
| `sku_detail` | 已知形状 | 已知形状且确认 live SKU 列为 22 列 | schema/runtime/submit probe |
| `qualification` | 已知形状 | 已知形状且确认页面区块与模块入口 | qualification probe |
| `main_pic_video` | 已知形状 | 已知形状且确认素材链候选入口 | material probe + submit probe |
| `white_background_pic` | 已知形状 | 已知形状且确认白底图审核候选链 | material probe + submit probe |

## 当前 blocker

- `addWithSchema` 阻断请求体仍未拿到。
- `stock_info` 真实提交约束仍未拿到。
- `qualification` 真实子键和值仍未拿到。
- `submitWhiteImg.action_list` 仍未拿到。
- `saveMaterial/materialDetail/batchApplyMaterial` 仍缺真实写请求体证据。

## 下一步建议

- 第二轮优先进入本地截停研究，优先级如下：
  - `addWithSchema/editWithSchema`
  - `price/stock/stock_info/spec_detail_ids`
  - `saveMaterial/materialDetail/batchApplyMaterial`
  - `submitWhiteImg/batchApprovalWhiteImgs`
  - `qualification`
