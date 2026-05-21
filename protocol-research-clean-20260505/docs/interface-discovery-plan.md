# 接口发现计划

创建日期：2026-05-05

## 阶段拆分

| 阶段 | 目标 | 可能接口 | 风险 | 第一轮动作 |
| --- | --- | --- | --- | --- |
| 会话环境 | 确认已登录发布页和 CDP 可用 | `/json/list`、页面 DOM 状态 | 只读 | `npm run check:cdp` |
| 类目搜索 | 根据关键词拿叶子类目 | `/product/tproduct/searchCategoryN` | 只读 | `npm run probe:fxg-schema` |
| Schema | 拿表单字段、必填项、规格轴 | `/product/tproduct/getSchema` | 只读 | `npm run probe:fxg-schema`、`probe:fxg-runtime-options` |
| 运费 | 读取运费模板选项 | `/product/tproduct/refetchSchema?action=freight_template_options_load` | 只读 | `npm run probe:fxg-freight` |
| 主图上传 | 上传主图得到平台 URL | `/product/img/batchupload` | 写入 | 先只做模块扫描；样本上传需单独确认 |
| 媒体处理 | 3:4、白底、视频任务 | 待探针确认 | 写入/任务 | 先抓包观察，不主动触发 |
| SKU 结构 | 构造规格轴和 SKU 行 | `addWithSchema/editWithSchema` envelope 内字段 | 写入 | 先截停，不放行 |
| 价格库存 | 写入价格、库存、发货 | 可能在 `sku_detail` 和提交 envelope 内 | 写入 | 第一优先级截停实证 |
| 最终提交 | 保存草稿/发布 | `/product/tproduct/addWithSchema`、`/product/tproduct/editWithSchema` | 高风险写入 | 只做本地截停和离线分析 |

## 第一轮执行顺序

1. 检查 CDP 环境。
2. 跑只读 schema/runtime/freight 探针。
3. 生成本目录去敏摘要。
4. 用截停模式观察最终 envelope，优先关注 `sku_detail`、`stock_info`、运费和上下架字段。
5. 离线分析请求体，不 replay、不正式提交。

## 接口状态标签

- `source_hint`：源码或前端模块线索。
- `readonly_verified`：只读请求已在当前环境验证。
- `blocked_capture_verified`：写请求已被本地截停并得到去敏请求体。
- `server_accept_verified`：服务端接受结果已验证。
- `blocked`：缺关键字段或校验规则。
- `excluded`：确认不是当前阶段必经链。

## 当前默认目标阶段

第一阶段执行器候选：价格库存。

理由：

- 当前 DOM 阶段慢且易受虚拟表格影响。
- 字段范围比完整提交小。
- 成功后能直接提升流水线稳定性。
