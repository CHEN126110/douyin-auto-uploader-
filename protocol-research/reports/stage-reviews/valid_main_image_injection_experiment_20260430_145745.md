# 有效主图注入实验复盘

## 基本信息

| 项目 | 内容 |
| --- | --- |
| 阶段名称 | 有效主图注入实验 |
| 样本 | `current_page` |
| 执行时间 | `2026-04-30 14:51` 至 `2026-04-30 14:57` |
| 测试图片 | `项目备份 禁止改动使用 只参考/C-975/主图/1200/1200-1.jpg` |
| 说明 | 图片只读使用，未改动备份目录内容 |

## 本轮实际执行内容

- 用 `C-975/主图/1200/1200-1.jpg` 替换之前的 `128x128.png` 图标样本。
- 收窄 `inject_main_image_via_cdp.mjs` 的状态采样范围，只保留主图区域、活动 `file input` 和按钮状态。
- 分别执行：
  - 直接文件注入
  - 先点主图卡位再文件注入
  - 点坐标命中的真实节点后再文件注入
- 对页面和媒体捕获产物做对照。

## 实际产物

- `captures/material/fxg_dom_valid_main_image_injection_current_page_20260430_145500.json`
- `captures/material/fxg_dom_valid_main_image_injection_after_click_current_page_20260430_145640.json`
- `captures/material/fxg_dom_valid_main_image_injection_after_point_click_current_page_20260430_145745.json`

## 已确认事实

- 主图组件运行时校验明确要求：
  - `mime = jpg,png,jpeg`
  - `minWidth = 600`
  - `minHeight = 600`
  - `maxSize = 5`
- 因此此前用 `128x128.png` 做实验不能代表真实主图上传路径。
- 换成 `1200-1.jpg` 后，终端输出一度出现 `上传中100%` 文本。
- 但以页面快照和注入结果文件为准：
  - `nextButtonDisabled` 仍然是 `true`
  - `titleValue` 为空
  - `activeFileInput` 为 `null`
  - 所有 `fileInputs[*].filesLength` 最终都回到 `0`
- 即使先点击主图卡位，或者点坐标命中的真实节点，再执行 `DOM.setFileInputFiles`，结果也没有变化。

## 当前结论

- 这轮已经可以明确排除一种常见误判：
  - 问题不只是“测试图尺寸太小”
  - 真正问题是“当前通过 `DOM.setFileInputFiles` 命中的通用 `file input`，并不是主图上传组件认可的活动入口”
- 也就是说：
  - 有效主图文件本身不是唯一阻塞
  - 上传组件还依赖更深的活动节点、弹层状态或内部动作链

## 对第二轮的影响

- 后续不应再把“往当前选中的隐藏 `file input` 塞文件”当成主推进路径。
- 更值得继续挖的方向是：
  - 主图卡位上的真实活动上传节点
  - `uploadActions` 对应的本地上传动作入口
  - 第 1 步完成后是否存在更稳定的页面状态复用方式
