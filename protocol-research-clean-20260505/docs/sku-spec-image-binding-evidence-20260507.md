# SKU 规格图协议绑定证据

采集时间：2026-05-07
来源：npm run probe:fxg-submit (CDP Runtime.evaluate，Webpack 模块分析)

## 核心发现

### 1. sku_pic 字段已确认（module 90665）

Zod schema 定义（混淆变量名已推断类型）：

```javascript
X = y.Ikc({
  id: y.YjP().optional(),           // string (optional)
  sku_id: y.YjP().optional(),       // string (optional)
  spec_detail_ids: y.YOg(y.YjP()).optional(),  // array<string> (optional)
  sku_pic: y.YOg(y.YjP()).optional(),          // array<string> (optional) ← 规格图
  price: y.YjP().optional(),        // string (optional)
  stock: y.aig().optional(),        // number (optional)
  stock_info: F.optional(),         // { stock_num, stock_inc_num, use_cargo_stock } (optional)
  ...
})

sku_detail: y.YOg(X)  // array<X> - SKU 数组
```

**结论：`sku_pic` 是 `sku_detail[]` 内的字段，类型为 `array<string>`，直接接受图片 URL 数组。**

### 2. addWithSchema 请求体组装路径（module 51313）

```javascript
f = function(e, t) {
  return n = s({}),
  [4, (0, u.b)(
    "/product/tproduct/addWithSchema?check_status=".concat(t.check_status),
    (0, o._)({ schema: e }, d(e), n, t),  // schema + context + pass_through_extra + options
    { withLoadingModal: !0 }
  )]
}
```

body 合并顺序：
1. `{ schema: model }` ← 包含 sku_detail[].sku_pic
2. `{ category_id, context: { ...schema.context, gray_components: undefined } }`
3. `{ pass_through_extra, optional recruit_info }`
4. submit options object (含 check_status)

### 3. spec_detail_ids 映射方式（module 90912）

```javascript
spec_key: null == (u = e.spec_detail_ids) ? void 0 : u.join(",")
```

每个 SKU 行通过 `spec_detail_ids` (规格值ID数组) 唯一标识。

## 协议化路径确认

SKU 规格图协议化只需两步：

1. **上传图片**：POST /product/img/batchupload (已 server_accept_verified)
   → 返回平台图片 URL

2. **绑定到 SKU**：将 URL 填入 addWithSchema 的 sku_detail[].sku_pic 数组
   → 随最终的 addWithSchema 提交

**不需要 saveMaterial / batchApplyMaterial**（这些是主图装修和白底图审核专用的）。

## 待验证

- [ ] sku_pic URL 是否可以独立通过 editWithSchema 补丁单个 SKU
- [ ] 批量上传多个规格图时，URL 如何对应到具体 SKU（按上传顺序？）
- [ ] 截停一个真实的 addWithSchema 请求体验证完整字段映射
