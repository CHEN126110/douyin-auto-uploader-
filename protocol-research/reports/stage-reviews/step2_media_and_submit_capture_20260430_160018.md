# Step 2 媒体与提交截取复盘

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 阶段名称 | 第 2 步媒体与提交截取 |
| 样本 | `current_page` |
| 执行时间 | `2026-04-30 15:56` 至 `2026-04-30 16:00` |
| 页面状态 | 已进入第 2 步商品信息编辑页 |

## 本轮实际执行内容

- 在第 2 步页面对 `发布商品` 执行一次 `submit-preflight` 截取。
- 对 `主图3:4` 的 `从1:1主图智能裁剪` 执行一次广义 XHR/Fetch 捕获。
- 结合页面快照确认主图已落入第 1 步表单、标题已通过推荐填入、第 2 步页面已成功进入。

## 已确认事实

- `发布商品` 被点击后，本轮 `submit-preflight` 截取结果为：
  - `count = 0`
  - `blockedCount = 0`
  - 没有命中 `addWithSchema/editWithSchema`
- 页面同时给出了清晰的前端校验阻塞：
  - `面料材质` 必填
  - `品牌` 必填
  - `规格不能为空`
  - `请先选择商品规格`
- 因此这次未抓到最终提交请求，不是捕获器失效，而是页面在前端校验阶段就阻断了提交流程。

- `从1:1主图智能裁剪` 在宽网络捕获中已实证命中两条真实接口：
  - `POST /product/tproduct/material/imageTextVideo/submitImgOptimizeTask4PC`
  - `GET /product/tproduct/material/imageTextVideo/queryImgOptimizeTask4PC`
- `submitImgOptimizeTask4PC` 的真实请求体关键字段包括：
  - `img_list`: 当前 1:1 主图 URL
  - `optimize_strategy`: `34智能裁剪`
  - `img_format`: `2`
  - `optimize_strategy_extra.request_source`: `pc`
  - `service_method`: `realtime`
  - `trace_id`
- `queryImgOptimizeTask4PC` 的真实轮询参数关键字段包括：
  - `task_id`
  - `tool_source=ecom`
  - `optimize_strategy=34智能裁剪`

## 当前结论

- 第 2 步已经可以稳定进入，这意味着后续研究不需要再反复从第 1 步空白页起步。
- 最终提交链路当前的真实阻塞在前端校验，不在协议提交器本身。
- `主图3:4` 的智能裁剪不是纯前端本地动作，而是明确走了后端任务接口。
- 因此媒体链目前新增了一段已实证链路：
  - `1:1 主图 URL` -> `submitImgOptimizeTask4PC` -> `queryImgOptimizeTask4PC` -> `3:4 主图结果`

## 尚未确认

- 这轮尚未补到 `queryImgOptimizeTask4PC` 的响应体预览和最终 `3:4` 结果字段。
- 尚未确认 `3:4` 结果最终是直接写回 `main_image_three_to_four`，还是还要经过额外素材应用步骤。
- 尚未拿到 `addWithSchema/editWithSchema` 的真实请求体。

## 下一步建议

- 若继续优先挖媒体链，可单独对 `queryImgOptimizeTask4PC` 做短时响应体捕获。
- 若继续优先挖最终提交链，应先尽量把前端必填阻塞缩减到可发起提交请求的程度，再执行 `submit-preflight`。
