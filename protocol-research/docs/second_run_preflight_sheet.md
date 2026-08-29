# 第二轮本地截停执行单

本文用于承接 `run_20260430_104552` 的第一轮只读 probe 结果。

说明：

- 本文是第二轮执行规划，不代表第二轮已经执行。
- 第二轮目标是尽快拿到真实写链证据；必要时允许从“本地阻断写请求并采集真实请求体摘要”切到“真实送达平台服务端的受控单样本提交验证”。
- 第二轮仍然不接入主项目正式上传主线。

## 前置依据

第一轮只读 probe 已经确认以下事实：

- 当前 live FXG 发布页可被 CDP 命中。
- `addWithSchema/editWithSchema` 已有明确前端装配模块证据。
- `spec_detail/sku_detail/stock_info/qualification/main_pic_video/white_background_pic` 已有 frontend submit schema 形状证据。
- `saveMaterial/materialDetail/submitWhiteImg/batchApprovalWhiteImgs` 已有页面模块候选证据。

## 第二轮目标

- 拿到被本地阻断的 `addWithSchema/editWithSchema` 请求体摘要。
- 拿到 `price/stock/stock_info/spec_detail_ids` 的真实提交关系。
- 拿到 `saveMaterial/materialDetail/batchApplyMaterial` 的真实请求摘要。
- 拿到 `submitWhiteImg` 与 `batchApprovalWhiteImgs` 的真实请求摘要。

## 第二轮优先级

### P0

- `addWithSchema`
- `editWithSchema`
- `spec_detail_ids`
- `price`
- `stock`
- `stock_info`

### P1

- `saveMaterial`
- `materialDetail`
- `batchApplyMaterial`
- `submitWhiteImg`
- `batchApprovalWhiteImgs`

### P2

- `qualification`
- `description`
- 白底图审核回退链

## 建议批次

| 批次 | profile | 目标 | 是否执行 |
| --- | --- | --- | --- |
| `preflight_submit_only` | `submit-only` | 只盯最终 `addWithSchema/editWithSchema` | 未执行 |
| `preflight_submit_full` | `submit-preflight` | 覆盖最终提交、媒体、资质、白底图候选链 | 未执行 |
| `preflight_media_only` | `media-preflight` | 只盯图片、素材、白底图链 | 未执行 |

## 建议执行顺序

### Step 1. 提交前预检窗口

- profile：
  - `submit-only`
- 目标：
  - 先用最小拦截范围确认最终提交通道
- 成功标准：
  - 产物中出现 `addWithSchema` 或 `editWithSchema`

### Step 2. 价库与 SKU 样例窗口

- profile：
  - `submit-preflight`
- 目标：
  - 在接近最终提交的页面状态下，获取 `price/stock/stock_info/spec_detail_ids`
- 成功标准：
  - 产物中出现 `spec_detail_ids`
  - 产物中出现 `stock_info`
  - 能判断 `stock` 和 `stock_info` 的同时出现关系

### Step 3. 素材与白底图窗口

- profile：
  - `media-preflight`
- 目标：
  - 获取 `saveMaterial/materialDetail/submitWhiteImg/batchApprovalWhiteImgs`
- 成功标准：
  - 至少命中一条视频素材链
  - 至少命中一条白底图审核链

## 样本建议

- 主样本：
  - `current_page`
- 如果页面状态允许，建议继续补：
  - `long_socks`
  - `short_socks`

## 产物命名建议

- `fxg_protocol_capture_submit_only_current_page_<timestamp>.json`
- `fxg_protocol_capture_submit_preflight_current_page_<timestamp>.json`
- `fxg_protocol_capture_media_preflight_current_page_<timestamp>.json`

## 风险边界

- 默认先本地截停；如果页面状态、字段和目标链路已经足够明确，也允许把写请求真实送达服务端做单样本验证。
- 一旦进入真实提交验证，必须优先使用当前研究样本、明确记录触发时间、页面状态、结果表现和回滚/清理动作，避免混入不可追踪的历史状态。
- 只要当前页面不是“足够接近提交状态”，就不要把没捕到 `addWithSchema` 误判为接口不存在。
- 如果只命中读请求，结论必须写成“当前页面状态不足以触发目标写接口”。
- 如果没有拿到 `action_list`、`stock_info`、`qualification` 子键，就仍然按 blocker 处理；即使阶段中使用了临时过渡策略，也不能把缺证字段写成已闭环。

## 当前结论

- 第一轮只读 probe 已经完成，第二轮目标和批次已经明确。
- 但截至当前回写时，第二轮本地截停仍未正式完成。
- 新增的真实阻塞是：
  - 当前 live 页面停在第 1 步。
  - `20260430_142845` 的单样本上传探针已证明 `/product/img/batchupload` 可成功返回图片 URL。
  - 但 `DOM.setFileInputFiles` 注入隐藏 `input[type=file]` 不能让页面 `下一步` 解锁。
  - `20260430_143240` 的 `media-preflight` 截取也证明，这种注入动作不会触发任何目标媒体写请求。
  - `20260430_145745` 进一步证明：即使换成 `C-975` 中满足 `600x600+` 的真实主图，当前通用隐藏 `file input` 注入仍不会成为活动上传入口。
- 继续研究后又补到一条新的真实边界：
  - `商品规格` 区的 `智能识图填写规格` 入口实际存在，但真实入口是先打开右侧 `AI识图填写规格` 抽屉。
  - 抽屉图片上传仍会命中 `/product/img/batchupload`，随后点击 `开始识别` 会走 `asyncRefetchSchema?action=ai_gen_spec_refresh` 与 `getAsyncRefetchSchema` 异步任务链。
  - 当前样本图只识别出了 `码数=均码`、`筒高长度=中筒袜`，没有补到必填 `颜色分类`，因此抽屉 `确认填写` 继续禁用，`商品规格` 阻塞仍未解除。
- 因此当前更准确的进入条件是：
  - 要么拿到“组件认可的主图绑定方式”，把页面推进到第 2 步；
  - 要么直接复用一个已经处于第 2 步及之后的 live 页面，再执行 `submit-only` 或 `submit-preflight`。
  - 若走 `商品规格` 这条缩减阻塞路径，则还必须先补齐 `颜色分类` 这类必填规格项，否则 AI 识图结果无法回填到主页面。
