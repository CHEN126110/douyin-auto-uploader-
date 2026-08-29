# 第一轮只读探针执行清单

本文用于指导协议自动化研究的第一轮只读探针工作。

目标不是直接拿到正式提交能力，而是先把当前 DOM 上传流水线背后的页面运行态、schema、类目、运费、媒体、资质和提交字段形状证据补齐。

执行原则：

- 第一轮优先做只读探针；如果只读证据已经不足以继续推进，可直接切到最小必要的 live 写验证，不把“只读”当作硬限制。
- 不修改当前正式 DOM 上传主线。
- 不把“模块线索”当成“真实请求体证据”。
- 每完成一项，都要回写字段证据矩阵。

## 执行顺序

| 顺序 | 目标 | 目的 | 输出 |
| --- | --- | --- | --- |
| 1 | CDP 环境检查 | 确认已登录、页面可见、不是登录页/风控页 | 环境检查 JSON |
| 2 | 页面 schema 探针 | 确认类目、叶子类目、字段总量、基础 schema | schema JSON |
| 3 | 运行时选项探针 | 确认属性、规格轴、SKU 列、发布控制、运费 | runtime options JSON |
| 4 | 运费探针 | 单独确认运费模板和 freight 相关字段 | freight JSON |
| 5 | 提交字段形状探针 | 确认 submit schema 中媒体、SKU、控制字段形状 | submit probe JSON |
| 6 | 资质探针 | 确认 qualification 相关 DOM 区块与模块线索 | qualification JSON |
| 7 | 素材探针 | 确认 saveMaterial、白底图、视频素材候选链路 | material JSON |
| 8 | 多类目矩阵探针 | 验证不同类目下的属性/规格/资质差异 | category matrix JSON |
| 9 | 只读结论回写 | 回写字段证据矩阵和阶段报告 | 更新文档 |

## 清单明细

### 1. CDP 环境检查

- 目标：
  - 确认专用调试浏览器已启动。
  - 确认当前打开的是已登录的 FXG 发布页。
  - 排除登录页、验证码页、风控页。
- 建议工具：
  - `cdp_environment_check`
- 预期证据：
  - 当前 URL
  - 页面标题
  - 页面文本摘要
  - 关键字段是否可见，例如 `主图`、`商品标题`、`下一步`
- 输出路径建议：
  - `protocol-research/captures/environment/`
- 完成标准：
  - 明确当前环境可继续运行只读探针。

### 2. 页面 schema 探针

- 目标：
  - 确认当前类目、叶子类目 ID、schema 字段总量。
  - 固化页面当前的基础字段平面。
- 建议工具：
  - `cdp_fxg_schema_probe`
- 预期证据：
  - 当前类目名称
  - `category_leaf_id`
  - `modelKeyCount`
  - 当前类目下的主要字段分布
- 输出路径建议：
  - `protocol-research/schemas/live/`
- 对应字段：
  - `goods_category.category_leaf_id`
  - `category_properties.*`
- 完成标准：
  - 当前页面 schema 可作为后续所有阶段研究的基线。

### 3. 运行时选项探针

- 目标：
  - 读取真实类目属性、规格轴、SKU 列、发布控制字段、运费模板选项。
- 建议工具：
  - `cdp_fxg_runtime_options_probe`
- 预期证据：
  - 必填属性
  - 属性候选值
  - `spec_detail` 相关规格轴
  - SKU 表列定义
  - 发布控制字段
  - 运费模板选项
- 输出路径建议：
  - `protocol-research/schemas/runtime/`
- 对应字段：
  - `category_properties.*`
  - `spec_detail`
  - `freight_id`
  - `sale_channel_type`
  - `enable_all_channel_product_online`
- 完成标准：
  - 形成一份“当前类目的运行时能力快照”。

### 4. 运费探针

- 目标：
  - 单独确认运费模板相关字段和选项来源。
- 建议工具：
  - `cdp_fxg_freight_probe`
- 预期证据：
  - 运费模板列表
  - 模板名称与模板 ID 对应关系
  - freight 相关字段形状
- 输出路径建议：
  - `protocol-research/schemas/freight/`
- 对应字段：
  - `freight_id`
- 完成标准：
  - 证明运费模板不是 DOM 文案猜测，而是有真实运行时选项来源。

### 5. 提交字段形状探针

- 目标：
  - 在不真实提交的情况下，确认提交 schema 中的核心字段形状。
- 建议工具：
  - `cdp_fxg_submit_probe`
- 预期证据：
  - `pic`
  - `main_image_three_to_four`
  - `white_background_pic`
  - `main_pic_video`
  - `qualification`
  - `spec_detail`
  - `sku_detail`
  - `stock_info`
  - `sale_channel_type`
- 输出路径建议：
  - `protocol-research/schemas/submit/`
- 对应字段：
  - 媒体字段
  - 资质字段
  - SKU 与价库字段
  - 提交控制字段
- 完成标准：
  - 字段矩阵里所有“已知形状”字段，都有对应探针产物可追溯。

### 6. 资质探针

- 目标：
  - 区分页面资质区块、类目属性 OCR 辅助区块和最终 `qualification` 字段线索。
- 建议工具：
  - `cdp_fxg_qualification_probe`
- 预期证据：
  - 资质相关 DOM 区块
  - `qualification` 组件线索
  - 资质子项命名线索
- 输出路径建议：
  - `protocol-research/captures/qualification/`
- 对应字段：
  - `qualification`
- 完成标准：
  - 明确哪些只是页面可见项，哪些才可能进入 `qualification`。

### 7. 素材探针

- 目标：
  - 确认视频素材、白底图、素材服务、详情图相关候选链路。
- 建议工具：
  - `cdp_fxg_material_probe`
- 预期证据：
  - `saveMaterial`
  - `materialDetail`
  - `batchApplyMaterial`
  - 白底图候选接口线索
  - 素材类型与模块线索
- 输出路径建议：
  - `protocol-research/captures/material/`
- 对应字段：
  - `main_pic_video`
  - `white_background_pic`
  - `description`
- 完成标准：
  - 形成素材链路候选图，不把视频、白底图、详情图混成同一条模糊路径。

### 8. 多类目矩阵探针

- 目标：
  - 验证不同类目下的属性、规格轴、资质、SKU 列差异。
- 建议工具：
  - `cdp_fxg_category_matrix_probe`
- 预期证据：
  - 类目对比矩阵
  - 必填属性差异
  - 规格轴差异
  - 资质入口差异
- 输出路径建议：
  - `protocol-research/reports/category-matrix/`
- 对应字段：
  - `category_properties.*`
  - `spec_detail`
  - `qualification`
- 完成标准：
  - 明确哪些字段计划可复用，哪些必须严格依赖 live schema 动态生成。

### 9. 只读结论回写

- 目标：
  - 把第一轮探针结论沉淀回文档，避免证据与结论分离。
- 需要更新的文档：
  - `docs/field_evidence_matrix.md`
  - `docs/dom_upload_pipeline_map.md`
- 回写要求：
  - 每补到一条证据，更新字段等级。
  - 每补到一个新阻塞项，补充到阻塞清单。
  - 每发现类目差异，补充到地图或矩阵文档。
- 完成标准：
  - 文档状态与证据产物一致，不出现“文档说已完成，但证据不存在”的情况。

## 第一轮输出目录建议

```text
protocol-research/
  captures/
    environment/
    qualification/
    material/
  schemas/
    live/
    runtime/
    freight/
    submit/
  reports/
    category-matrix/
```

## 第一轮完成定义

第一轮只读探针完成，不等于协议闭环完成。

第一轮的完成标准只有下面三条：

1. 当前页面类目、schema、运行时选项、运费、资质、素材、提交字段形状都有对应产物。
2. 字段证据矩阵已回写，能区分已实证、已知形状、候选推断、阻塞缺口。
3. 已经能明确指出第二轮应该优先截停哪些写接口，而不是继续盲目搜索。

## 第二轮入口条件

只有当第一轮完成后，第二轮才进入本地截停研究，优先级顺序如下：

1. `addWithSchema` / `editWithSchema`
2. `spec_detail` / `sku_detail` / `price` / `stock` / `stock_info`
3. `batchupload` / `saveMaterial` / `submitWhiteImg`
4. `qualification`

补充说明：

- 如果某条链在第一轮中已经通过真实页面状态证明“继续只读没有新增价值”，允许提前切到真实写验证或真实提交验证。
- 但无论推进速度多快，文档里仍要区分“已实证”“临时策略”“仍缺证字段”。
