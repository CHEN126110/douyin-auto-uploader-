# Step 1 绑定实验复盘

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 阶段名称 | 第 1 步主图绑定实验 |
| 样本 | `current_page` |
| 执行时间 | `2026-04-30 14:28` 至 `2026-04-30 14:32` |
| 页面基线 | FXG 发布页第 1 步 |
| 执行类型 | DOM 注入实验 + 媒体写接口截取 |

## 实际执行内容

- 用 `cdp_fxg_upload_probe` 执行单样本图片上传探针。
- 新建 `inject_main_image_via_cdp.mjs`，通过 CDP `DOM.setFileInputFiles` 向隐藏 `input[type=file]` 注入本地样本图片。
- 在页面中填写标题字段。
- 先点击 `上传主图` 再重复做一次文件注入。
- 在 `media-preflight` 截停窗口中重放文件注入，检查是否触发真实媒体写请求。

## 实际产物

- `captures/material/fxg_upload_probe_sample_current_page_20260430_142845.json`
- `captures/material/fxg_dom_main_image_injection_current_page_20260430_142845.json`
- `captures/material/fxg_dom_main_image_injection_after_click_current_page_20260430_143100.json`
- `captures/submit-preflight/fxg_protocol_capture_media_preflight_injection_current_page_20260430_143240.json`
- `scripts/inject_main_image_via_cdp.mjs`

## 已确认事实

- 单样本上传探针真实命中了 `/product/img/batchupload`。
- 该样本上传的真实响应摘要显示：
  - `httpStatus=200`
  - `code=0`
  - `dataType=array`
  - `dataLength=1`
- 去敏后的响应值显示 `data[0]` 是一个图片 URL 字符串。
- 通过 CDP 定位到的当前隐藏文件输入节点是 `nodeId=24`。
- 无论是否先点击 `上传主图`，通过 `DOM.setFileInputFiles` 向该输入框注入图片后：
  - 页面标题可以正常填写
  - `下一步` 仍然保持 `disabled=true`
- 在 `media-preflight` 截取窗口中重放该注入动作后：
  - `count=0`
  - `blockedCount=0`
  - `image_upload.requestCount=0`
  - 没有任何目标媒体写请求被命中

## 未确认事项

- 当前隐藏文件输入是否只是上传组件内部的备用节点，而不是实际接收主图上传事件的活动节点。
- 点击 `上传主图` 后，页面是否还需要额外的组件上下文、拖拽态或弹层态才能接受文件。
- 当前页面是否存在更深层的上传组件状态机，导致简单的 `setFileInputFiles` 不能触发上传逻辑。

## 关键结论

- “向当前隐藏 file input 注入本地文件”并不足以把第 1 步页面推进到可点击 `下一步` 的状态。
- 这个结论不只是来自按钮状态，还来自一轮真实媒体截取结果：
  - 注入动作没有触发 `/product/img/batchupload`
  - 也没有触发其他媒体链相关写请求
- 因此当前不能把这条 CDP 注入路径当成可用的自动推进方案。

## 当前 blocker

- 第二轮本地截停要拿 `addWithSchema/editWithSchema`，前提是页面先跨过第 1 步。
- 目前已知的通用 CDP 注入路径不能让页面跨过第 1 步。
- 因此第二轮的真实 blocker 变成：
  - 缺少一种“组件认可的主图绑定/上传推进方式”
  - 或者缺少已经处于第 2 步及之后的页面状态

## 下一步建议

- 优先研究主图上传组件的活动节点、弹层态、拖拽态或内部 store 写入入口。
- 如果短期内不能拿到组件认可的上传推进方式，就把第二轮执行入口切换成：
  - 复用已人工推进到第 2 步的 live 页面
  - 再执行 `submit-preflight` / `submit-only`
