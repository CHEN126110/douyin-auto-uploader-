# 商品规格 AI 识图链路复盘

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 阶段名称 | 商品规格 AI 识图链路 |
| `run_id` | `continued_20260430_spec_recognition` |
| 样本 | `current_page` + `C-975/SKU/2双装/1细条纹+大宽条.jpg` |
| 执行时间 | `2026-04-30（本轮继续研究）` |
| 页面基线 | `https://fxg.jinritemai.com/ffa/g/create?`，当前类目为 `中筒袜` |
| 执行类型 | `只读观察 + 页面态验证 + 去敏网络捕获` |

## 本轮实际执行内容

- 在当前发布页重新定位 `商品规格` 区真实入口，确认 `智能识图填写规格 -> 立即上传图片` 不是普通 `button`，而是 `div.styles_uploadImgBtn__KH1g7`。
- 点击该入口，确认页面会打开右侧 `AI识图填写规格` 抽屉，而不是直接在主页面内联上传。
- 新增独立研究脚本 `protocol-research/scripts/inject_spec_recognition_image_via_cdp.mjs`，用于：
  - 自动确保抽屉已打开；
  - 对抽屉内隐藏 `image/*` 输入框执行 `DOM.setFileInputFiles`；
  - 回读抽屉状态；
  - 捕获与规格识图相关的 XHR/Fetch 请求。
- 以只读样本图 `C-975/SKU/2双装/1细条纹+大宽条.jpg` 执行一轮上传，再执行一次 `开始识别`。

## 实际产物

- `captures/spec-recognition/fxg_spec_recognition_upload_and_start_current_page_20260430_continued.json`
- `scripts/inject_spec_recognition_image_via_cdp.mjs`

## 已确认事实

- `商品规格` 区确实存在可触发的 AI 识图入口，上一轮的 `smart-sku-button-missing` 结论不再成立。
- 点击 `立即上传图片` 后会打开 `AI识图填写规格` 抽屉；抽屉内存在独立隐藏图片上传输入控件。
- 抽屉图片上传与主图上传共用了 `POST /product/img/batchupload`：
  - 首次空表单请求返回 `code=10002`、`msg=请上传图片`；
  - 带文件请求返回 `code=0`，并回包图片 URL。
- 点击 `开始识别` 后，页面不是本地识别，而是走了真实后端链路：
  - `POST /product/tproduct/asyncRefetchSchema?action=ai_gen_spec_refresh`
  - 多次 `POST /product/tproduct/getAsyncRefetchSchema?action=ai_gen_spec_refresh&task_id=...`
- `asyncRefetchSchema` 首次返回 `async_options.url=/product/tproduct/getAsyncRefetchSchema?action=ai_gen_spec_refresh&task_id=...`，说明这是异步任务型接口而非单次同步返回。
- 最终成功响应里，`ai_gen_spec.value.predict_spec_from_pics` 已给出真实预测结果：
  - `码数 -> 均码`
  - `筒高长度 -> 中筒袜`
- 同一成功响应里，`ai_gen_spec.additions.spec_items` 明确返回了规格项要求：
  - `cp_id=2752`，required=`true`
  - `cp_id=3939`，required=`true`
  - `cp_id=4706`，required=`false`
  - `cp_id=93`，required=`false`
- 抽屉最终文案变为：
  - `已帮你识别出2种规格类型`
  - 可见候选值 `均码`、`中筒袜`
- 当前抽屉里的 `确认填写` 仍然禁用，这与响应体一致：
  - 识图结果只覆盖了 `码数` 和 `筒高长度`
  - 没有覆盖必填规格项 `颜色分类`

## 未确认事项

- 这轮尚未确认 `颜色分类` 是否只能人工补，还是还存在第二种图片/按钮入口可继续补齐。
- 尚未确认点击抽屉内具体候选值后，页面主规格区会不会立即回填。
- 尚未确认 `确认填写` 解锁后，主页面的 `spec_detail` / `sku_detail` 会生成什么真实结构。

## 字段影响

| 字段 | 变化前状态 | 变化后状态 | 依据 |
| --- | --- | --- | --- |
| `spec_detail` | `已知形状`，仅有 schema 证据 | `已知形状`，新增 AI 识图预测值与必填规格项证据 | `fxg_spec_recognition_upload_and_start_current_page_20260430_continued.json` |
| `spec_detail[].spec_values[]` | `已知形状`，缺真实规格值样例 | `已知形状`，已拿到 `均码` / `中筒袜` 的真实候选值与 `cpv_id/cpv_path` 结构 | `fxg_spec_recognition_upload_and_start_current_page_20260430_continued.json` |
| `sku_detail` | `已知形状`，缺组合生成证据 | `已知形状`，仍未生成，因为必填规格项未补齐 | 同上 |

## 当前 blocker

- AI 规格识图当前不能单独解除 `商品规格` 阻塞。
- 根因不是识图接口不存在，而是：
  - 当前样本只识别出了 `码数` 和 `筒高长度`；
  - 必填规格项 `颜色分类` 没有预测结果；
  - 因此抽屉 `确认填写` 继续禁用，SKU 组合表也不会生成。

## 下一步建议

- 优先补查 `颜色分类` 的来源：
  - 看当前页面是否已有主图或规格图能继续触发颜色识别；
  - 或确认它是否只能人工新建/输入。
- 如果能把 `颜色分类` 补齐，再次观察：
  - 抽屉 `确认填写` 是否解锁；
  - 页面是否生成 `spec_detail` 和价格库存表；
  - `submit-preflight` 是否开始命中最终提交链。
