# 第一批只读探针结果

采集时间：2026-05-05

## 环境状态

CDP 发布页环境可用：

- CDP：`http://127.0.0.1:9333/json/list`
- 页面：`https://fxg.jinritemai.com/ffa/g/create`
- 页面状态：非登录页，已出现发布页字段。
- 当前页面可见字段：`主图`、`商品标题`。

说明：本轮未使用用户贴出的 Cookie 原始值，依赖的是本机专用 CDP Chrome 的已登录页面上下文。

## 产物

- `schemas/fxg_schema_long_socks_20260505.json`
- `schemas/fxg_runtime_options_long_socks_20260505.json`
- `schemas/fxg_freight_long_socks_20260505.json`
- `schemas/fxg_submit_probe_20260505.json`
- `schemas/fxg_upload_probe_scan_20260505.json`
- `schemas/fxg_material_probe_20260505.json`
- `schemas/fxg_qualification_probe_20260505.json`

## 已确认的只读接口

### 类目搜索

- 接口：`/product/tproduct/searchCategoryN`
- 状态：`readonly_verified`
- 当前关键词：`长筒袜`
- 命中类目：`服装 > 内衣裤袜 > 袜子 > 长筒袜`
- 叶子类目 ID：`1000010275`

### Schema

- 接口：`/product/tproduct/getSchema`
- 状态：`readonly_verified`
- `modelKeyCount=53`

关键字段：

- `goods_category`
- `category_properties`
- `pic`
- `description`
- `qualification`
- `spec_detail`
- `sku_detail`
- `freight_id`
- `pickup_method`
- `start_sale_type`
- `sale_channel_type`
- `product_type`
- `presell_type`

### 运费模板

- 接口：`/product/tproduct/refetchSchema?action=freight_template_options_load`
- 状态：`readonly_verified`
- 当前选中值：`300713474`
- 当前模板名：`中通包邮`
- 可选模板数：`8`

## 长筒袜类目字段

必填类目属性：

- `1687`：品牌
- `1577`：适用性别
- `1865`：筒高
- `785`：面料材质

规格轴：

- `2752`：颜色分类
- `3939`：码数
- `4706`：筒高长度

SKU 关键列：

- `price`：价格，必填
- `stock_info`：库存，必填
- `sku_id`：非必填
- `step_stock_info`：非必填
- `reserved_stock_info`：非必填

## 提交 envelope 线索

来源：`schemas/fxg_submit_probe_20260505.json`

状态：`source_hint`，不是请求体实证。

确认的提交入口线索：

- `/product/tproduct/addWithSchema?check_status=<check_status>`
- `/product/tproduct/editWithSchema?check_status=<check_status>`

提交 body 合并顺序线索：

1. `{ schema: model }`
2. `{ category_id, context: { ...schema.context, gray_components: undefined } }`
3. `{ pass_through_extra, optional recruit_info }`
4. `submit options object containing check_status`

## 价格库存字段形状线索

状态：`source_hint`，需要截停请求体复核。

`sku_detail[]` 可能包含：

- `id`
- `sku_id`
- `spec_detail_ids`
- `sku_pic`
- `price`
- `stock`
- `self_sell_stock`
- `stock_info`
- `sku_status`
- `origin_price`
- `step_stock_info`
- `reserved_stock_info`

`stock_info` 可能包含：

- `stock_num`
- `stock_inc_num`
- `use_cargo_stock`

## 当前关键结论

协议化流水线第一阶段应继续聚焦价格库存，但不能直接写协议执行器。

原因：

- 只读 schema 已确认价格和库存是 SKU 必填列。
- 前端模块已确认 `sku_detail.price` 与 `sku_detail.stock_info` 字段形状。
- 但还没有当前页面真实 `addWithSchema` 请求体，无法确认 `stock` 与 `stock_info` 的实际关系、SKU ID 生成规则和服务端接受条件。

## 媒体与资质接口线索

状态：`source_hint`，均未触发写请求。

图片上传：

- `/product/img/batchupload`
- 单图字段：`image`
- 批量字段：`image[index]`
- 附加字段：`extra={"request_source":"pc"}`

媒体任务：

- `/product/tproduct/material/imageTextVideo/submitImgOptimizeTask4PC`
- `/product/tproduct/material/imageTextVideo/queryImgOptimizeTask4PC`

素材：

- `/product/tproduct/saveMaterial`
- `/product/tproduct/materialDetail`
- `/product/tproduct/material/batchApplyMaterial`

白底图：

- `/common/img/IsWhiteBackgroundPic`
- `/product/tproduct/img/IntelligentOptimizeVerify`
- `/product/img/trans_img_style`
- `/product/tproduct/submitWhiteImg`
- `/product/tproduct/batchApprovalWhiteImgs`
- `/product/tproduct/CancelProductMaterialPicAudit`

资质：

- `/ffa/grs/qualification/list`
- `/ffa/mshop/qualification/list`
- 提交字段 `qualification` 仍只是 `record<string, unknown>` 级别线索。

注意：以上媒体/资质接口大多是写入或审核相关候选。后续必须用截停模式确认真实请求体和触发条件，不能直接接入流水线。

## 下一步

下一步必须做本地截停，不放行写请求：

1. 让页面填充到足以生成 `addWithSchema`。
2. 启动 `capture:fxg-submit-preflight` 或 `capture:fxg-protocol` 的截停模式。
3. 只截获去敏请求体，优先提取 `schema.model.sku_detail`、`schema.model.spec_detail`、`freight_id`、`start_sale_type`、`presell_type`。
4. 产物写入 `captures/`，并更新接口矩阵。
