# 字段证据矩阵

本文用于收口协议研究过程中的字段证据状态，避免把“候选结构”误写成“已闭环能力”。

证据等级约定：

- `已实证`：已经有真实请求体、真实响应体或 live schema 直接证据。
- `已知形状`：已通过前端模块、schema 探针或运行态探针确认字段形状，但还没有真实提交样例。
- `候选推断`：字段存在较强线索，但来源、最终形状或提交规则还未闭环。
- `阻塞缺口`：当前直接影响协议提交实现的关键缺证字段。

阻塞标记约定：

- `是`：当前字段缺证会阻塞协议正式提交研究收口。
- `否`：当前字段仍需研究，但暂不阻塞整体主链。

## 字段总表

| 字段 | DOM 阶段 | 主要用途 | 候选接口/来源 | 当前证据等级 | 阻塞 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `goods_category.category_leaf_id` | 选类目 | 确认叶子类目 | `searchCategoryN` + `getSchema` | 已实证 | 否 | 类目搜索与 schema 已能确认叶子类目 |
| `category_properties.*` | 填类目属性 | 品牌、性别、材质、筒高等 | `getSchema` + runtime options | 已知形状 | 是 | `run_20260430_104552` 已拿到长筒袜 live 属性与选项；多类目差异也已部分确认，但不能推广成所有类目固定字段 |
| `title` | 填标题 | 商品标题 | live schema + submit schema | 已知形状 | 否 | `run_20260430_104552` 已确认 `title` 在 live schema 中必填且为字符串字段 |
| `short_product_name` | 选类目后短标题 | 短标题 | DOM 运行态模块 | 候选推断 | 否 | 需确认是否进入最终提交体及字段名 |
| `pic` | 上传 1:1 主图 | 主图列表 | `batchupload` + live schema + 最终提交体 | 已知形状 | 是 | `run_20260430_104552` 已确认 `pic` 为 live 必填；`20260430_142845` 单样本上传探针已实证 `/product/img/batchupload` 返回图片 URL 字符串；`20260430_145745` 进一步确认即使换成 `600x600+` 的真实主图，直接向当前隐藏 `file input` 注入文件也不会进入页面表单状态 |
| `main_image_three_to_four` | 上传媒体资产 | 3:4 主图 | 智能裁剪任务接口 + 最终提交体 | 已知形状 | 否 | `20260430_160018` 已实证 `POST /product/tproduct/material/imageTextVideo/submitImgOptimizeTask4PC` 和 `GET /product/tproduct/material/imageTextVideo/queryImgOptimizeTask4PC`；已确认 1:1 主图会进入 `34智能裁剪` 任务链，但仍缺最终结果字段和提交映射 |
| `white_background_pic` | 上传媒体资产 | 白底图 | `submitWhiteImg` + 最终提交体 | 已知形状 | 是 | 字段形状已知，`action_list` 和审核闭环仍缺证 |
| `main_pic_video` | 上传媒体资产 | 主图视频 | `saveMaterial/materialDetail` 候选 | 已知形状 | 是 | 已知数组结构，仍缺资源上传到最终字段的闭环证据 |
| `description` | 上传媒体资产 | 商品详情 | live schema + submit schema | 已知形状 | 是 | `run_20260430_104552` 已确认 `description` 为必填字符串字段，但最终接受的序列化格式仍未实证 |
| `qualification` | 类目属性/媒体/提交 | 资质信息 | qualification probe + submit schema | 已知形状 | 是 | `run_20260430_104552` 已确认页面资质区块与 `record<string, unknown>` 形状；真实子键和值结构仍未拿到 |
| `spec_detail` | SKU 配置 | 规格轴与规格值 | submit probe + AI 识图异步 schema | 已知形状 | 是 | `20260430_continued` 已实证 `asyncRefetchSchema?action=ai_gen_spec_refresh` / `getAsyncRefetchSchema`；当前类目 AI 识图返回 `spec_items` 显示 `颜色分类(cp_id=2752)`、`码数(cp_id=3939)` 为必填，`筒高长度(cp_id=4706)`、`规格(cp_id=93)` 为非必填，但仍缺最终提交样例 |
| `spec_detail[].spec_values[]` | SKU 配置 | 规格值定义 | submit probe + AI 识图异步 schema | 已知形状 | 是 | `20260430_continued` 已拿到 `predict_spec_from_pics` 的真实候选值：`码数=均码`、`筒高长度=中筒袜`，并带出 `cpv_id/cpv_path`；但必填 `颜色分类` 仍无预测值，SKU 组合尚未生成 |
| `sku_detail` | SKU 配置/价格库存 | SKU 组合明细 | submit probe + 最终提交体 | 已知形状 | 是 | 缺真实 `id/sku_id/spec_detail_ids` 样例 |
| `sku_detail[].sku_pic` | SKU 配置 | SKU 图片绑定 | 页面运行态 + 最终提交体 | 候选推断 | 否 | 需补规格图绑定到具体 SKU 的证据 |
| `sku_detail[].price` | 价格库存 | SKU 价格 | 最终提交体 | 已知形状 | 是 | 已知为字符串，仍缺真实请求体样例 |
| `sku_detail[].stock` | 价格库存 | SKU 库存 | 最终提交体 | 已知形状 | 是 | 是否与 `stock_info` 同时出现仍未实证 |
| `sku_detail[].stock_info` | 价格库存 | 库存扩展结构 | 最终提交体 | 已知形状 | 是 | 当前是协议研究最大缺口之一 |
| `freight_id` | 价格库存/控制项 | 运费模板 | `refetchSchema?action=freight_template_options_load` | 已实证 | 否 | 运行时选项已能读到真实模板 ID |
| `sale_channel_type` | 价格库存/控制项 | 销售渠道 | runtime options + submit schema | 已知形状 | 是 | `run_20260430_104552` 已确认其为 runtime 必填控制项，但当前页面没有可用选项和值样例 |
| `enable_all_channel_product_online` | 价格库存/控制项 | 上架/渠道控制 | live schema + 最终提交体 | 已知形状 | 否 | 已确认是布尔字段，仍缺真实提交例子 |
| `pickup_method` | 提交控制 | 发货方式 | live schema / dry-run | 已实证 | 否 | 当前已可从 schema 初始值读出 |
| `start_sale_type` | 提交控制 | 起售类型 | live schema / dry-run | 已实证 | 否 | 当前已可从 schema 初始值读出 |
| `product_type` | 提交控制 | 商品类型 | live schema / dry-run | 已实证 | 否 | 当前已可从 schema 初始值读出 |
| `presell_type` | 提交控制 | 预售类型 | live schema / dry-run | 已实证 | 否 | 当前已可从 schema 初始值读出 |
| `addWithSchema envelope` | 发布商品 | 最终提交通道 | `addWithSchema` / `editWithSchema` | 阻塞缺口 | 是 | 当前最高优先级，未闭环前不能谈协议正式提交 |

## 按阶段聚合

### 1. 页面初始化与类目阶段

| 字段/对象 | 当前状态 | 说明 |
| --- | --- | --- |
| 页面 bootstrap 请求 | 候选推断 | 需要进一步整理初始化请求清单 |
| `category_leaf_id` | 已实证 | 已可通过类目搜索与 schema 读到 |
| 类目属性 schema | 已知形状 | 需继续扩大多类目样本验证 |

### 2. 属性阶段

| 字段/对象 | 当前状态 | 说明 |
| --- | --- | --- |
| `category_properties` | 已知形状 | 已能解释部分核心字段来源 |
| `qualification` | 已知形状 | 真实子项结构仍缺证 |
| 水洗标/吊牌图相关字段 | 候选推断 | 页面入口明确，但与最终提交字段关系未闭环 |

### 3. 媒体阶段

| 字段/对象 | 当前状态 | 说明 |
| --- | --- | --- |
| `pic` | 已知形状 | 已有真实上传回包形状，但仍缺页面绑定与最终接受性证据 |
| `main_image_three_to_four` | 已知形状 | 已补到智能裁剪任务接口证据，仍缺任务响应结果到最终字段的映射证据 |
| `white_background_pic` | 已知形状 | 白底图审核链仍未闭环 |
| `main_pic_video` | 已知形状 | 缺素材接口回包与最终字段关系 |
| `description` | 候选推断 | 最终序列化形式是关键缺口 |

### 4. SKU 与价格库存阶段

| 字段/对象 | 当前状态 | 说明 |
| --- | --- | --- |
| `spec_detail` | 已知形状 | 已补到 AI 识图返回的必填规格项与候选值，仍缺完整回填后的提交样例 |
| `sku_detail` | 已知形状 | 缺真实组合 ID 样例 |
| `price` | 已知形状 | 缺真实请求体 |
| `stock` | 已知形状 | 与 `stock_info` 关系未定 |
| `stock_info` | 阻塞缺口 | 当前关键阻塞项 |

### 5. 提交控制与最终提交阶段

| 字段/对象 | 当前状态 | 说明 |
| --- | --- | --- |
| `freight_id` | 已实证 | 已能读取真实模板选项 |
| `sale_channel_type` | 已知形状 | 没有 live 样例 |
| `enable_all_channel_product_online` | 已知形状 | 仍缺真实提交例子 |
| `addWithSchema envelope` | 阻塞缺口 | 最终总装配口，优先级最高 |

## 当前研究出口

当前字段矩阵说明：

- `run_20260430_104552` 已经产出第一轮 live 只读 probe 证据，当前页面样本为 `长筒袜`。
- 已经能支撑“只读探针 + dry-run 审计”的字段并不少。
- 真正阻塞协议正式提交的，仍然集中在四类：
  - 最终提交 envelope
  - SKU 真实组合与价格库存
  - 媒体回包到最终字段映射
  - `qualification` 真实结构

## 最新实证批次

- `run_20260430_104552`
- 主要产物：
  - `captures/environment/env_check_current_page_20260430_104552.json`
  - `schemas/live/fxg_schema_probe_current_page_20260430_104552.json`
  - `schemas/runtime/fxg_runtime_options_current_page_20260430_104552.json`
  - `schemas/freight/fxg_freight_probe_current_page_20260430_104552.json`
  - `schemas/submit/fxg_submit_probe_current_page_20260430_104552.json`
  - `captures/qualification/fxg_qualification_probe_current_page_20260430_104552.json`
  - `captures/material/fxg_material_probe_current_page_20260430_104552.json`
  - `schemas/category-matrix/fxg_category_matrix_socks_20260430_104552.json`
- 这批产物已经把以下内容从“待验证”推进到“已有 live 只读证据”：
  - 当前类目叶子 ID 与类目路径
  - 当前类目 live schema 必填字段集合
  - `freight_id` 的真实运行时选项
  - `pickup_method/start_sale_type/product_type/presell_type` 的 live 控制项
  - `white_background_pic/main_pic_video/qualification/spec_detail/sku_detail/stock_info` 的 frontend submit schema 形状
  - 多袜子类目之间的属性与规格轴差异

## 更新规则

后续每补到一条新证据，都按下面规则更新：

1. 先更新字段行的证据等级。
2. 再更新是否 blocker。
3. 最后补“证据来源”和“仍缺什么”，避免只改结论不改依据。
