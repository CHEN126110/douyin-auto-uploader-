# DOM 上传流水线接口地图

本文用于把当前正式 DOM 上传流水线拆成可研究的协议阶段地图。

研究原则：

- 先以 DOM 实际行为为准，不按猜测补接口。
- 先确认页面运行态和 schema 证据，再补写接口证据。
- 研究阶段不改主项目正式上传逻辑。

## 正式入口

- 前端调用：`tauri-app/src/services/api.ts` -> `startUpload()`
- 后端入口：`tauri-app/python-sidecar/app.py` -> `upload_start()`
- 正式执行：`tauri-app/python-sidecar/app.py` -> `_run_upload_task()` -> `_execute_upload_flow()`

## 阶段总览

| 阶段 | DOM 动作 | 主要代码 | 研究重点 | 研究方式 | 当前结论 |
| --- | --- | --- | --- | --- | --- |
| 1 | 打开发布页 | `app.py::_open_publish_page` | 页面初始化、bootstrap、草稿恢复 | 只读探针 | `run_20260430_104552` 已确认当前可命中 live FXG 发布页 |
| 2 | 填写标题 | `app.py::_fill_title_for_record` | 标题字段是否仅保存在本地状态 | 只读探针 | `run_20260430_104552` 已确认 `title` 为 live 必填字符串字段 |
| 3 | 上传 1:1 主图 | `app.py::_upload_main_images` | 图片上传接口与回包映射 | 只读观察 + 本地截停 | `run_20260430_104552` 已确认 `/product/img/batchupload` 与 `request_source=pc` 组件线索；`20260430_142845` 已实证单样本上传回包，但通用隐藏 `file input` 注入仍不能推进页面状态；`20260430_155503` 之后已实证通过 AI 素材工具上传可让主图真正落入页面表单 |
| 4 | 选类目 | `app.py::_select_category_and_prepare_attributes` | 类目搜索、叶子类目确认、schema 刷新 | 只读探针 | `run_20260430_104552` 已确认当前样本类目为 `长筒袜`，叶子类目 ID 为 `1000010275` |
| 5 | 填类目属性 | `app.py::_fill_category_attributes` | 品牌、性别、筒高、材质、OCR 辅助 | 只读探针 | `run_20260430_104552` 已确认长筒袜 live 属性；category matrix 已证明类目差异真实存在 |
| 6 | 上传媒体资产 | `app.py::_upload_media_assets` | 3:4 图、视频、白底图、详情图、素材链 | 只读观察 + 本地截停 | `run_20260430_104552` 已确认 `saveMaterial/materialDetail/submitWhiteImg/batchApprovalWhiteImgs/trans_img_style` 候选链 |
| 7 | 配置 SKU 入口 | `app.py::_configure_sku_entries` | 规格轴、规格值、规格图绑定 | 只读探针 + 提交前截停 | `run_20260430_104552` 已确认规格相关 schema；`20260430_continued` 已实证 `智能识图填写规格 -> AI识图填写规格` 抽屉入口、图片上传复用 `/product/img/batchupload`、以及 `ai_gen_spec_refresh` 异步识图链，但当前样本仍缺必填 `颜色分类` 结果 |
| 8 | 配置 SKU 结构 | `app.py::_configure_sku_structure` | 规格组合生成规则 | 只读探针 + 最终提交截停 | `run_20260430_104552` 已确认 `spec_detail_ids/sku_pic/stock_info` frontend submit schema 形状，仍缺真实样例 |
| 9 | 填价格库存与控制项 | `app.py::_fill_price_stock_and_delivery` | `price/stock/stock_info/freight_id/sale_channel_type` | 只读探针 + 提交前截停 | `run_20260430_104552` 已确认 `freight_id` 真实模板选项和控制项字段形状，仍缺真实写请求约束 |
| 10 | 发布商品 | `app.py::_submit_publish` | `addWithSchema/editWithSchema` 最终 envelope | 本地截停 | `run_20260430_104552` 已确认前端提交装配入口，但最终阻断请求体仍未拿到 |

## 分阶段拆解

### 1. 打开发布页

- DOM 行为：
  - 进入发布页。
  - 如果页面停留在第二步则退回第一步。
  - 清理干扰弹层。
  - 必要时处理“重新发布”。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_open_publish_page`
- 研究问题：
  - 页面初始化会触发哪些只读请求。
  - 是否存在草稿恢复、发布页上下文装载、运行时模块初始化。
  - 哪些请求是所有类目共有，哪些请求随类目变化。
- 建议证据：
  - 页面初始化请求清单。
  - 页面模块摘要。
  - 初始 schema 读取线索。
- 完成标准：
  - 能说明“进入发布页后发生了什么初始化行为”，并区分只读初始化与后续提交相关模块。

### 2. 填写标题

- DOM 行为：
  - 找到标题输入框，写入标题，并做 value 校验。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_fill_title_for_record`
- 研究问题：
  - 标题是否只是前端 state。
  - 是否存在实时校验请求或模块级格式校验。
  - 最终提交体中的标题字段名是什么。
- 建议证据：
  - 标题字段在提交 schema 或最终提交体中的位置。
  - 相关运行态模块摘要。
- 完成标准：
  - 明确标题字段不是凭页面文案猜测，而是能落到真实字段名。

### 3. 上传 1:1 主图

- DOM 行为：
  - 上传主图。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_upload_main_images`
- 研究问题：
  - 主图是否统一走图片上传接口。
  - 上传接口返回 URL、素材 ID 还是两者都有。
  - 最终 `pic` 字段如何构造。
- 已知候选：
  - `/product/img/batchupload`
- 建议证据：
  - 上传请求摘要。
  - 上传响应摘要。
  - 响应字段与最终 `pic` 的映射关系。
- 完成标准：
  - 解释“主图上传成功后，为什么最终提交体里能生成 `pic`”。

### 4. 选类目

- DOM 行为：
  - 智能选类目。
  - 点击生成短标题。
  - 检查是否存在“水洗标/吊牌图”字段。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_select_category_and_prepare_attributes`
- 研究问题：
  - 类目搜索请求如何定位叶子类目。
  - 类目确认后如何刷新页面 schema。
  - 不同类目下字段差异如何体现。
- 已知候选：
  - `/product/tproduct/searchCategoryN`
  - `/product/tproduct/getSchema`
- 建议证据：
  - 类目搜索请求与返回结构。
  - 叶子类目确认后的 schema 摘要。
  - 多类目差异矩阵。
- 完成标准：
  - 形成“类目 -> schema -> 必填字段/规格轴/资质入口”的稳定映射。

### 5. 填类目属性

- DOM 行为：
  - 填品牌、适用人群、适用性别、筒高、材质。
  - 处理水洗标/吊牌图 OCR 识别失败后的回填逻辑。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_fill_category_attributes`
- 研究问题：
  - 属性字段的真实字段 ID、候选值来源和必填规则。
  - “水洗标/吊牌图”与 `qualification` 是否属于同一路径。
  - OCR 识别后是否会影响提交模型字段。
- 建议证据：
  - 类目属性字段矩阵。
  - 水洗标/吊牌图相关页面运行态线索。
  - `qualification` 与类目属性的边界说明。
- 完成标准：
  - 每个 DOM 属性都能落到真实 schema 字段或明确标成未证实。

### 6. 上传媒体资产

- DOM 行为：
  - 上传 3:4 主图。
  - 上传主图视频或触发一键生成。
  - 上传白底图并处理 AI 后置流程。
  - 上传详情图。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_upload_media_assets`
- 研究问题：
  - 3:4 图、视频、白底图、详情图是否共用同一资源链。
  - `saveMaterial/materialDetail/batchApplyMaterial` 在哪里介入。
  - `submitWhiteImg` 与白底图审核链如何关联。
  - `description` 到底是 HTML、JSON 字符串还是编辑器序列化结果。
- 已知候选：
  - `/product/img/batchupload`
  - `/product/tproduct/saveMaterial`
  - `/product/tproduct/materialDetail`
  - `/product/tproduct/material/batchApplyMaterial`
  - `/product/tproduct/submitWhiteImg`
- 建议证据：
  - 媒体接口调用顺序。
  - 各接口返回值与最终字段 `main_image_three_to_four/white_background_pic/main_pic_video/description` 的关系。
- 完成标准：
  - 解释每一种媒体字段最终是如何进入提交体的。

### 7. 配置 SKU 入口

- DOM 行为：
  - 选择发货时效。
  - 开启规格图。
  - 删除旧的颜色规格值。
  - 逐条写入 SKU 信息。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_configure_sku_entries`
- 研究问题：
  - 规格轴与规格值来自 schema 还是页面生成。
  - 规格图如何绑定到具体规格值。
  - 页面上的颜色规格删除与重建，最终在提交体里如何表示。
- 本轮新增实证：
  - `智能识图填写规格` 的真实入口不是普通按钮，而是先打开右侧 `AI识图填写规格` 抽屉。
  - 抽屉图片上传阶段会复用 `/product/img/batchupload`。
  - 点击 `开始识别` 后，页面会走 `POST /product/tproduct/asyncRefetchSchema?action=ai_gen_spec_refresh`，再轮询 `POST /product/tproduct/getAsyncRefetchSchema?action=ai_gen_spec_refresh&task_id=...`。
  - 成功响应已返回 `predict_spec_from_pics`，当前样本识别出：
    - `码数=均码`
    - `筒高长度=中筒袜`
  - 但响应同时表明 `颜色分类` 仍是必填规格项，本轮没有识别结果，因此抽屉 `确认填写` 未解锁。
- 建议证据：
  - 规格轴定义。
  - 规格值定义。
  - SKU 图与规格值绑定证据。
- 完成标准：
  - 能说明 `spec_detail` 里每个规格轴与规格值的来源。

### 8. 配置 SKU 结构

- DOM 行为：
  - 选择“均码”等规格选项，确保价格库存表生成。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_configure_sku_structure`
- 研究问题：
  - SKU 组合是页面本地展开还是接口返回组合。
  - `spec_detail_ids` 的真实形式是什么。
  - `sku_id/id` 是否由页面临时生成。
- 建议证据：
  - 提交前页面运行态。
  - 最终提交截停样例。
- 完成标准：
  - 至少拿到一组真实 `spec_detail_ids` 和 `sku_detail` 样例。

### 9. 填价格库存与控制项

- DOM 行为：
  - 在价格库存表内逐行写价格和库存。
  - 设置运费模板。
  - 选择上架。
  - 处理达人带货开关和佣金率。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_fill_price_stock_and_delivery`
- 研究问题：
  - `price/stock/stock_info` 的真实提交字段形态。
  - 运费模板 `freight_id` 从哪里进入最终提交体。
  - `sale_channel_type`、`enable_all_channel_product_online` 是否只出现在最终提交体。
- 已知候选：
  - `/product/tproduct/refetchSchema?action=freight_template_options_load`
- 建议证据：
  - 价格库存样例。
  - 运费模板运行时选项。
  - 销售控制字段在 live schema 中的形状。
- 完成标准：
  - 明确价格库存和控制字段的真实结构，避免继续猜测。

### 10. 发布商品

- DOM 行为：
  - 点击“发布商品”。
  - 处理“发布提醒”弹窗。
- 代码位置：
  - `tauri-app/python-sidecar/app.py::_submit_publish`
- 研究问题：
  - 最终提交是 `addWithSchema` 还是 `editWithSchema`。
  - 完整 envelope 长什么样。
  - 哪些字段会在最终提交前被统一装配。
- 已知候选：
  - `/product/tproduct/addWithSchema`
  - `/product/tproduct/editWithSchema`
- 建议证据：
  - 本地截停后的最终请求摘要。
  - `submit-preflight` 分析报告。
  - 和 dry-run 的字段对照表。
- 完成标准：
  - 拿到可审计的最终提交证据包。

## 研究优先级

### P0

- `addWithSchema` / `editWithSchema`
- `spec_detail` / `sku_detail`
- `price` / `stock` / `stock_info`

### P1

- `batchupload`
- `saveMaterial`
- `materialDetail`
- `submitWhiteImg`
- `qualification`

### P2

- 多类目差异矩阵
- 字段稳定性验证
- 字段证据矩阵整理

## 完成定义

一个接口或一个字段链路只有满足下面四条，才能从“候选”升级为“已研究”：

1. 已确认触发场景。
2. 已确认真实请求体、真实响应体或真实 schema 形状。
3. 已确认与 DOM 阶段的对应关系。
4. 已确认当前是否仍为 blocker。

## 当前阻塞项

- `addWithSchema` 最终提交 envelope
- `spec_detail/sku_detail` 真实样例
- `price/stock/stock_info` 真实样例
- 白底图、视频、素材与最终提交字段的映射关系
- `qualification` 真实子键和值结构

## 第一轮只读进展

- `run_20260430_104552` 已完成第一轮 live 只读 probe：
  - 环境检查
  - schema probe
  - runtime options probe
  - freight probe
  - submit probe
  - qualification probe
  - material probe
  - category matrix probe
- 当前阶段已经不是“完全靠候选接口猜测”，而是：
  - 已有 live schema 证据
  - 已有 runtime options 证据
  - 已有 frontend submit schema 证据
  - 已有多类目差异证据
- 下一阶段应切换到“本地截停写接口”而不是继续重复只读搜索。
