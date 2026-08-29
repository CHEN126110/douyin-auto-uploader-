# 第一轮执行单

本文是第一轮只读研究的实际执行单。

说明：

- 本文不是结果报告。
- 本文只定义“本轮准备执行什么、把产物放到哪里、执行后要回写哪些文档”。
- 未实际跑出的探针结果，不视为已验证。

## 本轮目标

- 完成第一轮只读探针准备与执行顺序收口。
- 产出当前页面基线样本的环境、schema、runtime、freight、submit、qualification、material 证据。
- 为第二轮本地截停研究建立明确入口。

## 本轮样本

| 项目 | 值 | 状态 |
| --- | --- | --- |
| `sample` | `current_page` | 已定义 |
| `run_id` | `run_20260430_104552` | 已定义并用于首轮产物命名 |
| 页面类型 | FXG 发布页当前页面基线 | 已定义 |
| 是否真实提交 | 否 | 已定义 |
| 是否修改主链路 | 否 | 已定义 |

## 本轮输出目录

| 类型 | 目录 | 状态 |
| --- | --- | --- |
| 环境产物 | `protocol-research/captures/environment/` | 已创建 |
| 资质产物 | `protocol-research/captures/qualification/` | 已创建 |
| 素材产物 | `protocol-research/captures/material/` | 已创建 |
| 提交前截停产物 | `protocol-research/captures/submit-preflight/` | 已创建 |
| live schema | `protocol-research/schemas/live/` | 已创建 |
| runtime schema | `protocol-research/schemas/runtime/` | 已创建 |
| freight schema | `protocol-research/schemas/freight/` | 已创建 |
| submit schema | `protocol-research/schemas/submit/` | 已创建 |
| category matrix | `protocol-research/schemas/category-matrix/` | 已创建 |
| 阶段报告 | `protocol-research/reports/stage-reviews/` | 已创建 |
| blocker 报告 | `protocol-research/reports/blocker-reviews/` | 已创建 |

## 执行顺序

### Step 1. 生成本轮批次号

- 动作：
  - 按 `artifact_naming_convention.md` 生成本轮 `run_id`
- 输出：
  - 本轮所有产物统一使用同一时间戳
- 状态：
  - 已完成

### Step 2. 环境检查

- 工具目标：
  - `cdp_environment_check`
- 预期产物：
  - `env_check_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/captures/environment/`
- 完成标准：
  - 确认当前不是登录页、风控页、空白页
- 状态：
  - 已完成

- 本轮实际结果：
  - 已确认本地后端健康，`health_check` 返回 `status=ok`、`port=5001`。
  - 首次 `cdp_environment_check` 返回 `fetch failed`，说明当时没有可用的 CDP 调试端口。
  - 随后已通过 MCP `debug_browser_launch` 成功启动 Chrome 调试浏览器，调试地址为 `127.0.0.1:9333`。
  - 中途一度落在登录页，但后续已进入已登录的 FXG 发布页。
  - 最终复查 `cdp_environment_check` 结果为：`matchingTargetCount=1`、`readyForFxgProtocolProbe=true`。
  - 标准环境产物已写入：`captures/environment/env_check_current_page_20260430_104552.json`

- 当前结论：
  - 当前环境已满足第一轮只读 FXG 协议探针运行前提。

### Step 3. schema 基线

- 工具目标：
  - `cdp_fxg_schema_probe`
- 预期产物：
  - `fxg_schema_probe_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/schemas/live/`
- 完成标准：
  - 得到当前类目、叶子类目、字段总量
- 状态：
  - 已完成

### Step 4. runtime options 基线

- 工具目标：
  - `cdp_fxg_runtime_options_probe`
- 预期产物：
  - `fxg_runtime_options_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/schemas/runtime/`
- 完成标准：
  - 得到必填属性、规格轴、SKU 列、控制字段、运费模板
- 状态：
  - 已完成

### Step 5. freight 基线

- 工具目标：
  - `cdp_fxg_freight_probe`
- 预期产物：
  - `fxg_freight_probe_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/schemas/freight/`
- 完成标准：
  - 得到模板名称与模板 ID 映射
- 状态：
  - 已完成

### Step 6. submit 字段形状基线

- 工具目标：
  - `cdp_fxg_submit_probe`
- 预期产物：
  - `fxg_submit_probe_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/schemas/submit/`
- 完成标准：
  - 固化媒体、资质、SKU、控制字段的 shape
- 状态：
  - 已完成

### Step 7. qualification 基线

- 工具目标：
  - `cdp_fxg_qualification_probe`
- 预期产物：
  - `fxg_qualification_probe_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/captures/qualification/`
- 完成标准：
  - 明确页面资质区块与 `qualification` 线索边界
- 状态：
  - 已完成

### Step 8. material 基线

- 工具目标：
  - `cdp_fxg_material_probe`
- 预期产物：
  - `fxg_material_probe_current_page_<timestamp>.json`
- 落盘目录：
  - `protocol-research/captures/material/`
- 完成标准：
  - 明确视频、白底图、素材相关候选链路
- 状态：
  - 已完成

### Step 9. category matrix 基线

- 工具目标：
  - `cdp_fxg_category_matrix_probe`
- 预期产物：
  - `fxg_category_matrix_socks_<timestamp>.json`
- 落盘目录：
  - `protocol-research/schemas/category-matrix/`
- 完成标准：
  - 明确类目差异是否影响字段生成策略
- 状态：
  - 已完成

### Step 10. 文档回写

- 需要回写：
  - `docs/field_evidence_matrix.md`
  - `docs/dom_upload_pipeline_map.md`
  - `reports/stage-reviews/`
- 回写内容：
  - 本轮 `run_id`
  - 实际产物文件名
  - 新增已实证字段
  - 仍未补齐的 blocker
- 状态：
  - 进行中

## 本轮完成条件

只有同时满足下面条件，本文这一轮才可以标记为“已完成”：

1. 上述 8 类只读产物实际存在。
2. 文件名符合命名规范。
3. 至少有一份阶段报告回写到 `reports/stage-reviews/`。
4. 字段证据矩阵已经根据实际产物更新。

## 当前事实状态

截至当前回写时，只能确认下面事实：

- 本轮执行单文档已写入。
- 本轮目录骨架已创建。
- 本轮样本和输出路径已定义。
- 本地后端已确认健康。
- 调试 Chrome 已实际拉起，地址为 `127.0.0.1:9333`。
- 当前已命中已登录 FXG 发布页，环境检查产物已落盘。
- schema、runtime、freight、submit、qualification、material、category matrix 探针已实际执行，并已生成对应 JSON 产物。
- 文档回写正在进行中。
- 任何字段都不能因为本文存在而自动视为“已验证”。
