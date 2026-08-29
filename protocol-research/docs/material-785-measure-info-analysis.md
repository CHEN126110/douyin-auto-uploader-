# 面料材质 785 / measure_info 协议结构分析

## 时间
2026-05-02

## 核心发现

### 1. Schema 层级的关键结构（来自 webpack bundle module 90665）

**单条 property item 的 UI schema（M 层，React 内部状态）：**
```js
M = y.Ikc({
  id: y.YjP(),
  name: y.YjP().optional(),
  cpv_id: y.aig().optional(),
  remark: y.YjP().optional(),
  disabled: y.zMY().optional(),
  disabled_tips: y.YjP().optional(),
  disabled_additions: y.g1P(y.YjP(), y.bzn()).optional(),
  disabled_edit: y.zMY().optional(),
  disabled_edit_tips: y.YjP().optional(),
  disabled_edit_additions: y.g1P(y.YjP(), y.bzn()).optional(),
  disabled_del: y.zMY().optional(),
  disabled_del_tips: y.YjP().optional(),
  disabled_del_additions: y.g1P(y.YjP(), y.bzn()).optional(),
  disabled_img: y.zMY().optional(),
  disabled_img_tips: y.YjP().optional(),
  disabled_img_additions: y.g1P(y.YjP(), y.bzn()).optional(),
  invalid: y.zMY().optional(),
  cpv_path: y.YOg(y.Ikc({ cp_id: y.aig().optional(), cpv_id: y.aig() })).optional(),
  img_url: y.YjP().optional(),
  measure_info: N.optional(),   // <-- UI item schema 里存在
  customer_cascader_detail: y.g1P(y.YjP(), y.bzn()).optional()
})
```

**N = measure_info 的内部结构：**
```js
N = y.Ikc({
  template_id: y.aig(),       // 数字ID (如 873)
  values: y.YOg(I)          // I 类型数组
})

I = y.Ikc({
  module_id: y.aig(),         // 数字ID (如 1854/1855)
  value: y.YjP(),             // 字符串值 (如 "75")
  prefix: y.YjP().optional(),
  suffix: y.YjP().optional(),
  unit_name: y.YjP().optional(),
  unit_id: y.aig().optional()  // 15 = "%"
})
```

**总提交 schema（module 90665，提交时的最终校验）：**
```js
category_properties: y.g1P(
  y.YjP(),                          // 允许字符串（老格式兼容？）
  y.YOg(y.Ikc({
    value_id: y.YjP(),            // 只显式列这 4 个
    value_name: y.YjP(),
    diy_type: e_.optional(),
    tags: ev.optional()
  }))
).optional()
```

**关键发现：**
- `measure_info` 在 item schema M 里是与 `category_properties` **同级的字段**
- `category_properties` 的提交 schema 只显式列了 4 个字段
- 但 `y.g1P` = "get as possible"，语义上接受任意结构

---

### 2. addWithSchema API 调用结构（module 52639）

```js
// 新增产品
f = function(e, t) {
  return (0, r._)(function() {
    var n = s({});
    return [4, (0, u.b)(
      "/product/tproduct/addWithSchema?check_status=" + t.check_status,
      (0, o._)({ schema: e }, d(e), n, t),
      { withLoadingModal: !0 }
    )];
    [2, r.sent().data]
  })()
}

// 编辑产品
_ = function(e, t, n) {
  return (0, r._)(function() {
    var r = s({});
    return [4, (0, u.b)(
      "/product/tproduct/editWithSchema?check_status=" + n.check_status,
      (0, o._)({ product_id: e, schema: t }, d(t), r, n),
      { withLoadingModal: !0 }
    )];
    [2, i.sent().data]
  })()
}
```

**结论：`addWithSchema` 提交的是 `{ schema: {...} }`，其中 `schema` 包含完整的表单数据。**

---

### 3. category_properties.extra.additions 的真实用途（module 25119）

```js
d = function() {
  var e = (0, i.bI)(), t = (0, i.ox)();
  var d = ((0, a.p)(t.n("category_properties")) || {}).support_desc_predict;
  // ...
  t.n("category_properties").extra.additions || {}
  // ...
}
```

**发现：`extra.additions` 只用于 AI 描述预测相关元数据（`support_desc_predict`、`desc_predict_threshold`），与 `measure_info` 无关。**

---

### 4. spec_detail 中的 measure_info（webpack bundle 第839行附近）

在 submit schema 定义附近找到：
```js
spec_detail: y.YOg(y.Ikc({
  // ... spec values with measure_info ...
  spec_values: [{
    measure_info: N.optional(),   // <-- measure_info 在 spec_detail 里
    // ...
  }]
}))
```

**重要区分：**
- `spec_detail[n].spec_values[n].measure_info` = **尺码规格**的 measure_info
- `category_properties` items 中的 measure_info = **面料材质**的 measure_info

这是**两个不同的数据结构**，都叫 measure_info 但服务于不同的属性类型。

---

### 5. 真实请求体中的 measure_info

从 `spec-recognition/fxg_spec_recognition_upload_and_start_current_page_20260430_continued.json`：

**材质未填时：**
```json
"785": [{"value_id": "", "value_name": ""}]
```

**其他属性（材质已选但 measure_info 为 null）：**
```json
"241": [{"diy_type": 0, "measure_info": null, "tags": null, "value_id": "195685", "value_name": "厚款"}]
```

**关键：measure_info 确实出现在 category_properties 的 item 级别（diy_type/tags 同级），而不是 extra/additions。**

---

### 6. 后端校验错误

当 `category_properties/785` 只写 `value_name=棉`（无 value_id，无 measure_info）时：
```
属性:面料材质填写不符合要求,棉必须与measure_info匹配,
请至抖店商品编辑页面刷新页面重试
```

**后端确实在用 measure_info 做业务校验。**

---

### 7. 已确认枚举值

| 属性 | value_id | value_name |
|------|----------|------------|
| 面料材质（棉）| 19165 | 棉 |
| 面料材质（氨纶）| 27486 | 氨纶 |

**measure template：**
```json
{
  "template_id": 873,
  "modules": [
    { "module_id": 1854, "input_type": "enum_diy" },
    { "module_id": 1855, "input_type": "input", "unitOptions": [{ "label": "%", "value": 15 }] }
  ]
}
```

---

### 8. 面料材质 785 的完整合法 payload 结构（已确认）

**推理过程：**
- property 785 有 `measureTemplates` = `[{ template_id: 873, ... }]`
- 当用户在前端 UI 选择"棉"并输入"75%"时，React 状态中会生成 `measure_info` 对象
- 后端报错"棉必须与measure_info匹配"说明后端会解析 measure_info 内容
- `measure_info` 在 category_properties item 级别，与 `diy_type/tags` 同级（已从真实请求确认）

**结论：面料材质 785 的合法 item 结构为：**
```json
{
  "value_id": "19165",
  "value_name": "棉",
  "diy_type": 0,
  "measure_info": {
    "template_id": 873,
    "values": [
      {
        "module_id": 1854,
        "value": "棉",
        "prefix": null,
        "suffix": null,
        "unit_name": null,
        "unit_id": null
      },
      {
        "module_id": 1855,
        "value": "75",
        "prefix": null,
        "suffix": null,
        "unit_name": "%",
        "unit_id": 15
      }
    ]
  },
  "tags": null
}
```

**多材质场景（如棉75%+氨纶25%）：**
```json
{
  "value_id": "19165",
  "value_name": "棉",
  "diy_type": 0,
  "measure_info": {
    "template_id": 873,
    "values": [
      { "module_id": 1854, "value": "棉" },
      { "module_id": 1855, "value": "75", "unit_name": "%", "unit_id": 15 },
      { "module_id": 1854, "value": "氨纶" },
      { "module_id": 1855, "value": "25", "unit_name": "%", "unit_id": 15 }
    ]
  },
  "tags": null
}
```

**后端校验关系：**
- `value_id=19165`（棉）必须配合 `measure_info` 一起发送
- `measure_info.template_id=873` 固定为"面料材质"模板
- `module_id=1854` = 材质名称（enum_diy），`module_id=1855` = 百分比（input，unit=%）
- `unit_id=15` 对应 UI 的 "%" 单位选项

---

### 9. 主图上传与 step1 前端拦截（新增）

#### 9.1 主图上传的底层协议

从 webpack bundle `module 60026` 可确认，`BatchImgUpload` 的本地上传最终走：

```http
POST /product/img/batchupload?_bid=ffa_goods
Content-Type: multipart/form-data
```

**FormData 结构：**
```text
image[0] = <File>
image[1] = <File>
...
extra = {"request_source":"pc"}
```

**已确认行为：**
- 默认上传 API：`/product/img/batchupload`
- 单次超过 10 张图片时，前端会按 10 张一组分批上传
- 前端会按文件 basename 去重，重复图片会被过滤
- 上传成功后返回的图片 URL 至少会先进入上层媒体组件的局部 `value/imgList`；但是否已经同步写入 `formCore` 上的正式 `model.*.value`，仍需按具体区块分别实证

#### 9.2 主图相关的真实提交字段

从已有真实请求样本可确认，step1 的主图相关字段至少分成两组：

```json
"pic": {
  "value": [
    { "url": "https://p3-aio.ecombdimg.com/obj/..." }
  ]
},
"main_image_three_to_four": {
  "value": [
    { "url": "https://p3-aio.ecombdimg.com/obj/..." }
  ]
}
```

这说明：
- `pic` = 1:1 主图集合
- `main_image_three_to_four` = 3:4 主图集合
- 二者都是 `schema.model` 的独立字段，不是同一个字段的不同展示态

#### 9.3 step1 的前端拦截结论

在 9333 研究页对“下一步”进行运行态 hook 后确认：

- 点击“下一步”后 **没有任何** `product/* / schema / material / publish` 请求发出
- 页面也没有进入 step2
- 说明当前页在 **前端校验阶段** 就被拦截，尚未进入协议提交阶段

**结论：**
- 如果主图未形成有效的 `model.pic.value` / `model.main_image_three_to_four.value`
- 则 `addWithSchema` 抓包不会出现，因为请求根本不会发出
- 当前 blocker 不是后端协议，而是 step1 前端态未闭合

#### 9.4 `main_image_three_to_four` 与 step1 后续联动

从真实异步刷新请求样本可确认，`AI规格推荐` 的刷新动作依赖：

```json
{
  "dependencies": [
    "$model.pic",
    "$model.main_image_three_to_four",
    "$model.description",
    "$model.ai_gen_spec"
  ],
  "request": {
    "method": "post",
    "schema_field": ["$model.ai_gen_spec"],
    "url": "/product/tproduct/asyncRefetchSchema?action=ai_gen_spec_refresh"
  }
}
```

**结论：**
- `main_image_three_to_four` 不是纯展示字段，而是会参与 step1 后续异步联动
- 即使 `pic` 已有值，`main_image_three_to_four` 缺失或未闭合，也可能影响页面放行与 AI 预填
- 这与已有真实请求中 `pic.value` 和 `main_image_three_to_four.value` 同时存在的现象一致

#### 9.5 preflight 抓包再次证明：当前未进入协议层

两份历史 preflight capture：

- `submit-preflight/fxg_protocol_capture_main34_crop_current_page_20260430_155925.json`
- `submit-preflight/fxg_protocol_capture_submit_preflight_step2_current_page_20260430_155620.json`

均显示：

```json
{
  "blockedCount": 0,
  "count": 0,
  "requestedEvidence": {
    "addWithSchema": { "requestCount": 0 },
    "imageUpload": { "requestCount": 0 }
  }
}
```

**说明：**
- 当时不只是 `addWithSchema` 没出现
- 连 `batchupload / submitWhiteImg / batchApprovalWhiteImgs` 也没真正打出去
- 因此问题不在抓包窗口设置，而在前端根本没有触发相应协议调用

#### 9.6 新线索：主图可能存在“素材化再应用”的中间层

从 `fxg_material_probe_current_page_20260430_104552.json` 的懒加载素材 chunk 中，发现与主图相关的另一组接口：

```js
materialDetail(e) => GET  /product/tproduct/materialDetail
saveMaterial(e)   => POST /product/tproduct/saveMaterial
batchApplyMaterial(materialId, productId) =>
  POST /product/tproduct/material/batchApplyMaterial
```

其中 `batchApplyMaterial` 的请求体被明确写成：

```json
{
  "material_ids": ["<material_id>"],
  "material_type": 29,
  "product_id": "<product_id>"
}
```

而物料枚举中：

```json
{
  "9": "主图",
  "10": "主图3:4",
  "29": "装修主图"
}
```

**谨慎结论：**
- 前端素材体系里，至少存在一条 `装修主图(29)` 的“保存素材 -> 应用到商品”链路
- 这条链路与直接 `batchupload` 上传并不冲突，可能是上传后的下一层应用动作
- 但**目前还不能断言** step1 的“上传主图”按钮一定直接走 `saveMaterial/batchApplyMaterial`
- 已确认的是：`batchupload` 负责拿到上传结果；`saveMaterial/batchApplyMaterial` 则像是“素材落库并绑定商品”的后续层

**对当前研究的意义：**
- 如果 step1 并不是简单地把 `batchupload` 返回值直接写进 `model.pic.value`
- 那么主图自动化很可能还缺一步“素材应用”动作
- 这可以解释为什么仅靠点击上传按钮或打开本地上传弹窗，页面状态仍然没有闭合

#### 9.7 新实证：主图图片链真正发请求的是 `P.onChange`，不是最底层 input 的 `N.onChange`

2026-05-02 在稳定研究页 `595868...` 上做了两次受控 live 验证：

1. **直接调用隐藏 file input 绑定的 `N.onChange`**
   - 传入 1x1 PNG 的 `FileList`
   - `N.onChange` 返回 `Promise`
   - 但在 8 秒观察窗内 **没有任何** 目标请求发出：
     - 没有 `/product/img/batchupload`
     - 没有 `/product/tproduct/saveMaterial`
     - 没有 `/product/tproduct/material/batchApplyMaterial`

2. **跳过 `N`，直接调用上层媒体组件 `P.onChange([file], { setProgress, files }, undefined)`**
   - 真实命中：

```http
POST /product/img/batchupload?_bid=ffa_goods
Content-Type: multipart/form-data
```

   - 进度回调实测序列：

```json
[1, 100, 0]
```

   - 调用后再次读取组件运行态，主图组件 `P` 的 `value` 已从 `0` 变成 `1`：

```json
{
  "source": "product",
  "scene": "goods_img",
  "value": [
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_48cda64ea61ac5afd3c88146336cbdb3_sx_68_www1-1"
  ]
}
```

**结论：**
- 对图片主图来说，`/product/img/batchupload` 仍然是**真实主上传入口**
- 真正直接触发上传的是上层媒体组件 `P.onChange`
- 最底层隐藏 input 绑定的 `N.onChange` 前面还有一层额外控制逻辑，不能把“给 input 喂文件”简单等同于“会立刻发 upload 请求”
- 这也解释了此前多次“文件 input 已命中但无请求”的现象：卡点不在浏览器找不到 input，而在 `N -> P` 之间的前置控制层

#### 9.8 新实证：仅补齐 1:1 主图后，step1 仍然不会发出下一步请求

在同一页里把 1:1 主图通过 `P.onChange` 成功回填后，立即再次点击“下一步”并监听：

- `/product/tproduct/addWithSchema`
- `/product/tproduct/editWithSchema`
- `/product/tproduct/asyncRefetchSchema`
- `/product/tproduct/getAsyncRefetchSchema`
- `/product/tproduct/saveMaterial`
- `/product/tproduct/material/batchApplyMaterial`

结果仍然是：

```json
{
  "requestCount": 0
}
```

**这说明：**
- `pic.value` 的闭合已经不再是唯一 blocker
- 仅有 1:1 主图，仍不足以让 step1 进入协议层
- `main_image_three_to_four`、主图区其他派生状态，或 step1 的其他前端必填条件，仍至少有一项未闭合
- 但现在可以把问题进一步缩小为：
  - **图片主图上传主链已确认**
  - **下一步放行条件仍未闭环**
  - **后续重点不该再放在“怎么让 hidden input 选中文件”，而应放在“`P.onChange` 成功后，还缺哪一个运行态字段/派生任务”**

**2026-05-02 补充校正：**
- 当前研究页在点击“下一步”时，除主图链路外，`面料材质`、`品牌`、`适用性别` 等 step1 必填项也仍处于未完成状态
- 因此，“点击下一步没有任何协议请求”这条证据，**只能证明 step1 总体未闭合**
- 不能再把这条现象单独归因成“只差主图/主图3:4”
- 后续若要精确验证 `main_image_three_to_four` 是否为**唯一**放行条件，必须在其他必填项也补齐的前提下再做一次受控提交观察

#### 9.9 新实证：`主图3:4` 的真实入口是 `submitImgOptimizeTask4PC -> queryImgOptimizeTask4PC`

2026-05-02 在同一研究页中，对 `主图3:4` 区域的 `从1:1主图智能裁剪` 按钮做了定时点击 + CDP 抓包，抓到以下真实链路：

1. 页面中 `主图3:4` 区域存在一个真实按钮：

```html
<button type="button" class="ecom-g-btn ecom-g-btn-link ecom-g-btn-sm">
  <span>从1:1主图智能裁剪</span>
</button>
```

2. 点击后首先发起任务创建：

```http
POST /product/tproduct/material/imageTextVideo/submitImgOptimizeTask4PC
Content-Type: application/json
```

请求体核心字段：

```json
{
  "img_list": [
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_48cda64ea61ac5afd3c88146336cbdb3_sx_68_www1-1"
  ],
  "optimize_strategy": "34智能裁剪",
  "img_format": 2,
  "optimize_strategy_extra": {
    "request_source": "pc"
  },
  "service_method": "realtime"
}
```

返回值样本：

```json
{
  "code": 0,
  "data": {
    "task_id": "Crop34Pic2_d623cc31-45e0-11f1-9eaf-00163e1b0d49",
    "task_result_total_num": 5,
    "status": "创建成功"
  }
}
```

3. 随后页面立即轮询：

```http
GET /product/tproduct/material/imageTextVideo/queryImgOptimizeTask4PC
```

查询参数里带：

```json
{
  "task_id": "Crop34Pic2_d623cc31-45e0-11f1-9eaf-00163e1b0d49",
  "tool_source": "ecom",
  "optimize_strategy": "34智能裁剪"
}
```

本次轮询返回：

```json
{
  "code": 0,
  "data": {
    "status": "执行失败",
    "msg": "系统繁忙请重试",
    "img_list": [],
    "optimized_img_infos": []
  }
}
```

**这组证据至少确认了 4 件事：**
- `main_image_three_to_four` 的生成入口已经定位，不再是猜测
- 它不是直接从 `addWithSchema`/`editWithSchema` 里后端顺手生成，而是**发布前页面主动触发的独立异步任务**
- 当前已抓到的任务入参直接使用 **1:1 主图 URL (`img_list`)**，不是 `material_id`
- 因此，之前怀疑的 `saveMaterial / batchApplyMaterial` 更可能属于其他素材/视频/工具链，**至少不是当前这条 3:4 智能裁剪主入口**

**当前边界：**
- 已确认 `主图3:4` 的按钮、提交接口、轮询接口、任务模型
- 但这次任务执行失败，尚未拿到成功态的 `optimized_img_infos`
- 所以目前还不能把 `main_image_three_to_four.value` 的最终回填结构写成已闭环结论

**对下一步的直接意义：**
- 现在要找的已不再是“3:4 到底怎么触发”，而是：
  - 什么条件下 `submitImgOptimizeTask4PC` 会成功
  - 成功返回后的 `optimized_img_infos` 如何进入页面运行态
  - 以及 `step1` 的放行是否严格依赖这个任务成功

#### 9.10 新校正：`商品正面图` 属于 `主图3:4` 区块，不是 1:1 主图区主槽

2026-05-02 重新按可见位置梳理了页面上的上传槽位：

- `主图` 区块位于页面较上方，当前已有主图时，可见的是一排 `上传辅助图`
- `主图3:4` 区块位于其下方，早先出现 `商品正面图 / 上传主图` 文案的就是这一块

这意味着此前直接按 `商品正面图` 文案去找 `P.onChange`，命中的其实是 **3:4 区块组件**，不是 1:1 主图区主槽。

**修正后的理解：**
- 1:1 主图区与 3:4 区块各自有独立的媒体组件实例
- 后续如果要验证 `pic.value` 与 `main_image_three_to_four.value` 的对应关系，必须分清楚自己当前命中的是哪一个区块

#### 9.11 新实证：用真实商品主图重跑后，`queryImgOptimizeTask4PC` 已返回 `optimized_img_infos`

在本地临时起了只读 CORS 图片服务后，把真实商品主图 `主图_01.jpg` 构造成 `File`，并通过 1:1 主图区顶部那组可见 `上传辅助图` 对应的 `P.onChange` 送入上传链。

这一步再次真实命中：

```http
POST /product/img/batchupload?_bid=ffa_goods
```

本地文件实测：

```json
{
  "mime": "image/jpeg",
  "size": 285017
}
```

随后再次触发 `从1:1主图智能裁剪`，这次轮询结果相比 9.9 出现了关键变化：

```json
{
  "status": "执行失败",
  "msg": "系统繁忙请重试",
  "img_list": [
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200"
  ],
  "optimized_img_infos": [
    {
      "img_url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200",
      "ori_img_url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_f60d116c1f2ebb0221bd1e5b1e5277f7_sx_285017_www1200-1200"
    }
  ],
  "pic_type": 2
}
```

**这条证据非常关键：**
- 即使接口顶层仍返回 `status=执行失败` / `msg=系统繁忙请重试`
- 响应体里已经第一次出现了 **非空** `optimized_img_infos`
- 且 `ori_img_url` 已经对应到新的真实 1:1 主图 URL，大小也从 `sx_285017_www1200-1200` 能和本地文件量级对上
- `img_url` 则是一张新的 3:4 结果图 URL

**目前最谨慎的结论是：**
- `queryImgOptimizeTask4PC` 的“状态文案”和“结果载荷”不总是严格一致
- 不能只看 `status/msg` 判断任务完全失败
- 对自动化来说，更可靠的成功判据很可能应改为：
  - `optimized_img_infos` 是否非空
  - `ori_img_url` / `img_url` 是否齐全

**仍未闭环的最后一段：**
- 目前已拿到 3:4 结果 URL，但还没直接实证它如何写回页面运行态字段
- 所以下一步应优先确认：
  - `optimized_img_infos[0].img_url` 是否就是 `main_image_three_to_four.value` 的直接来源
  - 页面在什么条件下会把这条结果真正标记为“已完成”而不再显示 `从1:1主图智能裁剪`

#### 9.12 新实证：`optimized_img_infos` 已进入 3:4 预览组件；但当前 `formCore.byPath(...).getValue()` 口径还不能直接证明正式模型是否已写入

2026-05-02 继续在同一研究页 `595868...` 上直接读取运行态，拿到以下两组同时成立的证据：

1. **当前 `formCore.byPath(...).getValue()` 口径，连明显已填字段也会读到 `undefined`**

```js
formCore.byPath('$model.title').getValue() === undefined
formCore.byPath('$model.first_cid').getValue() === undefined
formCore.byPath('$model.tube_height').getValue() === undefined
formCore.byPath('$model.pic').getValue() === undefined
formCore.byPath('$model.pic.value').getValue() === undefined
formCore.byPath('$model.main_image_three_to_four').getValue() === undefined
formCore.byPath('$model.main_image_three_to_four.value').getValue() === undefined
```

这说明：
- 当前直接读 `formCore.byPath(...).getValue()` 的方法，**不能**被当成“正式表单模型是否有值”的最终判据
- 它更像是拿到了路径节点，但没有拿到该页面真实值容器，或还缺另一层解包入口

2. **但 `主图3:4` 区块里已经真实出现了裁剪结果预览图**

页面 DOM 中已能直接读到：

```html
<img src="//p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200~tplv-qzsgku4lz6-fxg-image:0:q75.image">
```

实测尺寸：

```json
{
  "naturalWidth": 900,
  "naturalHeight": 1200
}
```

继续沿该 `<img>` 的 React Fiber 往上追，读到两层关键局部组件：

```json
{
  "name": "Z",
  "source": "product",
  "scene": "goods_img",
  "dataIndex": 0,
  "imgList": [
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200"
  ]
}
```

```json
{
  "name": "AutoCutWrapper",
  "imgUrl": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200",
  "imgRatio": 2,
  "successMessage": "已自动裁剪该图片为3:4比例",
  "hasOnReplace": true
}
```

底层预览 item 组件 `x` 上也能直接读到：

```json
{
  "url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200",
  "value": [
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200"
  ]
}
```

同时，在裁剪按钮所在链路上还能读到一个单独的输入 prop：

```json
{
  "mainImg": [
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_48cda64ea61ac5afd3c88146336cbdb3_sx_68_www1-1",
    "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_f60d116c1f2ebb0221bd1e5b1e5277f7_sx_285017_www1200-1200"
  ]
}
```

**这条新证据把边界收得更清楚：**
- `queryImgOptimizeTask4PC` 返回的 `optimized_img_infos[0].img_url` 已经进入 `主图3:4` 区块的局部预览组件
- 页面也已经能渲染出真实的 3:4 预览图，不再只是抓包层面的“返回过 URL”
- 但由于 `title/类目/筒高` 这类明显已填字段，用同一 `formCore.byPath(...).getValue()` 口径也同样是 `undefined`
- 因此，当前**只能确认“页面局部预览已出现”**，还**不能**仅凭这组 `undefined` 结果断言“正式表单模型未闭合”

**当前最稳妥的理解是：**
- 3:4 裁剪结果至少先进入一层局部媒体状态：`AutoCutWrapper -> Z/x(value/imgList)`
- `formCore` 的真实取值入口还需要继续定位，不能把 `byPath(...).getValue()` 当成最终口径
- 这也解释了为什么页面已经能看到 3:4 预览，但 `从1:1主图智能裁剪` 按钮文案仍未消失，且 step1 仍未必具备放行条件

#### 9.13 新实证：`AutoCutWrapper.onReplace` 已直接指向 `main_image_three_to_four.state.value` 和 `validate()`

继续在运行态读取 `主图3:4` 预览图祖先组件的函数源码，拿到如下关键片段：

```js
function(n,e,t){
  var i;
  (null == (i = B.na("main_image_three_to_four").state.value) ? void 0 : i.map(function(n){
    return n.url
  }).includes(e)) && (
    nv(r, n),
    null == t || t(),
    B.na("main_image_three_to_four").validate()
  )
}
```

其中它正是 `AutoCutWrapper` 组件的 `onReplace`。

同一次运行态读取还确认，3:4 预览上传组件 `Z/x` 的 `onChange` 仍是前面已经实证过的统一媒体上传链：

```js
function(e,n,t){
  // File -> /product/img/batchupload
  // string[] -> eY(...)
}
```

而 `AutoCutWrapper` / `Z` / `x` 当时拿到的关键 props 分别是：

```json
{
  "AutoCutWrapper": {
    "imgUrl": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200",
    "imgRatio": 2,
    "successMessage": "已自动裁剪该图片为3:4比例",
    "hasOnReplace": true
  },
  "Z": {
    "source": "product",
    "scene": "goods_img",
    "dataIndex": 0,
    "imgList": [
      "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200"
    ]
  },
  "x": {
    "url": "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200",
    "value": [
      "https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_651bca8eff0f7ba1dc4ad7c12d371514_sx_346025_www900-1200"
    ]
  }
}
```

**这条证据把链路再收窄了一层：**
- `main_image_three_to_four` 并不是一个完全独立于字段系统之外的“纯局部 UI 状态”
- 至少在 `AutoCutWrapper.onReplace` 这一步，代码已经显式引用了 `B.na("main_image_three_to_four").state.value`
- 并且在替换后会立刻调用 `B.na("main_image_three_to_four").validate()`

**同时也暴露了一个新的可能卡点：**
- `onReplace` 只有在 `state.value.map(item => item.url).includes(e)` 为真时才继续执行
- 也就是说，它要求被替换的旧 URL `e` 已经预先存在于 `main_image_three_to_four.state.value`
- 如果当前 3:4 结果图只是进入了 `AutoCutWrapper/Z/x` 的局部预览层，但旧值/正式值集合不同步，就可能出现：
  - 页面能看见 3:4 预览图
  - 但 `main_image_three_to_four` 的字段校验并没有真正转为成功态

**与当前页面现象的对照：**
- 再次点击“下一步”后，仍然没有任何 `product/*` XHR/Fetch 请求发出
- 页面顶部同时出现过多条 toast：
  - `图片裁切失败，请稍后重试或选择手动上传`
  - `请将图片裁剪为3:4比例`
- 这说明当前 3:4 链路最需要继续确认的，不再是“接口有没有返回结果图”，而是：
  - `B.na("main_image_three_to_four").state.value` 的真实当前值是什么
  - `onReplace` 是否真的被执行
  - 以及它为什么没有把当前 3:4 结果稳定转成可通过校验的字段状态

---

## 核心矛盾与推理

### 问题：measure_info 在 item schema M 中存在，但在 category_properties 提交 schema 中没有显式字段

**可能解释：**

1. **猜想 A（高概率）**：`category_properties` 的 item 实际结构比 schema 显示的更丰富
   - `y.g1P(y.YjP(), y.YOg(y.Ikc({...})))` 中 `y.g1P` 语义为"尽量宽松"
   - 实际 item 可能包含 measure_info 字段，只是 schema 没有完全暴示
   - 真实结构可能是：
     ```js
     {
       value_id: "19165",
       value_name: "棉",
       diy_type: 0,        // 可选
       tags: null,         // 可选
       measure_info: {     // 实际存在但 schema 未显式声明
         template_id: 873,
         values: [{
           module_id: 1854,
           value: "棉",
           unit_id: 15
         }]
       }
     }
     ```

2. **猜想 B**：item 中的 measure_info 被合并到了 `spec_detail` 路径
   - 但这与后端错误信息"棉必须与measure_info匹配"不符

3. **猜想 C**：measure_info 的数据通过其他字段间接传递
   - 例如 `value_id` 的编码中包含了 template_id 和 module_id 信息

---

## 待验证项（优先级从高到低）

1. **【最高】** 抓取包含正确面料材质数据的真实 `addWithSchema` 提交请求体
   - 目标：确认 measure_info 是否在 category_properties item 内
   - 方法：让页面填好棉（75%）+ 氨纶（25%），然后在提交时拦截网络请求

2. **【高】** 确认 `value_id=19165` 是否必须配合 `measure_info` 一起发送
   - 如果不配 measure_info 只发 value_id，是否通过后端校验？

3. **【高】** 确认后端是否真的校验 `measure_info` 的 `template_id` / `module_id` / `value` 三元组
   - 如果 template_id=873 对应"棉材质"的专属模板，则后端校验逻辑清晰

4. **【中】** 探索面料材质 UI 中输入 75% 后，React 状态如何转换为 measure_info 对象

## 文件索引

| 文件 | 用途 |
|------|------|
| `captures/material/fxg_material_probe_current_page_20260430_104552.json` | webpack bundle 源码，包含 M/N/I schema 定义 |
| `captures/spec-recognition/fxg_spec_recognition_upload_and_start_current_page_20260430_continued.json` | 真实请求体样本 |
| `schemas/live/fxg_schema_probe_current_page_20260430_104552.json` | measure template 枚举值 |
| `schemas/submit/fxg_submit_probe_current_page_20260430_104552.json` | 提交 schema（但 measure_info 不在顶级） |
